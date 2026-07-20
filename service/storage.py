"""Isolated file storage for uploaded sources and generated artifacts."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from fastapi import UploadFile


ALLOWED_SOURCE_SUFFIXES = {
    ".bmp",
    ".csv",
    ".docx",
    ".emf",
    ".epub",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".markdown",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".svg",
    ".tif",
    ".tiff",
    ".tsv",
    ".txt",
    ".webp",
    ".wmf",
    ".xlsm",
    ".xlsx",
}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
ASSET_ROLES = {"source", "reference"}


@dataclass
class StoredFile:
    """Metadata produced while streaming a file to local storage."""

    id: UUID
    filename: str
    relative_path: str
    size_bytes: int
    sha256: str
    media_type: str | None


@dataclass(frozen=True)
class WorkspaceProgress:
    """Observable task progress derived from files already written to disk."""

    page_count: int
    page_output_updated: bool
    quality_report_ready: bool
    presentation_ready: bool
    image_generation_state: str | None
    image_generation_updated: bool
    image_generation_count: int


class JobStorage:
    """Keep every task inside one UUID-addressed directory."""

    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        self.root = root.resolve()
        self.max_upload_bytes = max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: UUID) -> Path:
        path = (self.root / str(job_id)).resolve()
        self._require_child(path, self.root)
        return path

    def prepare_job(self, job_id: UUID) -> Path:
        job_dir = self.job_dir(job_id)
        for name in ("inbox", "workspace", "control", "artifacts"):
            (job_dir / name).mkdir(parents=True, exist_ok=True)
        return job_dir

    async def save_upload(
        self,
        job_id: UUID,
        upload: UploadFile,
        role: str = "source",
    ) -> StoredFile:
        if role not in ASSET_ROLES:
            raise ValueError(f"unsupported asset role: {role}")
        original_name = Path(upload.filename or "source").name
        safe_name = _SAFE_FILENAME_RE.sub("_", original_name).strip("._") or "source"
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_SOURCE_SUFFIXES:
            raise ValueError(f"unsupported source file type: {suffix or 'none'}")

        file_id = uuid4()
        stored_name = f"{file_id}_{safe_name}"
        destination_dir = self.prepare_job(job_id) / "inbox" / role
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / stored_name
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with destination.open("xb") as output_file:
                while chunk := await upload.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > self.max_upload_bytes:
                        raise ValueError(
                            "uploaded file exceeds the configured size limit"
                        )
                    digest.update(chunk)
                    output_file.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        relative_path = destination.relative_to(self.job_dir(job_id)).as_posix()
        return StoredFile(
            id=file_id,
            filename=safe_name,
            relative_path=relative_path,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
            media_type=upload.content_type,
        )

    def resolve_job_file(self, job_id: UUID, relative_path: str) -> Path:
        job_dir = self.job_dir(job_id)
        path = (job_dir / relative_path).resolve()
        self._require_child(path, job_dir)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def describe_existing(self, job_id: UUID, path: Path) -> StoredFile:
        resolved_path = path.resolve()
        job_dir = self.job_dir(job_id)
        self._require_child(resolved_path, job_dir)
        if not resolved_path.is_file():
            raise FileNotFoundError(resolved_path)

        digest = hashlib.sha256()
        with resolved_path.open("rb") as input_file:
            while chunk := input_file.read(1024 * 1024):
                digest.update(chunk)
        return StoredFile(
            id=uuid4(),
            filename=resolved_path.name,
            relative_path=resolved_path.relative_to(job_dir).as_posix(),
            size_bytes=resolved_path.stat().st_size,
            sha256=digest.hexdigest(),
            media_type=mimetypes.guess_type(resolved_path.name)[0],
        )

    def discover_artifacts(self, job_id: UUID) -> list[StoredFile]:
        workspace = self.job_dir(job_id) / "workspace"
        candidates: list[Path] = []
        for suffix in ("pptx", "pdf"):
            matches = list(workspace.glob(f"**/exports/*.{suffix}"))
            if matches:
                candidates.append(max(matches, key=lambda path: path.stat().st_mtime))
        return [
            self.describe_existing(job_id, path) for path in sorted(set(candidates))
        ]

    def inspect_workspace(
        self,
        job_id: UUID,
        changed_after: float = 0,
    ) -> WorkspaceProgress:
        workspace = self.job_dir(job_id) / "workspace"
        pages = {
            path
            for path in workspace.glob("**/svg_output/*.svg")
            if "backup" not in path.relative_to(workspace).parts
        }
        page_output_updated = any(
            path.stat().st_mtime >= changed_after for path in pages
        )
        quality_report_ready = any(
            path.stat().st_mtime >= changed_after
            for path in workspace.glob("**/exports/svg_quality_report.json")
        )
        presentation_ready = any(
            path.stat().st_mtime >= changed_after
            for path in workspace.glob("**/exports/*.pptx")
        )
        image_generation_state: str | None = None
        image_generation_count = 0
        image_audit_path = self.job_dir(job_id) / "control" / "image_generation.json"
        image_generation_updated = (
            image_audit_path.is_file()
            and image_audit_path.stat().st_mtime >= changed_after
        )
        if image_generation_updated:
            try:
                image_audit = json.loads(image_audit_path.read_text(encoding="utf-8"))
                image_generation_state = str(image_audit.get("state", "")) or None
                image_generation_count = max(
                    0,
                    int(image_audit.get("item_count", 0)),
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                image_generation_state = None
        return WorkspaceProgress(
            page_count=len(pages),
            page_output_updated=page_output_updated,
            quality_report_ready=quality_report_ready,
            presentation_ready=presentation_ready,
            image_generation_state=image_generation_state,
            image_generation_updated=image_generation_updated,
            image_generation_count=image_generation_count,
        )

    def discover_live_previews(self, job_id: UUID) -> list[StoredFile]:
        workspace = self.job_dir(job_id) / "workspace"
        candidates = sorted(
            {
                path
                for path in workspace.glob("**/svg_output/*.svg")
                if "backup" not in path.relative_to(workspace).parts
            }
        )
        previews = [self.describe_existing(job_id, path) for path in candidates]
        for preview in previews:
            preview.id = uuid5(job_id, preview.relative_path)
        return previews

    @staticmethod
    def asset_role(relative_path: str) -> str:
        parts = Path(relative_path).parts
        if len(parts) >= 2 and parts[0] == "inbox" and parts[1] in ASSET_ROLES:
            return parts[1]
        return "source"

    @staticmethod
    def _require_child(path: Path, parent: Path) -> None:
        try:
            path.relative_to(parent)
        except ValueError as exc:
            raise ValueError("path escapes the task directory") from exc
