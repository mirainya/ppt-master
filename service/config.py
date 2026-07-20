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


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name, str(default)).strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass
class Settings:
    """Runtime settings loaded from environment variables."""

    database_url: str
    redis_url: str
    session_cookie_secure: bool
    session_days: int
    runtime_root: Path
    queue_name: str
    job_lease_seconds: int
    job_heartbeat_seconds: int
    max_upload_bytes: int
    sse_poll_seconds: float
    runner_model: str
    runner_timeout_seconds: int
    image_api_key: str
    image_base_url: str
    image_model: str
    image_size: str
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
            session_days=_positive_int("PPT_SESSION_DAYS", 30),
            runtime_root=Path(
                os.environ.get("PPT_RUNTIME_ROOT", repo_root / "runtime" / "jobs")
            ).resolve(),
            queue_name=os.environ.get("PPT_QUEUE_NAME", "ppt-master:jobs"),
            job_lease_seconds=_positive_int("PPT_JOB_LEASE_SECONDS", 30),
            job_heartbeat_seconds=_positive_int("PPT_JOB_HEARTBEAT_SECONDS", 5),
            max_upload_bytes=_positive_int("PPT_MAX_UPLOAD_MB", 100) * 1024 * 1024,
            sse_poll_seconds=poll_milliseconds / 1000,
            runner_model=os.environ.get("PPT_RUNNER_MODEL", ""),
            runner_timeout_seconds=_positive_int("PPT_RUNNER_TIMEOUT_SECONDS", 14_400),
            image_api_key=os.environ.get("PPT_IMAGE_API_KEY", "").strip(),
            image_base_url=os.environ.get("PPT_IMAGE_BASE_URL", "").strip(),
            image_model=os.environ.get("PPT_IMAGE_MODEL", "").strip(),
            image_size=os.environ.get("PPT_IMAGE_SIZE", "2048x1536").strip(),
            repo_root=repo_root,
        )

    def validate(self) -> None:
        """Reject insecure service settings before accepting requests."""
        if self.job_heartbeat_seconds >= self.job_lease_seconds:
            raise RuntimeError(
                "PPT_JOB_HEARTBEAT_SECONDS must be less than PPT_JOB_LEASE_SECONDS"
            )
        image_values = (self.image_api_key, self.image_base_url, self.image_model)
        if any(image_values) and not all(image_values):
            raise RuntimeError(
                "PPT_IMAGE_API_KEY, PPT_IMAGE_BASE_URL, and PPT_IMAGE_MODEL "
                "must be configured together"
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
