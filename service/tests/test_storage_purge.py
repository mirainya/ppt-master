"""Unit tests for JobStorage.purge_job_files (pure filesystem logic)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from service.storage import JobStorage


def _storage(tmp_path: Path) -> JobStorage:
    return JobStorage(tmp_path / "jobs", max_upload_bytes=1024)


def test_purge_removes_job_directory(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    job_id = uuid4()
    storage.prepare_job(job_id)
    assert storage.job_dir(job_id).exists()

    removed = storage.purge_job_files(job_id)

    assert removed is True
    assert not storage.job_dir(job_id).exists()


def test_purge_is_idempotent_when_missing(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    job_id = uuid4()

    removed = storage.purge_job_files(job_id)

    assert removed is False


def test_purge_keeps_sibling_jobs(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    keep_id = uuid4()
    drop_id = uuid4()
    storage.prepare_job(keep_id)
    storage.prepare_job(drop_id)

    storage.purge_job_files(drop_id)

    assert storage.job_dir(keep_id).exists()
    assert not storage.job_dir(drop_id).exists()
