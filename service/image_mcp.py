"""Restricted MCP bridge for manifest-driven PPT image generation."""

from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from PIL import Image


_MAX_ITEMS = 20
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_PROMPT_LENGTH = 12_000
_IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png", ".webp"}
_ASPECT_RATIOS = {
    "1:1",
    "16:9",
    "9:16",
    "3:2",
    "2:3",
    "4:3",
    "3:4",
    "4:5",
    "5:4",
    "21:9",
}
_IMAGE_SIZES = {"512px", "1K", "2K", "4K"}
_ALLOWED_STATUSES = {"Pending", "Generated", "Failed", "Needs-Manual"}

mcp = FastMCP("PPT Master Images")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Image generation is not configured: {name} is missing")
    return value


def _job_dir() -> Path:
    path = Path(_required_env("PPT_IMAGE_JOB_DIR")).resolve()
    if not path.is_dir():
        raise RuntimeError("The configured image task directory does not exist")
    return path


def _manifest_path(value: str) -> Path:
    job_dir = _job_dir()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = job_dir / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(job_dir)
    except ValueError as exc:
        raise ValueError(
            "The image manifest must stay inside the current task"
        ) from exc
    if candidate.name != "image_prompts.json" or candidate.parent.name != "images":
        raise ValueError("The manifest must be an images/image_prompts.json file")
    if not candidate.is_file():
        raise FileNotFoundError(f"Image manifest not found: {value}")
    if candidate.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("The image manifest is too large")
    return candidate


def _validate_manifest(path: Path, model: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("The image manifest contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("The image manifest must be a JSON object")
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= _MAX_ITEMS:
        raise ValueError(f"The image manifest must contain 1-{_MAX_ITEMS} items")

    filenames: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Image item {index} must be an object")
        filename = str(item.get("filename", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        aspect_ratio = str(item.get("aspect_ratio", "")).strip()
        status = str(item.get("status", "")).strip()
        image_size = str(item.get("image_size", "1K")).strip()
        item_model = str(item.get("model", model)).strip()
        if not filename or Path(filename).name != filename:
            raise ValueError(f"Image item {index} has an invalid filename")
        if Path(filename).suffix.lower() not in _IMAGE_SUFFIXES:
            raise ValueError(f"Image item {index} has an unsupported file extension")
        if filename in filenames:
            raise ValueError(f"Image item {index} duplicates filename {filename}")
        filenames.add(filename)
        if not prompt or len(prompt) > _MAX_PROMPT_LENGTH:
            raise ValueError(f"Image item {index} has an invalid prompt length")
        if aspect_ratio not in _ASPECT_RATIOS:
            raise ValueError(f"Image item {index} has an unsupported aspect ratio")
        if image_size not in _IMAGE_SIZES:
            raise ValueError(f"Image item {index} has an unsupported image size")
        if status not in _ALLOWED_STATUSES:
            raise ValueError(f"Image item {index} has an invalid status")
        if item_model != model:
            raise ValueError(f"Image item {index} cannot override the configured model")
    return payload


def _load_image_gen() -> Any:
    scripts_dir = (
        Path(__file__).resolve().parent.parent / "skills" / "ppt-master" / "scripts"
    )
    scripts_path = str(scripts_dir)
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    return import_module("image_gen")


def _read_image_audit() -> dict[str, Any]:
    """Read the current image-generation audit record."""
    path = _job_dir() / "control" / "image_generation.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _read_cumulative_total(payload: dict[str, Any], manifest_path: str) -> int:
    """Read and reconcile the running total after an interrupted generation call."""
    audit = _read_image_audit()
    try:
        total = max(0, int(audit.get("cumulative_total", 0)))
    except (ValueError, TypeError):
        total = 0
    audited_manifest = str(audit.get("manifest_path", "")).replace("\\", "/")
    if audit.get("state") != "running" or audited_manifest != manifest_path:
        return total
    raw_pending_files = audit.get("pending_files", [])
    pending_files = (
        {str(filename) for filename in raw_pending_files if filename}
        if isinstance(raw_pending_files, list)
        else set()
    )
    generated_files = {
        str(item.get("filename", ""))
        for item in payload["items"]
        if item.get("status") == "Generated"
    }
    return total + len(pending_files & generated_files)


def _write_audit(state: str, **details: Any) -> None:
    control_dir = _job_dir() / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "updated_at": datetime.now(UTC).isoformat(),
        **details,
    }
    path = control_dir / "image_generation.json"
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _generate_image_manifest(manifest_path: str) -> dict[str, Any]:
    api_key = _required_env("PPT_IMAGE_API_KEY")
    base_url = _required_env("PPT_IMAGE_BASE_URL").rstrip("/")
    model = _required_env("PPT_IMAGE_MODEL")
    image_size = _required_env("PPT_IMAGE_SIZE")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise RuntimeError("PPT_IMAGE_BASE_URL must be an HTTPS URL")

    manifest = _manifest_path(manifest_path)
    payload = _validate_manifest(manifest, model)
    relative_manifest = manifest.relative_to(_job_dir()).as_posix()
    prior_total = _read_cumulative_total(payload, relative_manifest)
    initial_statuses = [str(item["status"]) for item in payload["items"]]
    pending_files = [
        str(item["filename"])
        for item in payload["items"]
        if item["status"] in {"Pending", "Failed"}
    ]

    def generated_this_call() -> int:
        return sum(
            initial_status in {"Pending", "Failed"}
            and str(item.get("status", "")) == "Generated"
            for initial_status, item in zip(initial_statuses, payload["items"])
        )

    audit_details = {
        "manifest_path": relative_manifest,
        "model": model,
        "item_count": len(payload["items"]),
        "pending_files": pending_files,
        "requested_image_size": image_size,
        # Preserve the running total across running/failed writes (see _write_audit).
        "cumulative_total": prior_total,
    }
    _write_audit("running", **audit_details)
    os.environ.update(
        {
            "IMAGE_BACKEND": "openai",
            "IMAGE_CONCURRENCY": "2",
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_MODEL": model,
            "OPENAI_RESPONSE_FORMAT": "b64_json",
            "OPENAI_SIZE_OVERRIDE": image_size,
        }
    )
    try:
        # MCP stdio reserves stdout for JSON-RPC; provider progress belongs on stderr.
        with redirect_stdout(sys.stderr):
            image_gen = _load_image_gen()
            backend, _ = image_gen._load_backend("openai")
            _, failed, _ = image_gen._run_manifest(
                payload,
                str(manifest),
                backend,
                initial_concurrency=2,
                image_size="1K",
                output_dir=str(manifest.parent),
                model=model,
            )
            image_gen.render_manifest_md_to_file(str(manifest), payload)
        if failed:
            raise RuntimeError(f"Image generation failed for {failed} manifest item(s)")
    except Exception as exc:
        failed_details = {
            **audit_details,
            "cumulative_total": prior_total + generated_this_call(),
        }
        _write_audit("failed", error=str(exc)[:500], **failed_details)
        raise

    generated_files = []
    generated_dimensions: dict[str, str] = {}
    for item in payload["items"]:
        candidate = manifest.parent / Path(item["filename"]).name
        if candidate.is_file():
            relative_path = str(candidate.relative_to(_job_dir()))
            generated_files.append(relative_path)
            with Image.open(candidate) as image:
                generated_dimensions[relative_path] = f"{image.width}x{image.height}"
    result = {
        "manifest_path": str(manifest.relative_to(_job_dir())),
        "generated_files": generated_files,
        "generated_dimensions": generated_dimensions,
        "message": f"Generated {len(generated_files)} image(s) with {model}",
        "requested_image_size": image_size,
    }
    succeeded_details = {
        **audit_details,
        # Monotonic running total of actually generated images, for metering.
        "cumulative_total": prior_total + generated_this_call(),
    }
    _write_audit(
        "succeeded",
        generated_files=generated_files,
        generated_dimensions=generated_dimensions,
        **succeeded_details,
    )
    return result


@mcp.tool()
def generate_image_manifest(manifest_path: str) -> dict[str, Any]:
    """Generate every pending image in the current task's image_prompts.json manifest."""
    return _generate_image_manifest(manifest_path)


if __name__ == "__main__":
    mcp.run()
