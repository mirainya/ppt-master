"""Public request and response models for the PPT Master API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class JobRoute(StrEnum):
    """Supported top-level PPT Master routes."""

    GENERATE = "generate_pptx"
    CREATE_TEMPLATE = "create_template"
    FILL_NATIVE = "fill_native_pptx"
    ENHANCE_NATIVE = "enhance_native_pptx"


class JobStatus(StrEnum):
    """Persisted states used by the API and worker."""

    QUEUED = "queued"
    INTAKE = "intake"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PLANNING = "planning"
    ACQUIRING = "acquiring"
    AWAITING_ASSET = "awaiting_asset"
    EXECUTING = "executing"
    VALIDATING = "validating"
    EXPORTING = "exporting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssetRole(StrEnum):
    """How an uploaded file may influence generated content."""

    SOURCE = "source"
    REFERENCE = "reference"


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class JobRead(BaseModel):
    """Current task state returned to API clients."""

    id: UUID
    title: str | None
    prompt: str
    route: JobRoute
    status: JobStatus
    stage: str
    progress: int
    cancel_requested: bool
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class JobEventRead(BaseModel):
    """One durable task event."""

    id: int
    job_id: UUID
    event_type: str
    stage: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class JobMessageRead(BaseModel):
    """One user, assistant, or system turn in task order."""

    id: int
    job_id: UUID
    role: str
    content: str
    created_at: datetime


class ConfirmationRead(BaseModel):
    """Proposal and optional user decision for a task."""

    job_id: UUID
    proposal: dict[str, Any]
    response: dict[str, Any] | None
    status: str
    created_at: datetime
    updated_at: datetime


class ConfirmationSubmit(BaseModel):
    """User response to the blocking Strategist confirmation."""

    approved: bool
    message: str = Field(default="", max_length=10_000)


class JobMessageSubmit(BaseModel):
    """Message used to continue or revise an existing Agent session."""

    message: str = Field(min_length=1, max_length=10_000)


class AssetRead(BaseModel):
    """Uploaded source file metadata."""

    id: UUID
    job_id: UUID
    filename: str
    size_bytes: int
    sha256: str
    media_type: str | None
    role: AssetRole
    created_at: datetime


class ArtifactRead(BaseModel):
    """Generated output metadata."""

    id: UUID
    job_id: UUID
    kind: str
    filename: str
    size_bytes: int
    sha256: str
    media_type: str | None
    created_at: datetime


class MessageRead(BaseModel):
    """Simple API action result."""

    message: str


class LoginRequest(BaseModel):
    """Username and password submitted by the browser login form."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class UserRead(BaseModel):
    """Authenticated account details safe to return to clients."""

    id: UUID
    username: str
    is_admin: bool
    org_id: UUID | None = None


class AdminUserCreate(BaseModel):
    """Administrator request to create a local password account."""

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    is_admin: bool = False


class AdminUserStatusUpdate(BaseModel):
    """Administrator request to enable or disable a local account."""

    disabled: bool


class AdminUserPasswordUpdate(BaseModel):
    """Administrator request to replace a local account password."""

    password: str = Field(min_length=12, max_length=1024)


class AdminUserRead(BaseModel):
    """Local account details visible to administrators."""

    id: UUID
    username: str
    is_admin: bool
    disabled: bool
    active_api_key_count: int = 0
    created_at: datetime
    updated_at: datetime


class OrgTicketCreated(BaseModel):
    """One-time workbench login ticket issued to an organization backend."""

    ticket: str
    expires_in: int


class OrgTicketConsume(BaseModel):
    """One-time organization login ticket submitted by the workbench."""

    ticket: str = Field(min_length=32, max_length=200)


class ApiKeyCreate(BaseModel):
    """Label for a new third-party API credential."""

    name: str = Field(min_length=1, max_length=100)


class ApiKeyRead(BaseModel):
    """Non-secret API key metadata."""

    id: UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """New API key response containing the one-time plaintext key."""

    key: str


class OrgCreate(BaseModel):
    """Admin request to onboard an enterprise organization."""

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")


class OrgKeyCreate(BaseModel):
    """Admin request to issue an organization API key."""

    name: str = Field(min_length=1, max_length=100)


class CreditTopup(BaseModel):
    """Admin request to add prepaid credits to an organization."""

    amount: float = Field(gt=0, allow_inf_nan=False)


class PricingUpdate(BaseModel):
    """Admin request to update layer-1 pricing and per-job hold."""

    price_input_token: float = Field(ge=0, allow_inf_nan=False)
    price_output_token: float = Field(ge=0, allow_inf_nan=False)
    price_image: float = Field(ge=0, allow_inf_nan=False)
    hold_amount: float = Field(ge=0, allow_inf_nan=False)


class RuntimeConfigRead(BaseModel):
    """Administrator-safe provider configuration without plaintext API keys."""

    codex_base_url: str
    codex_api_key_configured: bool
    codex_model: str
    image_base_url: str
    image_api_key_configured: bool
    image_model: str
    image_size: str
    image_concurrency: int | None
    updated_at: datetime | None


class RuntimeConfigUpdate(BaseModel):
    """Provider configuration update; omitted API keys retain current secrets."""

    codex_base_url: str = Field(default="", max_length=2048)
    codex_api_key: str | None = Field(default=None, max_length=4096)
    clear_codex_api_key: bool = False
    codex_model: str = Field(default="", max_length=200)
    image_base_url: str = Field(default="", max_length=2048)
    image_api_key: str | None = Field(default=None, max_length=4096)
    clear_image_api_key: bool = False
    image_model: str = Field(default="", max_length=200)
    image_size: str = Field(default="2048x1536", max_length=32)
    image_concurrency: int | None = Field(default=None, ge=1, le=20)
