"""Curated visual reference cases available to remote PPT tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReferenceCase:
    """Compact visual guidance derived from one reviewed example deck."""

    id: str
    label: str
    style: str
    tone: str
    best_for: str
    preview_path: str

    def prompt_record(self, repo_root: Path) -> dict[str, str]:
        preview = (repo_root / self.preview_path).resolve()
        preview.relative_to(repo_root.resolve())
        if not preview.is_file():
            raise FileNotFoundError(f"reference preview is missing: {preview}")
        return {
            "id": self.id,
            "label": self.label,
            "style": self.style,
            "tone": self.tone,
            "best_for": self.best_for,
            "preview_file": str(preview),
        }


def load_reference_cases(repo_root: Path) -> list[ReferenceCase]:
    """Load the checked-in reference catalog and validate its records."""
    catalog_path = repo_root / "service" / "reference_cases.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("reference case catalog must contain a JSON array")
    cases: list[ReferenceCase] = []
    seen_ids: set[str] = set()
    for raw_case in payload:
        if not isinstance(raw_case, dict):
            raise RuntimeError("reference case entries must be JSON objects")
        case = _parse_case(raw_case)
        if case.id in seen_ids:
            raise RuntimeError(f"duplicate reference case id: {case.id}")
        case.prompt_record(repo_root)
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def reference_case_labels(cases: list[ReferenceCase]) -> dict[str, str]:
    """Return display labels keyed by stable case identifier."""
    return {case.id: case.label for case in cases}


def _parse_case(raw_case: dict[str, Any]) -> ReferenceCase:
    required = ("id", "label", "style", "tone", "best_for", "preview_path")
    values = {key: str(raw_case.get(key, "")).strip() for key in required}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            f"reference case is missing required fields: {', '.join(missing)}"
        )
    return ReferenceCase(**values)
