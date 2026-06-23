from __future__ import annotations

from PIL import Image

from tools.painted_map_pipeline.image_client import prepare_reference_upload
from tools.painted_map_pipeline.leonardo_api import is_v2_config


def test_is_v2_config_from_model():
    assert is_v2_config({"model": "nano-banana-2"})
    assert is_v2_config({"api_version": "v2"})
    assert not is_v2_config({"model_id": "abc", "base_url": "https://cloud.leonardo.ai/api/rest/v1"})


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
