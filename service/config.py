"""Environment-backed configuration for the PPT Master API service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


def _positive_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _non_negative_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be zero or greater")
    return value


def _optional_positive_int(name: str) -> int | None:
    raw_value = os.environ.get(name, "").strip().lower()
    if raw_value in {"", "0", "auto"}:
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer or auto") from exc
    if not 1 <= value <= 20:
        raise ValueError(f"{name} must be between 1 and 20")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name, str(default)).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _samesite(name: str, default: str) -> str:
    raw_value = os.environ.get(name, default).strip().lower()
    if raw_value not in {"lax", "strict", "none"}:
        raise ValueError(f"{name} must be one of lax, strict, none")
    return raw_value


@dataclass
class Settings:
    """Runtime settings loaded from environment variables."""

    database_url: str
    redis_url: str
    session_cookie_secure: bool
    session_cookie_samesite: str
    session_days: int
    job_retention_days: int
    runtime_root: Path
    queue_name: str
    job_lease_seconds: int
    job_heartbeat_seconds: int
    max_upload_bytes: int
    sse_poll_seconds: float
    runner_model: str
    runner_api_key: str
    runner_base_url: str
    runner_timeout_seconds: int
    runtime_config_key: str
    image_api_key: str
    image_base_url: str
    image_model: str
    image_size: str
    image_concurrency: int | None
    webhook_timeout_seconds: int
    webhook_max_attempts: int
    webhook_batch_size: int
    repo_root: Path

    @classmethod
    def from_env(cls) -> "Settings":
        repo_root = Path(__file__).resolve().parent.parent
        load_dotenv(repo_root / ".env", override=False)
        poll_milliseconds = _positive_int("PPT_SSE_POLL_MS", 750)
        return cls(
            database_url=os.environ.get(
                "PPT_DATABASE_URL",
                "postgresql://ppt_master:ppt_master@127.0.0.1:5432/ppt_master",
            ),
            redis_url=os.environ.get("PPT_REDIS_URL", "redis://127.0.0.1:6379/0"),
            session_cookie_secure=_boolean("PPT_SESSION_COOKIE_SECURE", False),
            session_cookie_samesite=_samesite("PPT_SESSION_COOKIE_SAMESITE", "lax"),
            session_days=_positive_int("PPT_SESSION_DAYS", 30),
            job_retention_days=_non_negative_int("PPT_JOB_RETENTION_DAYS", 30),
            runtime_root=Path(
                os.environ.get("PPT_RUNTIME_ROOT", repo_root / "runtime" / "jobs")
            ).resolve(),
            queue_name=os.environ.get("PPT_QUEUE_NAME", "ppt-master:jobs"),
            job_lease_seconds=_positive_int("PPT_JOB_LEASE_SECONDS", 30),
            job_heartbeat_seconds=_positive_int("PPT_JOB_HEARTBEAT_SECONDS", 5),
            max_upload_bytes=_positive_int("PPT_MAX_UPLOAD_MB", 100) * 1024 * 1024,
            sse_poll_seconds=poll_milliseconds / 1000,
            runner_model=os.environ.get("PPT_RUNNER_MODEL", ""),
            runner_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            runner_base_url=os.environ.get("OPENAI_BASE_URL", "").strip(),
            runner_timeout_seconds=_positive_int("PPT_RUNNER_TIMEOUT_SECONDS", 14_400),
            runtime_config_key=os.environ.get("PPT_RUNTIME_CONFIG_KEY", "").strip(),
            image_api_key=os.environ.get("PPT_IMAGE_API_KEY", "").strip(),
            image_base_url=os.environ.get("PPT_IMAGE_BASE_URL", "").strip(),
            image_model=os.environ.get("PPT_IMAGE_MODEL", "").strip(),
            image_size=os.environ.get("PPT_IMAGE_SIZE", "2048x1536").strip(),
            image_concurrency=_optional_positive_int("PPT_IMAGE_CONCURRENCY"),
            webhook_timeout_seconds=_positive_int("PPT_WEBHOOK_TIMEOUT_SECONDS", 10),
            webhook_max_attempts=_positive_int("PPT_WEBHOOK_MAX_ATTEMPTS", 8),
            webhook_batch_size=_positive_int("PPT_WEBHOOK_BATCH_SIZE", 20),
            repo_root=repo_root,
        )

    def validate(self) -> None:
        """Reject insecure service settings before accepting requests."""
        if self.job_heartbeat_seconds >= self.job_lease_seconds:
            raise RuntimeError(
                "PPT_JOB_HEARTBEAT_SECONDS must be less than PPT_JOB_LEASE_SECONDS"
            )
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise RuntimeError(
                "PPT_SESSION_COOKIE_SECURE must be true when "
                "PPT_SESSION_COOKIE_SAMESITE=none (browsers reject insecure "
                "SameSite=None cookies)"
            )
        if self.image_api_key and not (self.image_base_url and self.image_model):
            raise RuntimeError(
                "PPT_IMAGE_BASE_URL and PPT_IMAGE_MODEL are required when "
                "PPT_IMAGE_API_KEY is set"
            )
        if self.image_api_key:
            parsed_models = [m.strip() for m in self.image_model.split(",") if m.strip()]
            if not parsed_models:
                raise RuntimeError(
                    "PPT_IMAGE_MODEL must list at least one model name"
                )
        if self.image_base_url:
            parsed = urlparse(self.image_base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise RuntimeError("PPT_IMAGE_BASE_URL must be an HTTPS URL")
        if self.image_generation_enabled:
            try:
                width_text, height_text = self.image_size.lower().split("x", 1)
                width, height = int(width_text), int(height_text)
            except ValueError as exc:
                raise RuntimeError("PPT_IMAGE_SIZE must use WIDTHxHEIGHT") from exc
            if width <= 0 or height <= 0 or width > 8192 or height > 8192:
                raise RuntimeError("PPT_IMAGE_SIZE is outside the supported range")

    @property
    def image_generation_enabled(self) -> bool:
        """Return whether the worker has a complete image provider configuration."""
        return bool(self.image_api_key and self.image_base_url and self.image_model)
