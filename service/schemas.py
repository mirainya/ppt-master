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
