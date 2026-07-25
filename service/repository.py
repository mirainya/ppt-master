"""Durable job, event, confirmation, and file records."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from service.database import Database
from service.schemas import TERMINAL_STATUSES, JobRoute, JobStatus
from service.storage import StoredFile
from service.webhooks import build_final_payload, build_turn_payload


logger = logging.getLogger(__name__)


class OrganizationUnavailableError(RuntimeError):
    """Raised when an organization cannot create new jobs."""


class OrganizationQuotaExceededError(RuntimeError):
    """Raised when an organization has exhausted a job quota."""


class JobRepository:
    """Apply task state changes through parameterized PostgreSQL queries."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_job(
        self,
        job_id: UUID,
        owner_id: UUID,
        prompt: str,
        route: JobRoute,
        title: str | None,
        org_id: UUID | None = None,
    ) -> dict[str, Any]:
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                if org_id is not None:
                    organization = await connection.fetchrow(
                        """
                        SELECT status, daily_job_limit, max_active_jobs
                        FROM organizations
                        WHERE id = $1
                        FOR UPDATE
                        """,
                        org_id,
                    )
                    if organization is None or organization["status"] != "active":
                        raise OrganizationUnavailableError("organization is not active")
                    counts = await connection.fetchrow(
                        """
                        SELECT
                            COUNT(*) FILTER (
                                WHERE status NOT IN ('cancelled', 'failed', 'succeeded')
                            ) AS active,
                            COUNT(*) FILTER (
                                WHERE created_at >= date_trunc('day', CURRENT_TIMESTAMP)
                            ) AS today
                        FROM jobs
                        WHERE org_id = $1
                        """,
                        org_id,
                    )
                    if int(counts["active"]) >= int(organization["max_active_jobs"]):
                        raise OrganizationQuotaExceededError(
                            "too many active tasks for this organization"
                        )
                    if int(counts["today"]) >= int(organization["daily_job_limit"]):
                        raise OrganizationQuotaExceededError(
                            "daily task limit reached for this organization"
                        )
                record = await connection.fetchrow(
                    """
                    INSERT INTO jobs
                        (id, owner_id, org_id, title, prompt, route,
                         status, stage, progress)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7, 0)
                    RETURNING *
                    """,
                    job_id,
                    owner_id,
                    org_id,
                    title,
                    prompt,
                    route.value,
                    JobStatus.QUEUED.value,
                )
                await self._add_event(
                    connection,
                    job_id,
                    "status",
                    JobStatus.QUEUED.value,
                    "Task accepted",
                    {"progress": 0},
                )
                await self._add_message(connection, job_id, "user", prompt)
        return dict(record)

    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM jobs WHERE id = $1",
            job_id,
        )
        return dict(record) if record else None

    async def get_job_for_user(
        self,
        job_id: UUID,
        owner_id: UUID,
        *,
        include_unowned: bool,
    ) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            SELECT * FROM jobs
            WHERE id = $1
              AND (owner_id = $2 OR ($3 AND owner_id IS NULL))
            """,
            job_id,
            owner_id,
            include_unowned,
        )
        return dict(record) if record else None

    async def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM jobs
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            max(1, min(limit, 100)),
        )
        return [dict(record) for record in records]

    async def list_jobs_for_user(
        self,
        owner_id: UUID,
        limit: int = 50,
        *,
        include_unowned: bool,
    ) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM jobs
            WHERE owner_id = $1 OR ($2 AND owner_id IS NULL)
            ORDER BY updated_at DESC
            LIMIT $3
            """,
            owner_id,
            include_unowned,
            max(1, min(limit, 100)),
        )
        return [dict(record) for record in records]

    async def list_all_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """List every task across all owners, newest first, with owner username."""
        records = await self.database.require_pool().fetch(
            """
            SELECT job.*, account.username AS owner_username
            FROM jobs AS job
            LEFT JOIN users AS account ON account.id = job.owner_id
            ORDER BY job.updated_at DESC
            LIMIT $1
            """,
            max(1, min(limit, 200)),
        )
        return [dict(record) for record in records]

    async def mark_job_purged(self, job_id: UUID) -> dict[str, Any] | None:
        """Stamp files_purged_at once the on-disk files are gone."""
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE jobs AS job
            SET files_purged_at = CURRENT_TIMESTAMP
            WHERE job.id = $1
            RETURNING job.*,
                (SELECT username FROM users WHERE id = job.owner_id) AS owner_username
            """,
            job_id,
        )
        return dict(record) if record else None

    async def list_purgeable_jobs(self, cutoff: datetime) -> list[dict[str, Any]]:
        """Terminal tasks last updated before cutoff that still hold files."""
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM jobs
            WHERE status IN ('succeeded', 'failed', 'cancelled')
              AND updated_at < $1
              AND files_purged_at IS NULL
            ORDER BY updated_at ASC
            """,
            cutoff,
        )
        return [dict(record) for record in records]

    async def record_turn_usage(
        self,
        job_id: UUID,
        org_id: UUID,
        end_user_id: UUID,
        *,
        turn_id: str,
        input_tokens: int,
        output_tokens: int,
        cumulative_images: int,
        cumulative_pages: int,
        price_input_token: float,
        price_output_token: float,
        price_image: float,
    ) -> dict[str, Any] | None:
        """Record one turn's metering delta and settle its charge atomically.

        Idempotency key is the Codex turn id, so a crash/lease-recovery re-run of the
        same turn cannot double-bill. Tokens are per-turn from the runner; images/pages
        are cumulative on disk, so the per-turn delta subtracts earlier turns' totals.

        Settlement: the first billed turn reconciles the creation-time hold
        (refund or extra-charge the gap to the real cost); later turns charge the
        real cost directly. Balance may go negative, capped by the per-job hold risk.
        Returns the usage row plus the charged cost, or None if already billed.
        """
        turn_id = turn_id.strip()
        if not turn_id:
            raise ValueError("turn_id is required for idempotent billing")
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                job = await connection.fetchrow(
                    "SELECT billed_turns, held_amount FROM jobs WHERE id = $1 FOR UPDATE",
                    job_id,
                )
                if job is None:
                    return None
                held_amount = float(job["held_amount"])
                totals = await connection.fetchrow(
                    """
                    SELECT COALESCE(SUM(images), 0) AS images,
                           COALESCE(SUM(pages), 0) AS pages
                    FROM usage_records
                    WHERE job_id = $1
                    """,
                    job_id,
                )
                images_delta = max(0, cumulative_images - int(totals["images"]))
                pages_delta = max(0, cumulative_pages - int(totals["pages"]))
                safe_input = max(0, input_tokens)
                safe_output = max(0, output_tokens)
                actual_cost = round(
                    safe_input * price_input_token
                    + safe_output * price_output_token
                    + images_delta * price_image,
                    4,
                )
                record = await connection.fetchrow(
                    """
                    INSERT INTO usage_records
                        (id, org_id, end_user_id, job_id, turn_id,
                         input_tokens, output_tokens, images, pages, charged_credits)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (job_id, turn_id) DO NOTHING
                    RETURNING *
                    """,
                    uuid4(),
                    org_id,
                    end_user_id,
                    job_id,
                    turn_id,
                    safe_input,
                    safe_output,
                    images_delta,
                    pages_delta,
                    actual_cost,
                )
                if record is None:
                    return None
                await connection.execute(
                    "UPDATE jobs SET billed_turns = billed_turns + 1 WHERE id = $1",
                    job_id,
                )
                if held_amount > 0:
                    # Reconcile the actual hold reserved for this turn, then clear it.
                    delta = round(held_amount - actual_cost, 4)
                    reason = "settle_refund" if delta >= 0 else "settle_extra"
                    await connection.execute(
                        "UPDATE jobs SET held_amount = 0 WHERE id = $1",
                        job_id,
                    )
                else:
                    # A recovered legacy turn may have no outstanding hold.
                    delta = -round(actual_cost, 4)
                    reason = "settle_extra"
                balance_after = await connection.fetchval(
                    """
                    UPDATE organizations
                    SET credit_balance = credit_balance + $2
                    WHERE id = $1
                    RETURNING credit_balance
                    """,
                    org_id,
                    delta,
                )
                await connection.execute(
                    """
                    INSERT INTO credit_transactions
                        (id, org_id, amount, reason, job_id, balance_after)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    uuid4(),
                    org_id,
                    delta,
                    reason,
                    job_id,
                    balance_after,
                )
                await self._try_enqueue_turn_webhook(connection, record, job_id, org_id)
                result = dict(record)
                result["actual_cost"] = round(actual_cost, 4)
                return result

    async def _try_enqueue_turn_webhook(
        self,
        connection: asyncpg.Connection,
        record: asyncpg.Record,
        job_id: UUID,
        org_id: UUID,
    ) -> None:
        """Queue this turn's callback without ever endangering the charge.

        The whole judgment — reading org_webhooks, building the payload, inserting
        the row — sits in one savepoint. Protecting only the insert would leave the
        reads bare, so an unreadable callback table would roll back the charge it
        rode with, which is exactly what this design must not allow.
        """
        try:
            async with connection.transaction():
                if await self._webhook_target(connection, org_id):
                    await self._enqueue_turn_webhook(connection, record, job_id, org_id)
        except Exception:
            logger.exception("Could not queue usage.turn webhook for %s", job_id)

    async def _enqueue_turn_webhook(
        self,
        connection: asyncpg.Connection,
        record: asyncpg.Record,
        job_id: UUID,
        org_id: UUID,
    ) -> None:
        """Snapshot this turn's usage into a queued callback event.

        Runs on the billing connection so the cumulative total already includes
        the row inserted above, which a separate connection could not yet see.
        """
        totals = await self._job_usage_totals(connection, job_id)
        job = await connection.fetchrow(
            "SELECT status, owner_id FROM jobs WHERE id = $1",
            job_id,
        )
        end_user_id = await connection.fetchval(
            "SELECT external_id FROM users WHERE id = $1",
            record["end_user_id"],
        )
        event_id = uuid4()
        payload = build_turn_payload(
            event_id=event_id,
            org_id=org_id,
            job_id=job_id,
            end_user_id=end_user_id,
            job_status=job["status"] if job else "",
            turn_id=record["turn_id"],
            turn_index=totals["turns"],
            occurred_at=record["created_at"],
            delta={
                "input_tokens": record["input_tokens"],
                "output_tokens": record["output_tokens"],
                "images": record["images"],
                "pages": record["pages"],
                "credits": record["charged_credits"],
            },
            job_total=totals,
        )
        await self._enqueue_webhook(
            connection,
            org_id=org_id,
            job_id=job_id,
            event_type="usage.turn",
            event_key=record["turn_id"],
            payload=payload,
        )

    async def get_job_usage(self, job_id: UUID) -> dict[str, Any]:
        """Aggregate one job's metered usage and the credits we charged for it."""
        async with self.database.require_pool().acquire() as connection:
            return await self._job_usage_totals(connection, job_id)

    @staticmethod
    async def _job_usage_totals(
        connection: asyncpg.Connection,
        job_id: UUID,
    ) -> dict[str, Any]:
        """Sum a job's usage on a caller-supplied connection.

        Takes the connection so the webhook enqueue inside record_turn_usage can
        read the turn it just inserted, which a separate connection could not see
        before that transaction commits.
        """
        usage = await connection.fetchrow(
            """
            SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(images), 0) AS images,
                   COALESCE(SUM(pages), 0) AS pages,
                   COALESCE(SUM(charged_credits), 0) AS charged_credits,
                   COUNT(*) AS turns
            FROM usage_records
            WHERE job_id = $1
            """,
            job_id,
        )
        return {
            "input_tokens": int(usage["input_tokens"]),
            "output_tokens": int(usage["output_tokens"]),
            "images": int(usage["images"]),
            "pages": int(usage["pages"]),
            "turns": int(usage["turns"]),
            "our_charge": float(usage["charged_credits"]),
        }

    async def aggregate_org_usage(
        self,
        org_id: UUID,
        *,
        external_id: str | None = None,
        since: Any | None = None,
        until: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate an org's usage grouped by enterprise end-user (external_id)."""
        records = await self.database.require_pool().fetch(
            """
            SELECT u.external_id AS end_user_id,
                   COALESCE(SUM(ur.input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(ur.output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(ur.images), 0) AS images,
                   COALESCE(SUM(ur.pages), 0) AS pages,
                   COALESCE(SUM(ur.charged_credits), 0) AS our_charge,
                   COUNT(DISTINCT ur.job_id) AS jobs
            FROM usage_records AS ur
            JOIN users AS u ON u.id = ur.end_user_id
            WHERE ur.org_id = $1
              AND ($2::text IS NULL OR u.external_id = $2)
              AND ($3::timestamptz IS NULL OR ur.created_at >= $3)
              AND ($4::timestamptz IS NULL OR ur.created_at < $4)
            GROUP BY u.external_id
            ORDER BY u.external_id
            """,
            org_id,
            external_id,
            since,
            until,
        )
        return [
            {
                "end_user_id": record["end_user_id"],
                "input_tokens": int(record["input_tokens"]),
                "output_tokens": int(record["output_tokens"]),
                "images": int(record["images"]),
                "pages": int(record["pages"]),
                "our_charge": float(record["our_charge"]),
                "jobs": int(record["jobs"]),
            }
            for record in records
        ]

    async def set_status(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        progress = max(0, min(progress, 100))
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    UPDATE jobs
                    SET status = $2, stage = $2, progress = $3, error = $4,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                    RETURNING *
                    """,
                    job_id,
                    status.value,
                    progress,
                    error,
                )
                if record:
                    await self._add_event(
                        connection,
                        job_id,
                        "status",
                        status.value,
                        message,
                        {"progress": progress, "error": error},
                    )
                    if status in TERMINAL_STATUSES:
                        await self._try_enqueue_final_webhook(connection, record)
        return dict(record) if record else None

    async def _try_enqueue_final_webhook(
        self,
        connection: asyncpg.Connection,
        job: asyncpg.Record,
    ) -> None:
        """Queue the terminal callback without ever endangering the status write.

        A rollback here would leave the job stuck short of its terminal state, and
        the worker's own failure path also goes through set_status, so the job
        would be re-leased and re-run forever while burning real cost.
        """
        try:
            async with connection.transaction():
                if await self._webhook_target(connection, job["org_id"]):
                    await self._enqueue_final_webhook(connection, job)
        except Exception:
            logger.exception("Could not queue usage.final webhook for %s", job["id"])

    async def _enqueue_final_webhook(
        self,
        connection: asyncpg.Connection,
        job: asyncpg.Record,
    ) -> None:
        """Queue the terminal usage event for a job that just reached a final state.

        Keyed on billed_turns so a job resumed after a terminal state (the resume
        endpoint accepts succeeded/failed) emits a fresh event for its new total
        instead of being swallowed by the idempotency key.
        """
        job_id = job["id"]
        totals = await self._job_usage_totals(connection, job_id)
        end_user_id = await connection.fetchval(
            "SELECT external_id FROM users WHERE id = $1",
            job["owner_id"],
        )
        event_id = uuid4()
        payload = build_final_payload(
            event_id=event_id,
            org_id=job["org_id"],
            job_id=job_id,
            end_user_id=end_user_id,
            job_status=job["status"],
            occurred_at=job["updated_at"],
            job_total=totals,
        )
        await self._enqueue_webhook(
            connection,
            org_id=job["org_id"],
            job_id=job_id,
            event_type="usage.final",
            event_key=str(job["billed_turns"]),
            payload=payload,
        )

    async def list_events(
        self, job_id: UUID, after_id: int = 0
    ) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            """
            SELECT * FROM job_events
            WHERE job_id = $1 AND id > $2
            ORDER BY id ASC
            LIMIT 200
            """,
            job_id,
            after_id,
        )
        return [dict(record) for record in records]

    async def list_messages(self, job_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            "SELECT * FROM job_messages WHERE job_id = $1 ORDER BY id ASC",
            job_id,
        )
        return [dict(record) for record in records]

    async def add_message(
        self,
        job_id: UUID,
        role: str,
        content: str,
    ) -> dict[str, Any] | None:
        content = content.strip()
        if not content:
            return None
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"unsupported message role: {role}")
        async with self.database.require_pool().acquire() as connection:
            record = await self._add_message(connection, job_id, role, content)
        return dict(record)

    async def add_asset(self, job_id: UUID, stored_file: StoredFile) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO job_assets
                (id, job_id, filename, storage_path, size_bytes, sha256, media_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            stored_file.id,
            job_id,
            stored_file.filename,
            stored_file.relative_path,
            stored_file.size_bytes,
            stored_file.sha256,
            stored_file.media_type,
        )
        return dict(record)

    async def list_assets(self, job_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            "SELECT * FROM job_assets WHERE job_id = $1 ORDER BY created_at ASC",
            job_id,
        )
        return [dict(record) for record in records]

    async def set_proposal(
        self,
        job_id: UUID,
        proposal: dict[str, Any],
        assistant_message: str,
    ) -> None:
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO job_confirmations (job_id, proposal, status)
                    VALUES ($1, $2, 'pending')
                    ON CONFLICT (job_id) DO UPDATE
                    SET proposal = EXCLUDED.proposal, response = NULL, status = 'pending',
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    job_id,
                    proposal,
                )
                if assistant_message.strip():
                    await self._add_message(
                        connection,
                        job_id,
                        "assistant",
                        assistant_message.strip(),
                    )

    async def get_confirmation(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM job_confirmations WHERE job_id = $1",
            job_id,
        )
        return dict(record) if record else None

    async def submit_confirmation(
        self,
        job_id: UUID,
        approved: bool,
        message: str,
    ) -> dict[str, Any] | None:
        response = {"approved": approved, "message": message}
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    UPDATE job_confirmations
                    SET response = $2, status = $3, updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    job_id,
                    response,
                    "approved" if approved else "revision_requested",
                )
                if record:
                    await self._add_message(connection, job_id, "user", message)
        return dict(record) if record else None

    async def consume_confirmation(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE job_confirmations
            SET status = 'consumed', updated_at = CURRENT_TIMESTAMP
            WHERE job_id = $1 AND status IN ('approved', 'revision_requested')
            RETURNING *
            """,
            job_id,
        )
        return dict(record) if record else None

    async def prepare_resume(self, job_id: UUID, message: str) -> dict[str, Any] | None:
        response = {"approved": True, "message": message}
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    UPDATE job_confirmations
                    SET response = $2, status = 'approved',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = $1
                    RETURNING *
                    """,
                    job_id,
                    response,
                )
                if record:
                    await self._add_message(connection, job_id, "user", message)
        return dict(record) if record else None

    async def prepare_restart(self, job_id: UUID, message: str) -> dict[str, Any]:
        """Store an instruction for a failed task that has no resumable thread."""
        response = {"approved": True, "message": message}
        async with self.database.require_pool().acquire() as connection:
            async with connection.transaction():
                record = await connection.fetchrow(
                    """
                    INSERT INTO job_confirmations (job_id, proposal, response, status)
                    VALUES ($1, '{}'::jsonb, $2, 'approved')
                    ON CONFLICT (job_id) DO UPDATE
                    SET response = EXCLUDED.response, status = 'approved',
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING *
                    """,
                    job_id,
                    response,
                )
                await self._add_message(connection, job_id, "user", message)
        return dict(record)

    async def request_cancel(self, job_id: UUID) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            """
            UPDATE jobs
            SET cancel_requested = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND status NOT IN ('succeeded', 'failed', 'cancelled')
            RETURNING *
            """,
            job_id,
        )
        return dict(record) if record else None

    async def list_artifacts(self, job_id: UUID) -> list[dict[str, Any]]:
        records = await self.database.require_pool().fetch(
            "SELECT * FROM job_artifacts WHERE job_id = $1 ORDER BY created_at ASC",
            job_id,
        )
        return [dict(record) for record in records]

    async def get_artifact(
        self, job_id: UUID, artifact_id: UUID
    ) -> dict[str, Any] | None:
        record = await self.database.require_pool().fetchrow(
            "SELECT * FROM job_artifacts WHERE job_id = $1 AND id = $2",
            job_id,
            artifact_id,
        )
        return dict(record) if record else None

    async def add_artifact(
        self,
        job_id: UUID,
        kind: str,
        stored_file: StoredFile,
    ) -> dict[str, Any]:
        record = await self.database.require_pool().fetchrow(
            """
            INSERT INTO job_artifacts
                (id, job_id, kind, filename, storage_path, size_bytes, sha256, media_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (job_id, storage_path) DO UPDATE
            SET kind = EXCLUDED.kind,
                filename = EXCLUDED.filename,
                size_bytes = EXCLUDED.size_bytes,
                sha256 = EXCLUDED.sha256,
                media_type = EXCLUDED.media_type
            RETURNING *
            """,
            uuid4(),
            job_id,
            kind,
            stored_file.filename,
            stored_file.relative_path,
            stored_file.size_bytes,
            stored_file.sha256,
            stored_file.media_type,
        )
        return dict(record)

    async def set_runner_session(self, job_id: UUID, session_id: str) -> None:
        await self.database.require_pool().execute(
            """
            UPDATE jobs
            SET runner_session_id = $2, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            job_id,
            session_id,
        )

    async def add_event(
        self,
        job_id: UUID,
        event_type: str,
        stage: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        async with self.database.require_pool().acquire() as connection:
            await self._add_event(
                connection,
                job_id,
                event_type,
                stage,
                message,
                data or {},
            )

    @staticmethod
    async def _add_message(
        connection: asyncpg.Connection,
        job_id: UUID,
        role: str,
        content: str,
    ) -> asyncpg.Record:
        return await connection.fetchrow(
            """
            INSERT INTO job_messages (job_id, role, content)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            job_id,
            role,
            content,
        )

    @staticmethod
    async def _webhook_target(
        connection: asyncpg.Connection,
        org_id: UUID | None,
    ) -> bool:
        """Whether this organization currently wants usage callbacks."""
        if org_id is None:
            return False
        return bool(
            await connection.fetchval(
                "SELECT enabled FROM org_webhooks WHERE org_id = $1",
                org_id,
            )
        )

    @staticmethod
    async def _enqueue_webhook(
        connection: asyncpg.Connection,
        *,
        org_id: UUID,
        job_id: UUID,
        event_type: str,
        event_key: str,
        payload: dict[str, Any],
    ) -> None:
        """Queue one usage callback inside the caller's savepoint.

        Callers wrap this together with the enabled-check and payload build, so no
        savepoint is opened here — nesting a second one would only obscure which
        statements the rollback actually covers.
        """
        await connection.execute(
            """
            INSERT INTO webhook_deliveries
                (id, org_id, job_id, event_type, event_key, payload)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (job_id, event_type, event_key) DO NOTHING
            """,
            uuid4(),
            org_id,
            job_id,
            event_type,
            event_key,
            payload,
        )

    @staticmethod
    async def _add_event(
        connection: asyncpg.Connection,
        job_id: UUID,
        event_type: str,
        stage: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        await connection.execute(
            """
            INSERT INTO job_events (job_id, event_type, stage, message, data)
            VALUES ($1, $2, $3, $4, $5)
            """,
            job_id,
            event_type,
            stage,
            message,
            data,
        )
