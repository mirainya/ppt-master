"""FastAPI application for remote PPT Master jobs."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, AsyncIterator
from uuid import UUID, uuid4

from asyncpg.exceptions import UniqueViolationError
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
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service.auth import (
    AuthenticatedUser,
    generate_api_key,
    generate_org_api_key,
    generate_session_token,
    hash_password,
    hash_token,
    is_org_api_key,
    normalize_username,
    password_needs_rehash,
    verify_missing_user,
    verify_password,
)
from service.auth_repository import AuthRepository
from service.auth_ticket import OrgTicketStore
from service.billing import BillingRepository, Pricing
from service.config import Settings
from service.database import Database
from service.queue import JobQueue
from service.repository import (
    JobRepository,
    OrganizationQuotaExceededError,
    OrganizationUnavailableError,
)
from service.schemas import (
    AdminJobRead,
    AdminUserCreate,
    AdminUserPasswordUpdate,
    AdminUserRead,
    AdminUserStatusUpdate,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    ArtifactRead,
    AssetRead,
    ConfirmationRead,
    ConfirmationSubmit,
    JobMessageSubmit,
    JobMessageRead,
    CreditTopup,
    JobRead,
    JobRoute,
    JobStatus,
    LoginRequest,
    MessageRead,
    OrgCreate,
    OrgKeyCreate,
    OrgTicketConsume,
    OrgTicketCreated,
    PricingUpdate,
    RuntimeConfigRead,
    RuntimeConfigUpdate,
    TERMINAL_STATUSES,
    UserRead,
)
from service.storage import JobStorage
from service.runtime_config import RuntimeConfig, RuntimeConfigRepository


bearer_scheme = HTTPBearer(auto_error=False)
SESSION_COOKIE = "ppt_master_session"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    settings.validate()
    database = Database(settings.database_url)
    queue = JobQueue(settings.redis_url, settings.queue_name)
    ticket_store = OrgTicketStore(settings.redis_url)
    storage = JobStorage(settings.runtime_root, settings.max_upload_bytes)
    await database.connect()
    await database.verify_schema()
    await queue.healthcheck()
    app.state.settings = settings
    app.state.database = database
    app.state.auth_repository = AuthRepository(database)
    app.state.repository = JobRepository(database)
    app.state.billing_repository = BillingRepository(database)
    app.state.runtime_config_repository = RuntimeConfigRepository(database, settings)
    app.state.ticket_store = ticket_store
    app.state.queue = queue
    app.state.storage = storage
    try:
        yield
    finally:
        await ticket_store.close()
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


_END_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,189}$")


def _resolve_end_user_id(request: Request) -> str | None:
    """Validate the enterprise-supplied X-End-User-Id header, or None when absent.

    Rejects the reserved service sentinel and malformed values so a tenant cannot
    collide with its own default service account or split one user across variants.
    """
    raw = request.headers.get("X-End-User-Id")
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value == AuthRepository.SERVICE_EXTERNAL_ID:
        raise HTTPException(status_code=400, detail="X-End-User-Id is reserved")
    if not _END_USER_ID_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail="invalid X-End-User-Id")
    return value


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    repository: AuthRepository = request.app.state.auth_repository
    if credentials is not None:
        token = credentials.credentials
        token_hash = hash_token(token)
        # Prefix is a routing hint only; fall back to personal keys on a miss so a
        # personal key that happens to start with the org prefix still works.
        if is_org_api_key(token):
            org_id = await repository.authenticate_org_api_key(token_hash)
            if org_id is not None:
                external_id = _resolve_end_user_id(request)
                return await repository.provision_end_user(org_id, external_id)
        user = await repository.authenticate_api_key(token_hash)
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


async def require_org_api_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    """Authenticate only an organization API key for server-to-server SSO issuance."""
    if credentials is None or not is_org_api_key(credentials.credentials):
        raise _authentication_error()
    repository: AuthRepository = request.app.state.auth_repository
    org_id = await repository.authenticate_org_api_key(
        hash_token(credentials.credentials)
    )
    if org_id is None:
        raise _authentication_error()
    return await repository.provision_end_user(org_id, _resolve_end_user_id(request))


async def require_browser_user(request: Request) -> AuthenticatedUser:
    session_token = request.cookies.get(SESSION_COOKIE, "")
    if not session_token:
        raise _authentication_error()
    repository: AuthRepository = request.app.state.auth_repository
    user = await repository.authenticate_session(hash_token(session_token))
    if user is None:
        raise _authentication_error()
    return user


async def require_personal_browser_user(request: Request) -> AuthenticatedUser:
    user = await require_browser_user(request)
    if user.org_id is not None:
        raise HTTPException(
            status_code=403,
            detail="organization users cannot manage personal API keys",
        )
    return user


async def require_admin_user(request: Request) -> AuthenticatedUser:
    user = await require_browser_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="administrator access required")
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(require_user)]
OrgApiUser = Annotated[AuthenticatedUser, Depends(require_org_api_user)]
BrowserUser = Annotated[AuthenticatedUser, Depends(require_browser_user)]
PersonalBrowserUser = Annotated[
    AuthenticatedUser, Depends(require_personal_browser_user)
]
AdminUser = Annotated[AuthenticatedUser, Depends(require_admin_user)]


def _repository(request: Request) -> JobRepository:
    return request.app.state.repository


async def _start_browser_session(
    request: Request,
    response: Response,
    user_id: UUID,
) -> None:
    """Create the standard workbench session and attach its HttpOnly cookie."""
    session_token = generate_session_token()
    await request.app.state.auth_repository.create_session(
        user_id,
        hash_token(session_token),
        request.app.state.settings.session_days,
    )
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=request.app.state.settings.session_days * 86_400,
        httponly=True,
        secure=request.app.state.settings.session_cookie_secure,
        samesite=request.app.state.settings.session_cookie_samesite,
        path="/",
    )


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


async def _require_job_readonly(
    request: Request,
    job_id: UUID,
    user: AuthenticatedUser,
) -> dict:
    """Fetch a job for read-only access.

    Admins may read any user's job (preview, download, messages); non-admins
    are limited to their own jobs. Mutating endpoints keep using _require_job.
    """
    if user.is_admin:
        job = await _repository(request).get_job(job_id)
    else:
        job = await _repository(request).get_job_for_user(
            job_id, user.id, include_unowned=False
        )
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


async def _reject_if_purged(request: Request, job_id: UUID) -> None:
    """Return 410 when a task's files were intentionally cleaned up."""
    job = await _repository(request).get_job(job_id)
    if job is not None and job.get("files_purged_at") is not None:
        raise HTTPException(status_code=410, detail="task files have been cleaned up")


async def _reserve_continuation_hold(request: Request, job: dict) -> None:
    """Reserve the next turn before a confirmation or revision is queued."""
    org_id = job.get("org_id")
    if org_id is None:
        return
    try:
        pricing = await request.app.state.billing_repository.get_pricing()
        held = await request.app.state.billing_repository.hold_credits(
            org_id,
            job["id"],
            pricing.hold_amount,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="billing is temporarily unavailable",
        ) from exc
    if not held:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="insufficient organization credit balance",
        )


def _select_artifacts(
    artifacts: list[dict],
    live_paths: set[str],
    live_names: set[str],
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
        if artifact["kind"] == "preview"
        and artifact["storage_path"] not in live_paths
        and artifact["filename"] not in live_names
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


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Open the interactive API documentation from the service root."""
    return RedirectResponse(url="/docs")


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


@app.post(
    "/v1/auth/org-tickets",
    response_model=OrgTicketCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_org_ticket(
    request: Request,
    user: OrgApiUser,
) -> dict[str, object]:
    """Issue a short-lived workbench login ticket to an organization backend."""
    if user.org_id is None:
        raise HTTPException(status_code=403, detail="organization credentials required")
    ticket, expires_in = await request.app.state.ticket_store.issue(
        user.id,
        user.org_id,
    )
    return {"ticket": ticket, "expires_in": expires_in}


@app.post("/v1/auth/org-tickets/consume", response_model=UserRead)
async def consume_org_ticket(
    request: Request,
    response: Response,
    submission: OrgTicketConsume,
) -> AuthenticatedUser:
    """Consume a one-time ticket and create the existing workbench session."""
    identity = await request.app.state.ticket_store.consume(submission.ticket)
    if identity is None:
        raise HTTPException(
            status_code=401, detail="login ticket is invalid or expired"
        )
    user_id, org_id = identity
    user = await request.app.state.auth_repository.get_active_org_user(user_id, org_id)
    if user is None:
        raise HTTPException(
            status_code=401, detail="login ticket is invalid or expired"
        )
    await _start_browser_session(request, response, user.id)
    return user


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
    await _start_browser_session(request, response, account["id"])
    return {
        "id": account["id"],
        "username": account["username"],
        "is_admin": account["is_admin"],
        "org_id": account["org_id"],
    }


@app.post("/v1/auth/logout", response_model=MessageRead)
async def logout(request: Request, response: Response) -> MessageRead:
    session_token = request.cookies.get(SESSION_COOKIE, "")
    if session_token:
        await request.app.state.auth_repository.delete_session(
            hash_token(session_token)
        )
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=request.app.state.settings.session_cookie_secure,
        samesite=request.app.state.settings.session_cookie_samesite,
    )
    return MessageRead(message="signed out")


@app.get("/v1/auth/me", response_model=UserRead)
async def me(user: CurrentUser) -> AuthenticatedUser:
    return user


@app.get("/v1/auth/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(request: Request, user: PersonalBrowserUser) -> list[dict]:
    return await request.app.state.auth_repository.list_api_keys(user.id)


@app.post(
    "/v1/auth/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: Request,
    submission: ApiKeyCreate,
    user: PersonalBrowserUser,
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
    user: PersonalBrowserUser,
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
    try:
        job = await repository.create_job(
            job_id, user.id, prompt, route, title, org_id=user.org_id
        )
    except OrganizationUnavailableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    # Hold prepaid credits after the job row exists so the hold references the job and
    # can be released on any failure/cancel path. Reject with 402 if the balance is short.
    if user.org_id is not None:
        try:
            pricing = await request.app.state.billing_repository.get_pricing()
            held = await request.app.state.billing_repository.hold_credits(
                user.org_id, job_id, pricing.hold_amount
            )
        except Exception as exc:
            await request.app.state.billing_repository.release_hold(job_id)
            await repository.set_status(
                job_id,
                JobStatus.FAILED,
                0,
                "Billing setup failed",
                error={"code": "billing_unavailable", "message": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="billing is temporarily unavailable",
            ) from exc
        if not held:
            await repository.set_status(
                job_id,
                JobStatus.FAILED,
                0,
                "Insufficient organization credit balance",
                error={
                    "code": "insufficient_credit",
                    "message": "insufficient organization credit balance",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="insufficient organization credit balance",
            )
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
        await request.app.state.billing_repository.release_hold(job_id)
        await repository.set_status(
            job_id,
            JobStatus.FAILED,
            0,
            "Source upload rejected",
            error={"code": "invalid_upload", "message": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await request.app.state.billing_repository.release_hold(job_id)
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
    return await _require_job_readonly(request, job_id, user)


@app.get(
    "/v1/jobs/{job_id}/messages",
    response_model=list[JobMessageRead],
)
async def list_messages(
    request: Request,
    job_id: UUID,
    user: CurrentUser,
) -> list[dict]:
    await _require_job_readonly(request, job_id, user)
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
    await _require_job_readonly(request, job_id, user)

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
    await _require_job_readonly(request, job_id, user)
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
    await _reserve_continuation_hold(request, job)
    try:
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
    except HTTPException:
        await request.app.state.billing_repository.release_hold(job_id)
        raise
    except Exception as exc:
        await request.app.state.billing_repository.release_hold(job_id)
        await _repository(request).set_status(
            job_id,
            JobStatus.FAILED,
            job["progress"],
            "Task could not be queued",
            error={"code": "queue_error", "message": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="task queue is unavailable",
        ) from exc
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
    await _reserve_continuation_hold(request, job)
    try:
        if job["runner_session_id"]:
            confirmation = await _repository(request).prepare_resume(
                job_id, submission.message
            )
            if confirmation is None:
                raise HTTPException(
                    status_code=409,
                    detail="job has no previous confirmation to resume",
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
    except HTTPException:
        await request.app.state.billing_repository.release_hold(job_id)
        raise
    except Exception as exc:
        await request.app.state.billing_repository.release_hold(job_id)
        await _repository(request).set_status(
            job_id,
            JobStatus.FAILED,
            job["progress"],
            "Task could not be queued",
            error={"code": "queue_error", "message": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="task queue is unavailable",
        ) from exc
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
        # Refund any outstanding hold; no-op if a turn already settled it.
        await request.app.state.billing_repository.release_hold(job_id)
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
    await _require_job_readonly(request, job_id, user)
    repository = _repository(request)
    existing = await repository.list_artifacts(job_id)
    live_previews = request.app.state.storage.discover_live_previews(job_id)
    live_paths = {preview.relative_path for preview in live_previews}
    live_names = {preview.filename for preview in live_previews}
    records = _select_artifacts(existing, live_paths, live_names)
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
    await _require_job_readonly(request, job_id, user)
    await _reject_if_purged(request, job_id)
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
    await _require_job_readonly(request, job_id, user)
    await _reject_if_purged(request, job_id)
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


@app.get("/v1/jobs/{job_id}/usage")
async def job_usage(request: Request, job_id: UUID, user: CurrentUser) -> dict:
    """Layer-2 usage receipt for one job, for the enterprise to bill its end-user."""
    job = await _require_job_readonly(request, job_id, user)
    usage = await _repository(request).get_job_usage(job_id)
    end_user_id = await request.app.state.auth_repository.external_id_for_user(
        job["owner_id"]
    )
    is_final = JobStatus(job["status"]) in TERMINAL_STATUSES
    return {
        "job_id": job_id,
        "end_user_id": end_user_id,
        "status": "final" if is_final else "partial",
        "usage": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "images": usage["images"],
            "pages": usage["pages"],
            "jobs": 1,
        },
        "our_charge": {"credits": usage["our_charge"]},
    }


@app.get("/v1/orgs/usage")
async def org_usage(
    request: Request,
    user: CurrentUser,
    end_user_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Aggregate the caller's organization usage, grouped by enterprise end-user."""
    if user.org_id is None:
        raise HTTPException(status_code=403, detail="organization credentials required")
    rows = await _repository(request).aggregate_org_usage(
        user.org_id,
        external_id=end_user_id,
        since=since,
        until=until,
    )
    return {"org_id": user.org_id, "end_users": rows}


@app.get("/v1/admin/jobs", response_model=list[AdminJobRead])
async def admin_list_jobs(
    request: Request,
    admin: AdminUser,
    limit: int = 50,
) -> list[dict]:
    """List every task across all users for the admin console."""
    return await _repository(request).list_all_jobs(limit)


@app.post("/v1/admin/jobs/{job_id}/purge", response_model=AdminJobRead)
async def admin_purge_job(
    request: Request,
    job_id: UUID,
    admin: AdminUser,
) -> dict:
    """Delete one task's on-disk files while keeping its record and billing."""
    job = await _repository(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] not in {s.value for s in TERMINAL_STATUSES}:
        raise HTTPException(
            status_code=409,
            detail="task is still active; cancel it before purging files",
        )
    request.app.state.storage.purge_job_files(job_id)
    updated = await _repository(request).mark_job_purged(job_id)
    return updated if updated is not None else job


@app.get("/v1/admin/users", response_model=list[AdminUserRead])
async def admin_list_users(request: Request, admin: AdminUser) -> list[dict]:
    """List local password accounts and their active API key counts."""
    return await request.app.state.auth_repository.list_local_users()


@app.post(
    "/v1/admin/users",
    response_model=AdminUserRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_user(
    request: Request,
    submission: AdminUserCreate,
    admin: AdminUser,
) -> dict:
    """Create one local password account."""
    username = normalize_username(submission.username)
    if not username:
        raise HTTPException(status_code=400, detail="username cannot be blank")
    try:
        account = await request.app.state.auth_repository.create_user(
            username,
            hash_password(submission.password),
            is_admin=submission.is_admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc
    return {**account, "active_api_key_count": 0}


@app.patch("/v1/admin/users/{user_id}", response_model=AdminUserRead)
async def admin_update_user_status(
    request: Request,
    user_id: UUID,
    submission: AdminUserStatusUpdate,
    admin: AdminUser,
) -> dict:
    """Enable or disable one local account."""
    try:
        account = await request.app.state.auth_repository.set_local_user_disabled(
            user_id,
            submission.disabled,
            acting_user_id=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if account is None:
        raise HTTPException(status_code=404, detail="user not found")
    keys = await request.app.state.auth_repository.list_api_keys(user_id)
    return {
        **account,
        "active_api_key_count": sum(key["revoked_at"] is None for key in keys),
    }


@app.put("/v1/admin/users/{user_id}/password", response_model=MessageRead)
async def admin_reset_user_password(
    request: Request,
    user_id: UUID,
    submission: AdminUserPasswordUpdate,
    admin: AdminUser,
) -> MessageRead:
    """Replace a local account password and revoke its browser sessions."""
    try:
        password_hash = hash_password(submission.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = await request.app.state.auth_repository.reset_local_user_password(
        user_id,
        password_hash,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="user not found")
    return MessageRead(message="password reset")


@app.get(
    "/v1/admin/users/{user_id}/api-keys",
    response_model=list[ApiKeyRead],
)
async def admin_list_user_api_keys(
    request: Request,
    user_id: UUID,
    admin: AdminUser,
) -> list[dict]:
    if await request.app.state.auth_repository.get_local_user(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    return await request.app.state.auth_repository.list_api_keys(user_id)


@app.post(
    "/v1/admin/users/{user_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_user_api_key(
    request: Request,
    user_id: UUID,
    submission: ApiKeyCreate,
    admin: AdminUser,
) -> dict:
    """Issue a user-owned API key and return its plaintext exactly once."""
    if await request.app.state.auth_repository.get_local_user(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    key, prefix = generate_api_key()
    record = await request.app.state.auth_repository.create_api_key(
        user_id,
        submission.name,
        prefix,
        hash_token(key),
    )
    return {**record, "key": key}


@app.delete(
    "/v1/admin/users/{user_id}/api-keys/{key_id}",
    response_model=MessageRead,
)
async def admin_revoke_user_api_key(
    request: Request,
    user_id: UUID,
    key_id: UUID,
    admin: AdminUser,
) -> MessageRead:
    revoked = await request.app.state.auth_repository.revoke_api_key(user_id, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="user API key not found")
    return MessageRead(message="user API key revoked")


@app.get("/v1/admin/orgs")
async def admin_list_orgs(request: Request, admin: AdminUser) -> list[dict]:
    """List organizations for the admin billing console."""
    return await request.app.state.auth_repository.list_organizations()


@app.post("/v1/admin/orgs", status_code=status.HTTP_201_CREATED)
async def admin_create_org(
    request: Request, submission: OrgCreate, admin: AdminUser
) -> dict:
    """Onboard an enterprise organization plus its default service account."""
    try:
        org = await request.app.state.auth_repository.create_organization(
            submission.name, submission.slug
        )
    except UniqueViolationError as exc:
        raise HTTPException(
            status_code=409, detail="organization slug already exists"
        ) from exc
    return org


@app.post("/v1/admin/orgs/{org_id}/keys", status_code=status.HTTP_201_CREATED)
async def admin_create_org_key(
    request: Request, org_id: UUID, submission: OrgKeyCreate, admin: AdminUser
) -> dict:
    """Issue an organization API key; the plaintext is returned exactly once."""
    if await request.app.state.auth_repository.get_organization(org_id) is None:
        raise HTTPException(status_code=404, detail="organization not found")
    key, prefix = generate_org_api_key()
    record = await request.app.state.auth_repository.create_org_api_key(
        org_id, submission.name, prefix, hash_token(key)
    )
    return {**record, "key": key}


@app.get("/v1/admin/orgs/{org_id}/keys")
async def admin_list_org_keys(
    request: Request, org_id: UUID, admin: AdminUser
) -> list[dict]:
    return await request.app.state.auth_repository.list_org_api_keys(org_id)


@app.delete("/v1/admin/orgs/{org_id}/keys/{key_id}", response_model=MessageRead)
async def admin_revoke_org_key(
    request: Request, org_id: UUID, key_id: UUID, admin: AdminUser
) -> MessageRead:
    revoked = await request.app.state.auth_repository.revoke_org_api_key(org_id, key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="organization API key not found")
    return MessageRead(message="organization API key revoked")


@app.post("/v1/admin/orgs/{org_id}/credits")
async def admin_topup_org(
    request: Request, org_id: UUID, submission: CreditTopup, admin: AdminUser
) -> dict:
    """Add prepaid credits to an organization balance."""
    if await request.app.state.auth_repository.get_organization(org_id) is None:
        raise HTTPException(status_code=404, detail="organization not found")
    balance = await request.app.state.billing_repository.topup(
        org_id, submission.amount
    )
    return {"org_id": org_id, "credit_balance": balance}


@app.get("/v1/admin/orgs/{org_id}/usage")
async def admin_org_usage(
    request: Request,
    org_id: UUID,
    admin: AdminUser,
    end_user_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Per-end-user usage report for one organization."""
    if await request.app.state.auth_repository.get_organization(org_id) is None:
        raise HTTPException(status_code=404, detail="organization not found")
    rows = await _repository(request).aggregate_org_usage(
        org_id, external_id=end_user_id, since=since, until=until
    )
    return {"org_id": org_id, "end_users": rows}


@app.get("/v1/admin/billing-config")
async def admin_get_pricing(request: Request, admin: AdminUser) -> dict:
    pricing = await request.app.state.billing_repository.get_pricing()
    return {
        "price_input_token": pricing.price_input_token,
        "price_output_token": pricing.price_output_token,
        "price_image": pricing.price_image,
        "hold_amount": pricing.hold_amount,
    }


@app.put("/v1/admin/billing-config")
async def admin_update_pricing(
    request: Request, submission: PricingUpdate, admin: AdminUser
) -> dict:
    updated = await request.app.state.billing_repository.update_pricing(
        Pricing(
            price_input_token=submission.price_input_token,
            price_output_token=submission.price_output_token,
            price_image=submission.price_image,
            hold_amount=submission.hold_amount,
        )
    )
    return {
        "price_input_token": updated.price_input_token,
        "price_output_token": updated.price_output_token,
        "price_image": updated.price_image,
        "hold_amount": updated.hold_amount,
    }


def _runtime_config_read(config: RuntimeConfig) -> dict:
    return {
        "codex_base_url": config.codex_base_url,
        "codex_api_key_configured": bool(config.codex_api_key),
        "codex_model": config.codex_model,
        "image_base_url": config.image_base_url,
        "image_api_key_configured": bool(config.image_api_key),
        "image_model": config.image_model,
        "image_size": config.image_size,
        "image_concurrency": config.image_concurrency,
        "updated_at": config.updated_at,
    }


@app.get("/v1/admin/runtime-config", response_model=RuntimeConfigRead)
async def admin_get_runtime_config(
    request: Request, admin: AdminUser
) -> dict:
    config = await request.app.state.runtime_config_repository.get()
    return _runtime_config_read(config)


@app.put("/v1/admin/runtime-config", response_model=RuntimeConfigRead)
async def admin_update_runtime_config(
    request: Request,
    submission: RuntimeConfigUpdate,
    admin: AdminUser,
) -> dict:
    try:
        config = await request.app.state.runtime_config_repository.update(
            codex_base_url=submission.codex_base_url,
            codex_api_key=(
                submission.codex_api_key.strip() or None
                if submission.codex_api_key is not None
                else None
            ),
            clear_codex_api_key=submission.clear_codex_api_key,
            codex_model=submission.codex_model,
            image_base_url=submission.image_base_url,
            image_api_key=(
                submission.image_api_key.strip() or None
                if submission.image_api_key is not None
                else None
            ),
            clear_image_api_key=submission.clear_image_api_key,
            image_model=submission.image_model,
            image_size=submission.image_size,
            image_concurrency=submission.image_concurrency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _runtime_config_read(config)
