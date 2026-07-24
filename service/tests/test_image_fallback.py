"""Unit tests for image model fallback chain parsing."""

from __future__ import annotations

from service import image_mcp


def test_model_list_splits_comma(monkeypatch):
    monkeypatch.setenv("PPT_IMAGE_MODEL", "model-a, model-b ,model-c")
    assert image_mcp._model_list() == ["model-a", "model-b", "model-c"]


def test_model_list_single(monkeypatch):
    monkeypatch.setenv("PPT_IMAGE_MODEL", "gpt_image2")
    assert image_mcp._model_list() == ["gpt_image2"]


def test_model_list_empty_raises(monkeypatch):
    monkeypatch.delenv("PPT_IMAGE_MODEL", raising=False)
    try:
        image_mcp._model_list()
        assert False, "should raise"
    except RuntimeError:
        pass


def _manifest(*names):
    return {"items": [
        {"filename": n, "prompt": "p", "aspect_ratio": "16:9",
         "image_size": "1K", "status": "Pending"} for n in names
    ]}


class _FakeBackend:
    """generate() fails for `failing_models`, succeeds otherwise."""
    def __init__(self, failing_models, exc):
        self.failing_models = set(failing_models)
        self.exc = exc
        self.calls = []

    def generate(self, *, prompt, aspect_ratio, image_size, output_dir,
                 filename, model, max_retries):
        self.calls.append((filename, model))
        if model in self.failing_models:
            raise self.exc
        return f"{output_dir}/{filename}.png"


def test_fallback_switches_model_on_failure(tmp_path):
    payload = _manifest("a.png", "b.png")
    backend = _FakeBackend(failing_models=["model-a"], exc=RuntimeError("503 Service Unavailable"))
    ok, failed, trace = image_mcp._run_with_fallback(
        payload, backend, models=["model-a", "model-b"],
        concurrency=2, output_dir=str(tmp_path),
    )
    assert ok == 2 and failed == 0
    assert trace == {"a.png": "model-b", "b.png": "model-b"}
    assert all(it["status"] == "Generated" for it in payload["items"])


def test_fallback_all_models_fail(tmp_path):
    payload = _manifest("a.png")
    backend = _FakeBackend(failing_models=["m1", "m2"], exc=RuntimeError("503"))
    ok, failed, trace = image_mcp._run_with_fallback(
        payload, backend, models=["m1", "m2"],
        concurrency=1, output_dir=str(tmp_path),
    )
    assert ok == 0 and failed == 1
    assert payload["items"][0]["status"] == "Failed"
    assert "503" in payload["items"][0]["last_error"]


def test_fallback_primary_success_skips_backups(tmp_path):
    payload = _manifest("a.png")
    backend = _FakeBackend(failing_models=[], exc=RuntimeError("x"))
    ok, failed, trace = image_mcp._run_with_fallback(
        payload, backend, models=["m1", "m2"],
        concurrency=1, output_dir=str(tmp_path),
    )
    assert ok == 1 and failed == 0
    assert all(model == "m1" for _, model in backend.calls)
