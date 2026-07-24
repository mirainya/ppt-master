"""Restricted MCP bridge for manifest-driven PPT image generation."""

from __future__ import annotations

import concurrent.futures  # Must import early, before service/queue.py shadows stdlib queue
import json
import os
import sys
import threading
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


def _model_list() -> list[str]:
    """Parse PPT_IMAGE_MODEL into an ordered fallback chain (first = primary)."""
    raw = _required_env("PPT_IMAGE_MODEL")
    models = [part.strip() for part in raw.split(",") if part.strip()]
    if not models:
        raise RuntimeError("Image generation is not configured: PPT_IMAGE_MODEL is empty")
    return models


def _run_with_fallback(
    payload: dict[str, Any],
    backend: Any,
    *,
    models: list[str],
    concurrency: int,
    output_dir: str,
) -> tuple[int, int, dict[str, str]]:
    """Try each model in order; any error on an item falls through to the next model.

    max_retries=0 means rate-limit/5xx/timeout all surface immediately so the
    outer model loop switches without waiting. Only items still Failed after the
    last model count as failures. Returns (ok, failed, {filename: winning_model}).
    """
    items = payload["items"]
    lock = threading.Lock()
    model_trace: dict[str, str] = {}

    def _one(idx: int, model: str):
        item = items[idx]
        try:
            backend.generate(
                prompt=item["prompt"],
                aspect_ratio=item["aspect_ratio"],
                image_size=item.get("image_size", "1K"),
                output_dir=output_dir,
                filename=Path(item["filename"]).stem,
                model=model,
                max_retries=0,
            )
            return idx, None
        except Exception as exc:  # noqa: BLE001 — backend raises arbitrary types
            return idx, exc

    for model in models:
        pending = [
            i for i, it in enumerate(items)
            if it["status"] in {"Pending", "Failed"}
        ]
        if not pending:
            break
        batch = max(1, min(concurrency, len(pending)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch) as ex:
            futures = [ex.submit(_one, i, model) for i in pending]
            for fut in concurrent.futures.as_completed(futures):
                idx, exc = fut.result()
                item = items[idx]
                with lock:
                    if exc is None:
                        item["status"] = "Generated"
                        item.pop("last_error", None)
                        model_trace[item["filename"]] = model
                    else:
                        item["status"] = "Failed"
                        item["last_error"] = str(exc)[:500]
                        item["last_model"] = model

    ok = sum(1 for it in items if it["status"] == "Generated")
    failed = sum(1 for it in items if it["status"] == "Failed")
    return ok, failed, model_trace


def _image_concurrency(pending_count: int) -> int:
    raw_value = os.environ.get("PPT_IMAGE_CONCURRENCY", "0").strip().lower()
    if raw_value in {"", "0", "auto"}:
        return max(1, pending_count)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "PPT_IMAGE_CONCURRENCY must be an integer or auto"
        ) from exc
    if not 1 <= value <= _MAX_ITEMS:
        raise RuntimeError(
            f"PPT_IMAGE_CONCURRENCY must be between 1 and {_MAX_ITEMS}"
        )
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


def _validate_manifest(path: Path, models: list[str]) -> dict[str, Any]:
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
        item_model = str(item.get("model", models[0])).strip()
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
        if item_model not in models:
            raise ValueError(
                f"Image item {index} model must be one of the configured PPT_IMAGE_MODEL values"
            )
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
    models = _model_list()
    model = models[0]  # primary, for audit/env defaults and result message
    image_size = _required_env("PPT_IMAGE_SIZE")
    parsed_url = urlparse(base_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise RuntimeError("PPT_IMAGE_BASE_URL must be an HTTPS URL")

    manifest = _manifest_path(manifest_path)
    payload = _validate_manifest(manifest, models)
    relative_manifest = manifest.relative_to(_job_dir()).as_posix()
    prior_total = _read_cumulative_total(payload, relative_manifest)
    initial_statuses = [str(item["status"]) for item in payload["items"]]
    pending_files = [
        str(item["filename"])
        for item in payload["items"]
        if item["status"] in {"Pending", "Failed"}
    ]
    concurrency = _image_concurrency(len(pending_files))

    def generated_this_call() -> int:
        return sum(
            initial_status in {"Pending", "Failed"}
            and str(item.get("status", "")) == "Generated"
            for initial_status, item in zip(initial_statuses, payload["items"])
        )

    audit_details = {
        "manifest_path": relative_manifest,
        "model": model,
        "models": models,
        "item_count": len(payload["items"]),
        "pending_files": pending_files,
        "requested_image_size": image_size,
        "concurrency": concurrency,
        # Preserve the running total across running/failed writes (see _write_audit).
        "cumulative_total": prior_total,
    }
    _write_audit("running", **audit_details)
    os.environ.update(
        {
            "IMAGE_BACKEND": "openai",
            "IMAGE_CONCURRENCY": str(concurrency),
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
            ok, failed, model_trace = _run_with_fallback(
                payload,
                backend,
                models=models,
                concurrency=concurrency,
                output_dir=str(manifest.parent),
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
        "message": f"Generated {len(generated_files)} image(s) with models {models}",
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
        model_trace=model_trace,
        **succeeded_details,
    )
    return result


@mcp.tool()
def generate_image_manifest(manifest_path: str) -> dict[str, Any]:
    """Generate every pending image in the current task's image_prompts.json manifest."""
    return _generate_image_manifest(manifest_path)


if __name__ == "__main__":
    mcp.run()
