"""Background worker that drives persistent PPT Master Agent sessions."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from time import time
from uuid import UUID, uuid4

from service.agent_runner import AgentRunCancelled, AgentRunner, RunnerResult
from service.billing import BillingRepository
from service.config import Settings
from service.database import Database
from service.queue import JobClaim, JobQueue
from service.reference_catalog import reference_case_labels
from service.repository import JobRepository
from service.runtime_config import RuntimeConfigRepository
from service.schemas import JobStatus, TERMINAL_STATUSES
from service.storage import JobStorage, RevisionScope


logger = logging.getLogger(__name__)

_RUNNING_STAGE_RANK = {
    JobStatus.INTAKE: 0,
    JobStatus.PLANNING: 1,
    JobStatus.ACQUIRING: 2,
    JobStatus.EXECUTING: 3,
    JobStatus.VALIDATING: 4,
    JobStatus.EXPORTING: 5,
}


def _split_assets(
    assets: list[dict],
    storage: JobStorage,
) -> tuple[list[str], list[str], dict[str, str]]:
    source_paths: list[str] = []
    reference_paths: list[str] = []
    reference_names: dict[str, str] = {}
    for asset in assets:
        path = asset["storage_path"]
        if storage.asset_role(path) == "reference":
            reference_paths.append(path)
            reference_names[path] = asset["filename"]
        else:
            source_paths.append(path)
    return source_paths, reference_paths, reference_names


async def _record_reference_usage(
    job_id: UUID,
    result: RunnerResult,
    allowed_reference_paths: list[str],
    reference_names: dict[str, str],
    repository: JobRepository,
    storage: JobStorage,
    runner: AgentRunner,
) -> None:
    manifest_path = storage.prepare_job(job_id) / "control" / "references.json"
    previous: dict = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}

    labels = reference_case_labels(runner.reference_cases)
    case_ids = list(
        dict.fromkeys(
            case_id for case_id in result.reference_case_ids if case_id in labels
        )
    )
    allowed_paths = set(allowed_reference_paths)
    reference_paths = list(
        dict.fromkeys(path for path in result.reference_files if path in allowed_paths)
    )
    manifest = {
        "reference_case_ids": case_ids,
        "reference_case_labels": [labels[case_id] for case_id in case_ids],
        "reference_files": reference_paths,
        "reference_file_names": [
            reference_names.get(path, Path(path).name) for path in reference_paths
        ],
    }
    if manifest == previous:
        return
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    used_labels = [
        *manifest["reference_case_labels"],
        *manifest["reference_file_names"],
    ]
    message = (
        f"本次使用参考：{'、'.join(used_labels)}"
        if used_labels
        else "本次未使用参考案例"
    )
    job = await repository.get_job(job_id)
    await repository.add_event(
        job_id,
        "references",
        job["stage"] if job else JobStatus.INTAKE.value,
        message,
        {
            "reference_case_ids": case_ids,
            "reference_files": reference_paths,
        },
    )


async def _record_artifacts(
    job_id: UUID,
    result: RunnerResult,
    repository: JobRepository,
    storage: JobStorage,
) -> None:
    job_dir = storage.job_dir(job_id)
    paths: list[Path] = []
    for relative_path in result.artifact_paths:
        candidate = (job_dir / relative_path).resolve()
        try:
            storage.resolve_job_file(job_id, relative_path)
        except (FileNotFoundError, ValueError):
            continue
        paths.append(candidate)

    stored_files = [storage.describe_existing(job_id, path) for path in paths]
    if not stored_files:
        stored_files = storage.discover_artifacts(job_id)
    unique_files = {
        stored_file.relative_path: stored_file for stored_file in stored_files
    }
    for stored_file in unique_files.values():
        suffix = Path(stored_file.filename).suffix.lower()
        parts = Path(stored_file.relative_path).parts
        if suffix == ".pptx":
            kind = "pptx"
        elif suffix == ".svg" and "svg_output" in parts and "backup" not in parts:
            kind = "preview"
        elif suffix in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
            kind = "asset"
        else:
            kind = "document"
        await repository.add_artifact(job_id, kind, stored_file)


def _pending_turn_usage_path(storage: JobStorage, job_id: UUID) -> Path:
    return storage.prepare_job(job_id) / "control" / "pending_turn_usage.json"


def _read_pending_turn_usage(path: Path) -> tuple[str, int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        turn_id = str(payload["turn_id"]).strip()
        input_tokens = max(0, int(payload["input_tokens"]))
        output_tokens = max(0, int(payload["output_tokens"]))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("pending turn usage is invalid") from exc
    if not turn_id:
        raise RuntimeError("pending turn usage has no turn_id")
    return turn_id, input_tokens, output_tokens


async def _settle_turn_usage(
    job: dict,
    repository: JobRepository,
    billing: BillingRepository,
    storage: JobStorage,
    *,
    turn_id: str,
    input_tokens: int,
    output_tokens: int,
    cumulative_pages: int | None = None,
) -> None:
    """Settle one organization turn from durable usage values."""
    org_id = job.get("org_id")
    if org_id is None:
        return
    progress = storage.inspect_workspace(job["id"])
    try:
        pricing = await billing.get_pricing()
        await repository.record_turn_usage(
            job["id"],
            org_id,
            job["owner_id"],
            turn_id=turn_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cumulative_images=progress.image_generation_total,
            cumulative_pages=(
                progress.page_count if cumulative_pages is None else cumulative_pages
            ),
            price_input_token=pricing.price_input_token,
            price_output_token=pricing.price_output_token,
            price_image=pricing.price_image,
        )
    except Exception:
        logger.exception("Could not record turn usage for %s", job["id"])
        raise


async def _meter_pending_turn(
    job: dict,
    repository: JobRepository,
    billing: BillingRepository,
    storage: JobStorage,
) -> None:
    """Settle a turn saved before a worker interruption, then remove the sidecar."""
    path = _pending_turn_usage_path(storage, job["id"])
    if not path.is_file():
        return
    if job.get("org_id") is None:
        path.unlink(missing_ok=True)
        return
    turn_id, input_tokens, output_tokens = _read_pending_turn_usage(path)
    revision_scope = storage.load_revision_scope(job["id"])
    await _settle_turn_usage(
        job,
        repository,
        billing,
        storage,
        turn_id=turn_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cumulative_pages=(
            len(revision_scope.page_order) if revision_scope is not None else None
        ),
    )
    path.unlink(missing_ok=True)


async def _meter_turn(
    job: dict,
    result: RunnerResult,
    repository: JobRepository,
    billing: BillingRepository,
    storage: JobStorage,
    *,
    cumulative_pages: int | None = None,
) -> None:
    """Settle a completed turn and clear its durable pending-usage sidecar."""
    path = _pending_turn_usage_path(storage, job["id"])
    if job.get("org_id") is None:
        path.unlink(missing_ok=True)
        return
    turn_id = result.turn_id
    input_tokens = result.input_tokens
    output_tokens = result.output_tokens
    if input_tokens is None or output_tokens is None:
        pending_turn_id, input_tokens, output_tokens = _read_pending_turn_usage(path)
        if turn_id and pending_turn_id != turn_id:
            raise RuntimeError("pending turn usage does not match the completed turn")
        turn_id = pending_turn_id
    elif path.is_file():
        pending_turn_id, _, _ = _read_pending_turn_usage(path)
        if pending_turn_id != turn_id:
            raise RuntimeError("pending turn usage does not match the completed turn")
    await _settle_turn_usage(
        job,
        repository,
        billing,
        storage,
        turn_id=turn_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cumulative_pages=cumulative_pages,
    )
    path.unlink(missing_ok=True)


async def _process_job(
    job_id: UUID,
    repository: JobRepository,
    billing: BillingRepository,
    storage: JobStorage,
    runner: AgentRunner,
    lease_lost: asyncio.Event,
) -> None:
    job = await repository.get_job(job_id)
    if job is None:
        return
    await _meter_pending_turn(job, repository, billing, storage)
    if JobStatus(job["status"]) in TERMINAL_STATUSES:
        await billing.release_hold(job_id)
        return
    if job["cancel_requested"]:
        await repository.set_status(
            job_id, JobStatus.CANCELLED, job["progress"], "Task cancelled"
        )
        await billing.release_hold(job_id)
        return

    job_dir = storage.prepare_job(job_id)

    async def should_cancel() -> bool:
        if lease_lost.is_set():
            return True
        current_job = await repository.get_job(job_id)
        return current_job is None or bool(current_job["cancel_requested"])

    session_id = job.get("runner_session_id") or ""

    async def record_progress(message: str, data: dict[str, str]) -> None:
        try:
            event_data = dict(data)
            thread_id = event_data.pop("thread_id", "")
            if thread_id:
                await repository.set_runner_session(job_id, thread_id)
            current_job = await repository.get_job(job_id)
            activity_stage = (
                current_job["stage"] if current_job else JobStatus.INTAKE.value
            )
            await repository.add_event(
                job_id,
                "activity",
                activity_stage,
                message,
                event_data,
            )
        except Exception:
            logger.exception("Could not persist progress for task %s", job_id)

    assets = await repository.list_assets(job_id)
    published_artifacts = await repository.list_artifacts(job_id)
    published_paths = [artifact["storage_path"] for artifact in published_artifacts]
    source_paths, reference_paths, reference_names = _split_assets(assets, storage)

    revision_scope: RevisionScope | None = None
    if not session_id:
        restart = await repository.consume_confirmation(job_id)
        prompt = job["prompt"]
        if restart is not None:
            response = restart.get("response") or {}
            restart_message = str(response.get("message", "")).strip()
            if restart_message:
                prompt += f"\n\nAdditional user instruction:\n{restart_message}"
        await repository.set_status(
            job_id, JobStatus.INTAKE, 10, "Analyzing source material"
        )
        result = await runner.start(
            job_id,
            job_dir,
            prompt,
            job["route"],
            source_paths,
            reference_paths,
            should_cancel,
            record_progress,
        )
        if result.session_id:
            await repository.set_runner_session(job_id, result.session_id)
    else:
        confirmation = await repository.consume_confirmation(job_id)
        if confirmation is None:
            running_statuses = {
                JobStatus.INTAKE.value,
                JobStatus.PLANNING.value,
                JobStatus.ACQUIRING.value,
                JobStatus.EXECUTING.value,
                JobStatus.VALIDATING.value,
                JobStatus.EXPORTING.value,
            }
            if job["status"] not in running_statuses:
                raise RuntimeError(
                    "No unconsumed user response is available for this task"
                )
            message = (
                "The worker was interrupted. Continue from the existing task files "
                "and current workflow stage without repeating completed work."
            )
            revision_scope = storage.load_revision_scope(job_id)
        else:
            response = confirmation.get("response")
            message = response.get("message", "") if response else "Continue the task."
            if response and response.get("approved"):
                message = message or "Approved. Continue with the confirmed proposal."
            try:
                revision_scope = storage.prepare_revision_scope(
                    job_id,
                    message,
                    published_paths,
                )
            except ValueError as exc:
                failure_message = str(exc)
                await repository.add_message(job_id, "assistant", failure_message)
                await repository.set_status(
                    job_id,
                    JobStatus.FAILED,
                    job["progress"],
                    failure_message,
                    error={
                        "code": "invalid_revision_scope",
                        "message": failure_message,
                    },
                )
                await billing.release_hold(job_id)
                return
        available_source_paths = [
            path for path in source_paths if (job_dir / path).is_file()
        ]
        available_reference_paths = [
            path for path in reference_paths if (job_dir / path).is_file()
        ]
        if available_source_paths:
            message += f"\nContent files currently available: {available_source_paths}"
        if available_reference_paths:
            message += (
                "\nVisual reference files currently available: "
                f"{available_reference_paths}"
            )
        result = await runner.resume(
            job_dir,
            session_id,
            message,
            should_cancel,
            record_progress,
            revision_scope,
        )

    # Meter every turn as soon as the result is in: the turn already consumed cost,
    # so revision-scope violations, failures, and abandons must all be billed too.
    await _meter_turn(
        job,
        result,
        repository,
        billing,
        storage,
        cumulative_pages=(
            len(revision_scope.page_order) if revision_scope is not None else None
        ),
    )

    if revision_scope is not None:
        violations = storage.revision_scope_violations(job_id, revision_scope)
        if violations:
            try:
                storage.restore_revision_scope(job_id, revision_scope)
            except OSError as exc:
                violations.append(f"恢复原文件失败：{exc}")
            failure_message = "单页修改校验失败：" + "；".join(violations)
            await repository.add_message(job_id, "assistant", failure_message)
            await repository.set_status(
                job_id,
                JobStatus.FAILED,
                job["progress"],
                failure_message,
                error={
                    "code": "revision_scope_violation",
                    "message": failure_message,
                    "target_page": revision_scope.target_page,
                    "target_svg": revision_scope.target_svg,
                    "violations": violations,
                },
            )
            return

    await _record_reference_usage(
        job_id,
        result,
        reference_paths,
        reference_names,
        repository,
        storage,
        runner,
    )

    if result.phase == "awaiting_confirmation":
        proposal = result.proposal or {"message": result.message}
        assistant_message = str(
            proposal.get("markdown") or proposal.get("message") or result.message
        ).strip()
        await repository.set_proposal(job_id, proposal, assistant_message)
        await repository.set_status(
            job_id,
            JobStatus.AWAITING_CONFIRMATION,
            25,
            result.message,
        )
    elif result.phase == "awaiting_asset":
        await repository.add_message(job_id, "assistant", result.message)
        await repository.set_status(
            job_id, JobStatus.AWAITING_ASSET, 45, result.message
        )
    elif result.phase == "succeeded":
        await repository.set_status(
            job_id, JobStatus.VALIDATING, 90, "Collecting outputs"
        )
        await _record_artifacts(job_id, result, repository, storage)
        await repository.add_message(job_id, "assistant", result.message)
        await repository.set_status(job_id, JobStatus.SUCCEEDED, 100, result.message)
    else:
        await repository.add_message(job_id, "assistant", result.message)
        await repository.set_status(
            job_id,
            JobStatus.FAILED,
            job["progress"],
            result.message,
            error={"code": "agent_failed", "message": result.message},
        )


async def _sync_observed_progress(
    job_id: UUID,
    repository: JobRepository,
    storage: JobStorage,
    changed_after: float,
    previous_page_count: int,
) -> int:
    job = await repository.get_job(job_id)
    if job is None:
        return previous_page_count
    current_status = JobStatus(job["status"])
    if current_status in TERMINAL_STATUSES or current_status in {
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.AWAITING_ASSET,
    }:
        return previous_page_count

    observed = storage.inspect_workspace(job_id, changed_after)
    target_status: JobStatus | None = None
    message = ""
    progress = job["progress"]
    if observed.presentation_ready:
        target_status = JobStatus.EXPORTING
        message = "正在导出并检查最终文件"
        progress = 80
    elif observed.quality_report_ready:
        target_status = JobStatus.VALIDATING
        message = "正在检查页面和文件"
        progress = 75
    elif observed.page_output_updated:
        target_status = JobStatus.EXECUTING
        message = f"正在生成页面，已完成 {observed.page_count} 页"
        progress = 50
    elif observed.image_generation_updated:
        image_count = observed.image_generation_count
        count_label = f" {image_count} 张" if image_count else ""
        if observed.image_generation_state == "running":
            target_status = JobStatus.ACQUIRING
            message = f"正在调用生图模型生成{count_label}素材图"
            progress = 45
        elif observed.image_generation_state == "succeeded":
            target_status = JobStatus.EXECUTING
            message = "素材图生成完成，正在更新页面"
            progress = 50

    current_rank = _RUNNING_STAGE_RANK.get(current_status, -1)
    target_rank = _RUNNING_STAGE_RANK.get(target_status, -1)
    if target_status is not None and target_rank > current_rank:
        await repository.set_status(job_id, target_status, progress, message)
    elif (
        observed.page_output_updated
        and observed.page_count != previous_page_count
        and current_status is JobStatus.EXECUTING
    ):
        await repository.add_event(
            job_id,
            "activity",
            JobStatus.EXECUTING.value,
            f"已完成 {observed.page_count} 页",
            {"page_count": observed.page_count},
        )
    return observed.page_count


async def _maintain_claim(
    claim: JobClaim,
    queue: JobQueue,
    repository: JobRepository,
    storage: JobStorage,
    settings: Settings,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    loop = asyncio.get_running_loop()
    last_renewed = loop.time()
    changed_after = time()
    previous_page_count = storage.inspect_workspace(claim.job_id).page_count
    while not stop.is_set():
        try:
            renewed = await queue.renew(claim, settings.job_lease_seconds)
            if not renewed:
                lease_lost.set()
                return
            last_renewed = loop.time()
        except Exception:
            logger.exception("Could not renew task lease for %s", claim.job_id)
            if loop.time() - last_renewed >= settings.job_lease_seconds:
                lease_lost.set()
                return

        try:
            previous_page_count = await _sync_observed_progress(
                claim.job_id,
                repository,
                storage,
                changed_after,
                previous_page_count,
            )
        except Exception:
            logger.exception("Could not inspect task progress for %s", claim.job_id)

        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=settings.job_heartbeat_seconds,
            )
        except TimeoutError:
            continue


async def _maintain_worker_presence(
    queue: JobQueue,
    worker_id: str,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            await queue.heartbeat_worker(worker_id, settings.job_lease_seconds)
        except Exception:
            logger.exception("Could not publish worker heartbeat for %s", worker_id)
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=settings.job_heartbeat_seconds,
            )
        except TimeoutError:
            continue


async def run_worker() -> None:
    """Consume Redis jobs until the process is stopped."""
    settings = Settings.from_env()
    settings.validate()
    database = Database(settings.database_url)
    queue = JobQueue(settings.redis_url, settings.queue_name)
    storage = JobStorage(settings.runtime_root, settings.max_upload_bytes)
    await database.connect()
    await database.verify_schema()
    await queue.healthcheck()
    runtime_config_repository = RuntimeConfigRepository(database, settings)
    runner = AgentRunner(settings, await runtime_config_repository.get())
    await runner.open()
    repository = JobRepository(database)
    billing = BillingRepository(database)
    worker_id = uuid4().hex
    stop_presence = asyncio.Event()
    presence_task = asyncio.create_task(
        _maintain_worker_presence(queue, worker_id, settings, stop_presence)
    )

    try:
        while True:
            recovered = await queue.recover_expired()
            if recovered:
                logger.warning("Recovered %s expired task lease(s)", recovered)
            claim = await queue.dequeue(settings.job_lease_seconds)
            if claim is None:
                continue
            stop_monitor = asyncio.Event()
            lease_lost = asyncio.Event()
            monitor_task = asyncio.create_task(
                _maintain_claim(
                    claim,
                    queue,
                    repository,
                    storage,
                    settings,
                    stop_monitor,
                    lease_lost,
                )
            )
            acknowledge = False
            try:
                await runner.reconfigure(await runtime_config_repository.get())
                await _process_job(
                    claim.job_id,
                    repository,
                    billing,
                    storage,
                    runner,
                    lease_lost,
                )
                acknowledge = True
            except AgentRunCancelled:
                if lease_lost.is_set():
                    logger.warning(
                        "Stopped task %s after its lease was lost", claim.job_id
                    )
                else:
                    cancelled_job = await repository.get_job(claim.job_id)
                    if cancelled_job is not None:
                        await _meter_pending_turn(
                            cancelled_job,
                            repository,
                            billing,
                            storage,
                        )
                    await repository.set_status(
                        claim.job_id,
                        JobStatus.CANCELLED,
                        0,
                        "Task cancelled",
                    )
                    await billing.release_hold(claim.job_id)
                    acknowledge = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if lease_lost.is_set():
                    logger.warning(
                        "Task %s failed after its lease was lost; leaving recovery "
                        "to the next worker: %s",
                        claim.job_id,
                        exc,
                    )
                    continue
                failed_job = await repository.get_job(claim.job_id)
                if failed_job is not None:
                    await _meter_pending_turn(
                        failed_job,
                        repository,
                        billing,
                        storage,
                    )
                await repository.set_status(
                    claim.job_id,
                    JobStatus.FAILED,
                    0,
                    "Task execution failed",
                    error={"code": "worker_error", "message": str(exc)},
                )
                await billing.release_hold(claim.job_id)
                acknowledge = True
            finally:
                stop_monitor.set()
                await monitor_task
                if acknowledge:
                    await queue.acknowledge(claim)
    finally:
        stop_presence.set()
        await presence_task
        await queue.forget_worker(worker_id)
        await runner.close()
        await queue.close()
        await database.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
