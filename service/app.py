"""FastAPI application for remote PPT Master jobs."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, AsyncIterator
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service.auth import (
    AuthenticatedUser,
    generate_api_key,
    generate_session_token,
    hash_password,
    hash_token,
    normalize_username,
    password_needs_rehash,
    verify_missing_user,
    verify_password,
)
from service.auth_repository import AuthRepository
from service.config import Settings
from service.database import Database
from service.queue import JobQueue
from service.repository import JobRepository
from service.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    ArtifactRead,
    AssetRead,
    ConfirmationRead,
    ConfirmationSubmit,
    JobMessageSubmit,
    JobMessageRead,
    JobRead,
    JobRoute,
    JobStatus,
    LoginRequest,
    MessageRead,
    TERMINAL_STATUSES,
    UserRead,
)
from service.storage import JobStorage


bearer_scheme = HTTPBearer(auto_error=False)
SESSION_COOKIE = "ppt_master_session"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    settings.validate()
    database = Database(settings.database_url)
    queue = JobQueue(settings.redis_url, settings.queue_name)
    storage = JobStorage(settings.runtime_root, settings.max_upload_bytes)
    await database.connect()
    await database.verify_schema()
    await queue.healthcheck()
    app.state.settings = settings
    app.state.database = database
    app.state.auth_repository = AuthRepository(database)
    app.state.repository = JobRepository(database)
    app.state.queue = queue
    app.state.storage = storage
    try:
        yield
    finally:
        await queue.close()
        await database.close()


app = FastAPI(
    title="PPT Master API",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    repository: AuthRepository = request.app.state.auth_repository
    if credentials is not None:
        user = await repository.authenticate_api_key(
            hash_token(credentials.credentials)
        )
        if user is None:
            raise _authentication_error()
        return user
    session_token = request.cookies.get(SESSION_COOKIE, "")
    if not session_token:
        raise _authentication_error()
    user = await repository.authenticate_session(hash_token(session_token))
    if user is None:
        raise _authentication_error()
    return user


async def require_browser_user(request: Request) -> AuthenticatedUser:
    session_token = request.cookies.get(SESSION_COOKIE, "")
    if not session_token:
        raise _authentication_error()
    repository: AuthRepository = request.app.state.auth_repository
    user = await repository.authenticate_session(hash_token(session_token))
    if user is None:
        raise _authentication_error()
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(require_user)]
BrowserUser = Annotated[AuthenticatedUser, Depends(require_browser_user)]


def _repository(request: Request) -> JobRepository:
    return request.app.state.repository


async def _require_job(
    request: Request,
    job_id: UUID,
    user: AuthenticatedUser,
) -> dict:
    job = await _repository(request).get_job_for_user(
        job_id,
        user.id,
        include_unowned=user.is_admin,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _select_artifacts(
    artifacts: list[dict],
    live_paths: set[str],
) -> list[dict]:
    normalized: list[dict] = []
    for artifact in artifacts:
        record = dict(artifact)
        path_parts = record["storage_path"].replace("\\", "/").split("/")
        suffix = record["filename"].rsplit(".", 1)[-1].lower()
        is_page_preview = (
            suffix == "svg"
            and "svg_output" in path_parts
            and "backup" not in path_parts
        )
        if record["kind"] == "preview" and not is_page_preview:
            record["kind"] = "asset"
        normalized.append(record)

    records = [
        artifact
        for artifact in normalized
        if artifact["kind"] == "preview" and artifact["storage_path"] not in live_paths
    ]
    deliverables: dict[tuple[str, str], dict] = {}
    for artifact in normalized:
        if artifact["kind"] == "preview":
            continue
        suffix = artifact["filename"].rsplit(".", 1)[-1].lower()
        key = (artifact["kind"], suffix)
        current = deliverables.get(key)
        if current is None:
            deliverables[key] = artifact
            continue
        current_score = (
            current["storage_path"].startswith("artifacts/"),
            current["created_at"],
        )
        candidate_score = (
            artifact["storage_path"].startswith("artifacts/"),
            artifact["created_at"],
        )
        if candidate_score > current_score:
            deliverables[key] = artifact
    records.extend(
        sorted(deliverables.values(), key=lambda artifact: artifact["created_at"])
    )
    return records


def _asset_read(storage: JobStorage, asset: dict) -> dict:
    return {
        **asset,
        "role": storage.asset_role(asset["storage_path"]),
    }


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    await request.app.state.database.healthcheck()
    await request.app.state.queue.healthcheck()
    return {
        "status": "ok",
        "worker": "ok"
        if await request.app.state.queue.worker_available()
        else "unavailable",
    }


@app.post("/v1/auth/login", response_model=UserRead)
async def login(
    request: Request,
    response: Response,
    submission: LoginRequest,
) -> dict:
    repository: AuthRepository = request.app.state.auth_repository
    username = normalize_username(submission.username)
    account = await repository.get_user_by_username(username)
    if account is None:
        verify_missing_user(submission.password)
        raise HTTPException(status_code=401, detail="invalid username or password")
    password_valid = verify_password(account["password_hash"], submission.password)
    if account["disabled"] or not password_valid:
        raise HTTPException(status_code=401, detail="invalid username or password")
    if password_needs_rehash(account["password_hash"]):
        await repository.update_password_hash(
            account["id"],
            hash_password(submission.password),
        )
    session_token = generate_session_token()
    await repository.create_session(
        account["id"],
        hash_token(session_token),
        request.app.state.settings.session_days,
    )
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=request.app.state.settings.session_days * 86_400,
        httponly=True,
        secure=request.app.state.settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {
        "id": account["id"],
        "username": account["username"],
        "is_admin": account["is_admin"],
    }


@app.post("/v1/auth/logout", response_model=MessageRead)
async def logout(request: Request, response: Response) -> MessageRead:
    session_token = request.cookies.get(SESSION_COOKIE, "")
    if session_token:
        await request.app.state.auth_repository.delete_session(
            hash_token(session_token)
        )
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageRead(message="signed out")


@app.get("/v1/auth/me", response_model=UserRead)
async def me(user: CurrentUser) -> AuthenticatedUser:
    return user


@app.get("/v1/auth/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(request: Request, user: BrowserUser) -> list[dict]:
    return await request.app.state.auth_repository.list_api_keys(user.id)


@app.post(
    "/v1/auth/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: Request,
    submission: ApiKeyCreate,
    user: BrowserUser,
) -> dict:
    name = submission.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="API key name is required")
    key, prefix = generate_api_key()
    record = await request.app.state.auth_repository.create_api_key(
        user.id,
        name,
        prefix,
        hash_token(key),
    )
    return {**record, "key": key}


@app.delete(
    "/v1/auth/api-keys/{key_id}",
    response_model=MessageRead,
)
async def revoke_api_key(
    request: Request,
    key_id: UUID,
    user: BrowserUser,
) -> MessageRead:
    revoked = await request.app.state.auth_repository.revoke_api_key(user.id, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    return MessageRead(message="API key revoked")


@app.post(
    "/v1/jobs",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(
    request: Request,
    user: CurrentUser,
    prompt: Annotated[str, Form(min_length=1, max_length=20_000)],
    route: Annotated[JobRoute, Form()] = JobRoute.GENERATE,
    title: Annotated[str | None, Form(max_length=200)] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    references: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    repository = _repository(request)
    job_id = uuid4()
    request.app.state.storage.prepare_job(job_id)
    job = await repository.create_job(job_id, user.id, prompt, route, title)
    try:
        uploads = [
            *(("source", upload) for upload in files or []),
            *(("reference", upload) for upload in references or []),
        ]
        if len(uploads) > 20:
            raise ValueError("a task can contain at most 20 files")
        for role, upload in uploads:
            stored_file = await request.app.state.storage.save_upload(
                job_id,
                upload,
                role,
            )
            await repository.add_asset(job_id, stored_file)
        await request.app.state.queue.enqueue(job_id)
    except ValueError as exc:
        await repository.set_status(
            job_id,
            JobStatus.FAILED,
            0,
            "Source upload rejected",
            error={"code": "invalid_upload", "message": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await repository.set_status(
            job_id,
            JobStatus.FAILED,
            0,
            "Task could not be queued",
            error={"code": "queue_error", "message": str(exc)},
        )
        raise HTTPException(
            status_code=503, detail="task queue is unavailable"
        ) from exc
    return job


@app.get(
    "/v1/jobs",
    response_model=list[JobRead],
)
async def list_jobs(
    request: Request,
    user: CurrentUser,
    limit: int = 50,
) -> list[dict]:
    return await _repository(request).list_jobs_for_user(
        user.id,
        limit,
        include_unowned=user.is_admin,
    )


@app.get(
    "/v1/jobs/{job_id}",
    response_model=JobRead,
)
async def get_job(request: Request, job_id: UUID, user: CurrentUser) -> dict:
    return await _require_job(request, job_id, user)


@app.get(
    "/v1/jobs/{job_id}/messages",
    response_model=list[JobMessageRead],
)
async def list_messages(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
) -> list[dict]:
    await _require_job(request, job_id, user)
    return await _repository(request).list_messages(job_id)


@app.get(
    "/v1/jobs/{job_id}/events",
)
async def stream_events(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
    after: int = 0,
) -> StreamingResponse:
    await _require_job(request, job_id, user)

    async def event_stream() -> AsyncIterator[str]:
        last_event_id = max(after, 0)
        keepalive_elapsed = 0.0
        while not await request.is_disconnected():
            events = await _repository(request).list_events(job_id, last_event_id)
            for event in events:
                last_event_id = event["id"]
                payload = json.dumps(event, ensure_ascii=False, default=str)
                yield f"id: {last_event_id}\nevent: job_event\ndata: {payload}\n\n"
            job = await _repository(request).get_job(job_id)
            if job is None or JobStatus(job["status"]) in TERMINAL_STATUSES:
                break
            await asyncio.sleep(request.app.state.settings.sse_poll_seconds)
            keepalive_elapsed += request.app.state.settings.sse_poll_seconds
            if keepalive_elapsed >= 15:
                yield ": keep-alive\n\n"
                keepalive_elapsed = 0

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get(
    "/v1/jobs/{job_id}/confirmation",
    response_model=ConfirmationRead,
)
async def get_confirmation(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
) -> dict:
    await _require_job(request, job_id, user)
    confirmation = await _repository(request).get_confirmation(job_id)
    if confirmation is None:
        raise HTTPException(status_code=404, detail="confirmation is not ready")
    return confirmation


@app.post(
    "/v1/jobs/{job_id}/confirmation",
    response_model=ConfirmationRead,
)
async def submit_confirmation(
    request: Request,
    job_id: UUID,
    submission: ConfirmationSubmit,
    user: CurrentUser,
) -> dict:
    job = await _require_job(request, job_id, user)
    if JobStatus(job["status"]) is not JobStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="job is not awaiting confirmation")
    confirmation = await _repository(request).submit_confirmation(
        job_id,
        submission.approved,
        submission.message.strip()
        or ("确认方案" if submission.approved else "请修改方案"),
    )
    if confirmation is None:
        raise HTTPException(
            status_code=409, detail="confirmation was already submitted"
        )
    await _repository(request).set_status(
        job_id, JobStatus.PLANNING, 30, "Response received"
    )
    await request.app.state.queue.enqueue(job_id)
    return confirmation


@app.post(
    "/v1/jobs/{job_id}/assets",
    response_model=list[AssetRead],
)
async def upload_assets(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
    files: Annotated[list[UploadFile] | None, File()] = None,
    references: Annotated[list[UploadFile] | None, File()] = None,
) -> list[dict]:
    job = await _require_job(request, job_id, user)
    allowed = {JobStatus.AWAITING_ASSET, JobStatus.SUCCEEDED, JobStatus.FAILED}
    if JobStatus(job["status"]) not in allowed:
        raise HTTPException(
            status_code=409, detail="job cannot accept assets in its current state"
        )
    uploads = [
        *(("source", upload) for upload in files or []),
        *(("reference", upload) for upload in references or []),
    ]
    if not uploads:
        raise HTTPException(status_code=400, detail="at least one file is required")
    if len(uploads) > 20:
        raise HTTPException(
            status_code=400, detail="at most 20 files can be uploaded at once"
        )
    records = []
    for role, upload in uploads:
        try:
            stored_file = await request.app.state.storage.save_upload(
                job_id,
                upload,
                role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record = await _repository(request).add_asset(job_id, stored_file)
        records.append(_asset_read(request.app.state.storage, record))
    return records


@app.post(
    "/v1/jobs/{job_id}/resume",
    response_model=MessageRead,
)
async def resume_job(
    request: Request,
    job_id: UUID,
    submission: JobMessageSubmit,
    user: CurrentUser,
) -> MessageRead:
    job = await _require_job(request, job_id, user)
    allowed = {JobStatus.AWAITING_ASSET, JobStatus.SUCCEEDED, JobStatus.FAILED}
    if JobStatus(job["status"]) not in allowed:
        raise HTTPException(
            status_code=409, detail="job cannot be resumed from its current state"
        )
    if job["runner_session_id"]:
        confirmation = await _repository(request).prepare_resume(
            job_id, submission.message
        )
        if confirmation is None:
            raise HTTPException(
                status_code=409, detail="job has no previous confirmation to resume"
            )
        await _repository(request).set_status(
            job_id, JobStatus.PLANNING, 30, "Revision queued"
        )
    else:
        await _repository(request).prepare_restart(job_id, submission.message)
        await _repository(request).set_status(
            job_id, JobStatus.QUEUED, 0, "Task queued again"
        )
    await request.app.state.queue.enqueue(job_id)
    return MessageRead(message="job queued")


@app.post(
    "/v1/jobs/{job_id}/cancel",
    response_model=MessageRead,
)
async def cancel_job(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
) -> MessageRead:
    job = await _require_job(request, job_id, user)
    cancelled = await _repository(request).request_cancel(job_id)
    if cancelled is None:
        raise HTTPException(status_code=409, detail="job is already complete")
    waiting_statuses = {
        JobStatus.QUEUED,
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.AWAITING_ASSET,
    }
    if JobStatus(job["status"]) in waiting_statuses:
        await _repository(request).set_status(
            job_id,
            JobStatus.CANCELLED,
            job["progress"],
            "Task cancelled",
        )
    return MessageRead(message="cancellation requested")


@app.get(
    "/v1/jobs/{job_id}/artifacts",
    response_model=list[ArtifactRead],
)
async def list_artifacts(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
) -> list[dict]:
    await _require_job(request, job_id, user)
    repository = _repository(request)
    existing = await repository.list_artifacts(job_id)
    live_previews = request.app.state.storage.discover_live_previews(job_id)
    live_paths = {preview.relative_path for preview in live_previews}
    records = _select_artifacts(existing, live_paths)
    for preview in live_previews:
        path = request.app.state.storage.resolve_job_file(job_id, preview.relative_path)
        records.append(
            {
                "id": preview.id,
                "job_id": job_id,
                "kind": "preview",
                "filename": preview.filename,
                "storage_path": preview.relative_path,
                "size_bytes": preview.size_bytes,
                "sha256": preview.sha256,
                "media_type": preview.media_type,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC),
            }
        )

    return records


@app.get(
    "/v1/jobs/{job_id}/artifacts/{artifact_id}/download",
)
async def download_artifact(
    request: Request,
    job_id: UUID,
    artifact_id: UUID,
    user: CurrentUser,
) -> FileResponse:
    await _require_job(request, job_id, user)
    artifact = await _repository(request).get_artifact(job_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        path = request.app.state.storage.resolve_job_file(
            job_id, artifact["storage_path"]
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="artifact file is missing") from exc
    return FileResponse(
        path, media_type=artifact["media_type"], filename=artifact["filename"]
    )


@app.get(
    "/v1/jobs/{job_id}/artifacts/{artifact_id}/view",
)
async def view_artifact(
    request: Request,
    job_id: UUID,
    artifact_id: UUID,
    user: CurrentUser,
) -> FileResponse:
    await _require_job(request, job_id, user)
    live_preview = next(
        (
            preview
            for preview in request.app.state.storage.discover_live_previews(job_id)
            if preview.id == artifact_id
        ),
        None,
    )
    if live_preview is not None:
        path = request.app.state.storage.resolve_job_file(
            job_id, live_preview.relative_path
        )
        return FileResponse(
            path,
            media_type=live_preview.media_type,
            filename=live_preview.filename,
            content_disposition_type="inline",
        )
    artifact = await _repository(request).get_artifact(job_id, artifact_id)
    if artifact is None or artifact["kind"] != "preview":
        raise HTTPException(status_code=404, detail="preview not found")
    try:
        path = request.app.state.storage.resolve_job_file(
            job_id, artifact["storage_path"]
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="preview file is missing") from exc
    return FileResponse(
        path,
        media_type=artifact["media_type"],
        filename=artifact["filename"],
        content_disposition_type="inline",
    )
