from __future__ import annotations

from PIL import Image

from tools.painted_map_pipeline.image_client import prepare_reference_upload
from tools.painted_map_pipeline.leonardo_api import _readable_api_error, is_v2_config


def test_is_v2_config_from_model():
    assert is_v2_config({"model": "nano-banana-2"})
    assert is_v2_config({"api_version": "v2"})
    assert not is_v2_config({"model_id": "abc", "base_url": "https://cloud.leonardo.ai/api/rest/v1"})


def test_rejected_request_with_a_string_detail_still_prints():
    text = _readable_api_error(
        {"extensions": {"details": "rate limit"}},
        1280,
        720,
        "veo-3.1-lite",
    )
    assert "rate limit" in text
    assert "Leonardo rejected" in text
    assert "body:" in text


def test_prepare_reference_upload_fits_under_10mb():
    image = Image.new("RGB", (5056, 3392), color=(120, 140, 180))
    payload, extension = prepare_reference_upload(
        image,
        target_size=(5056, 3392),
        max_upload_bytes=10 * 1024 * 1024,
        jpeg_quality=90,
    )
    assert extension == "jpg"
    assert len(payload) <= 10 * 1024 * 1024


def test_reference_strength_per_image_or_from_config(monkeypatch):
    """One strength per image when given (the view gate sends its marked attempt LOW); otherwise the
    config's reference_strength on every image, as before."""
    from tools.painted_map_pipeline import leonardo_api

    sent = []
    monkeypatch.setattr(leonardo_api, "_api_key", lambda config: "key")
    monkeypatch.setattr(leonardo_api, "_request_json",
                        lambda method, url, key, payload: sent.append(payload) or {"generate": {"generationId": "g"}})
    config = {"model": "google/nano-banana-2.1", "reference_strength": "HIGH"}
    for strengths in (None, ["HIGH", "HIGH", "low"]):
        leonardo_api.create_v2_generation(prompt="p", width=1024, height=1024, init_image_ids=["a", "b", "c"],
                                          config=config, strengths=strengths)
    assert [r["strength"] for r in sent[0]["parameters"]["guidances"]["image_reference"]] == ["HIGH"] * 3
    assert [r["strength"] for r in sent[1]["parameters"]["guidances"]["image_reference"]] == ["HIGH", "HIGH", "LOW"]
