"""Unit tests for image model fallback chain parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import image_mcp


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
