import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.app import _filter_image_capabilities


def _caps(*entries):
    return {"code": 0, "message": "success", "data": list(entries)}


def test_filters_image_type_with_channels():
    payload = _caps(
        {"type": "image", "code": "gpt_image2", "name": "GPT 画图",
         "channels": [{"model": "gpt-image-2"}]},
        {"type": "video", "code": "sora2", "name": "Sora", "channels": [{"model": "sora2"}]},
        {"type": "image", "code": "empty_one", "name": "空的", "channels": []},
    )
    result = _filter_image_capabilities(payload)
    assert result == [{"code": "gpt_image2", "label": "GPT 画图"}]


def test_label_falls_back_to_code():
    payload = _caps(
        {"type": "image", "code": "doubao_img", "name": "", "channels": [{"model": "x"}]},
    )
    assert _filter_image_capabilities(payload) == [{"code": "doubao_img", "label": "doubao_img"}]


def test_bad_shape_returns_empty():
    assert _filter_image_capabilities({}) == []
    assert _filter_image_capabilities({"data": "nope"}) == []
    assert _filter_image_capabilities(None) == []
