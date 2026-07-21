"""Isolated file storage for uploaded sources and generated artifacts."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
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
_PAGE_NUMBER_PATTERNS = (
    re.compile(r"第\s*(\d+)\s*(?:页|張|张(?:\s*(?:PPT|幻灯片))?)", re.IGNORECASE),
    re.compile(
        r"第\s*([零〇一二两三四五六七八九十百千]+)\s*"
        r"(?:页|張|张(?:\s*(?:PPT|幻灯片))?)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:slide|page)\s*(?:#|no\.?\s*)?(\d+)", re.IGNORECASE),
)
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}


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


@dataclass(frozen=True)
class RevisionScope:
    """Original SVG state for one strictly scoped page revision."""

    target_page: int
    target_svg: str
    instruction: str
    page_order: tuple[str, ...]
    svg_hashes: dict[str, str]
    protected_files: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "target_page": self.target_page,
            "target_svg": self.target_svg,
            "instruction": self.instruction,
            "page_order": list(self.page_order),
            "svg_hashes": self.svg_hashes,
            "protected_files": list(self.protected_files),
        }


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

    def prepare_revision_scope(
        self,
        job_id: UUID,
        instruction: str,
        protected_paths: list[str] | None = None,
    ) -> RevisionScope | None:
        """Snapshot SVG hashes when an instruction names exactly one page."""
        scope_path = self.prepare_job(job_id) / "control" / "revision_scope.json"
        target_page = _extract_single_page_number(instruction)
        if target_page is None:
            scope_path.unlink(missing_ok=True)
            return None

        pages = self._svg_pages(job_id)
        if not pages:
            raise ValueError("当前任务还没有可修改的 PPT 页面")
        if target_page > len(pages):
            raise ValueError(
                f"修改指令指定第 {target_page} 页，但当前 PPT 只有 {len(pages)} 页"
            )

        page_order = tuple(
            path.relative_to(self.job_dir(job_id)).as_posix() for path in pages
        )
        protected_files = set(page_order)
        for relative_path in protected_paths or []:
            try:
                self.resolve_job_file(job_id, relative_path)
            except (FileNotFoundError, ValueError):
                continue
            protected_files.add(relative_path)

        baseline_dir = self.prepare_job(job_id) / "control" / "revision_baseline"
        if baseline_dir.exists():
            shutil.rmtree(baseline_dir)
        for relative_path in sorted(protected_files):
            source = self.resolve_job_file(job_id, relative_path)
            destination = baseline_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        scope = RevisionScope(
            target_page=target_page,
            target_svg=page_order[target_page - 1],
            instruction=instruction,
            page_order=page_order,
            svg_hashes={
                relative_path: self._sha256(self.job_dir(job_id) / relative_path)
                for relative_path in page_order
            },
            protected_files=tuple(sorted(protected_files)),
        )
        scope_path.write_text(
            json.dumps(scope.as_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return scope

    def load_revision_scope(self, job_id: UUID) -> RevisionScope | None:
        """Load a previous revision snapshot after an interrupted worker run."""
        scope_path = self.prepare_job(job_id) / "control" / "revision_scope.json"
        if not scope_path.is_file():
            return None
        try:
            data = json.loads(scope_path.read_text(encoding="utf-8"))
            page_order = tuple(
                _require_relative_path(str(path)) for path in data["page_order"]
            )
            svg_hashes = {
                _require_relative_path(str(path)): str(digest)
                for path, digest in data["svg_hashes"].items()
            }
            return RevisionScope(
                target_page=int(data["target_page"]),
                target_svg=_require_relative_path(str(data["target_svg"])),
                instruction=str(data["instruction"]),
                page_order=page_order,
                svg_hashes=svg_hashes,
                protected_files=tuple(
                    _require_relative_path(str(path))
                    for path in data.get("protected_files", data["page_order"])
                ),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def revision_scope_violations(
        self,
        job_id: UUID,
        scope: RevisionScope,
    ) -> list[str]:
        """Report page set, order, or non-target SVG changes."""
        page_order = tuple(
            path.relative_to(self.job_dir(job_id)).as_posix()
            for path in self._svg_pages(job_id)
        )
        violations: list[str] = []
        if page_order != scope.page_order:
            violations.append("页面数量、文件名或顺序发生变化")

        for relative_path, expected_hash in scope.svg_hashes.items():
            if relative_path == scope.target_svg:
                continue
            path = self.job_dir(job_id) / relative_path
            if not path.is_file() or self._sha256(path) != expected_hash:
                violations.append(f"非目标页面被修改：{relative_path}")
        return violations

    def restore_revision_scope(self, job_id: UUID, scope: RevisionScope) -> None:
        """Restore original pages and previously published files after rejection."""
        job_dir = self.job_dir(job_id)
        baseline_dir = job_dir / "control" / "revision_baseline"
        original_pages = set(scope.page_order)
        for page in self._svg_pages(job_id):
            relative_path = page.relative_to(job_dir).as_posix()
            if relative_path not in original_pages:
                page.unlink()

        for relative_path in scope.protected_files:
            source = baseline_dir / relative_path
            self._require_child(source.resolve(), baseline_dir.resolve())
            if not source.is_file():
                continue
            destination = job_dir / relative_path
            self._require_child(destination.resolve(), job_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    @staticmethod
    def asset_role(relative_path: str) -> str:
        parts = Path(relative_path).parts
        if len(parts) >= 2 and parts[0] == "inbox" and parts[1] in ASSET_ROLES:
            return parts[1]
        return "source"

    def _svg_pages(self, job_id: UUID) -> list[Path]:
        workspace = self.job_dir(job_id) / "workspace"
        return sorted(
            {
                path
                for path in workspace.glob("**/svg_output/*.svg")
                if "backup" not in path.relative_to(workspace).parts
            },
            key=lambda path: path.relative_to(workspace).as_posix(),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as input_file:
            while chunk := input_file.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _require_child(path: Path, parent: Path) -> None:
        try:
            path.relative_to(parent)
        except ValueError as exc:
            raise ValueError("path escapes the task directory") from exc


def _extract_single_page_number(instruction: str) -> int | None:
    page_numbers: set[int] = set()
    for index, pattern in enumerate(_PAGE_NUMBER_PATTERNS):
        for match in pattern.finditer(instruction):
            value = (
                int(match.group(1))
                if index != 1
                else _parse_chinese_number(match.group(1))
            )
            if value > 0:
                page_numbers.add(value)
    return next(iter(page_numbers)) if len(page_numbers) == 1 else None


def _parse_chinese_number(value: str) -> int:
    if all(character in _CHINESE_DIGITS for character in value):
        return int("".join(str(_CHINESE_DIGITS[character]) for character in value))

    total = 0
    digit = 0
    for character in value:
        if character in _CHINESE_DIGITS:
            digit = _CHINESE_DIGITS[character]
            continue
        unit = _CHINESE_UNITS[character]
        total += (digit or 1) * unit
        digit = 0
    return total + digit


def _require_relative_path(value: str) -> str:
    """Reject absolute or parent-traversing paths in a revision manifest."""
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("revision scope contains an unsafe relative path")
    return path.as_posix()
