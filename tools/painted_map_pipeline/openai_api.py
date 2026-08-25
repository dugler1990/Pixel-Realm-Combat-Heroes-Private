"""Minimal OpenAI Images REST client (stdlib only).

Mirrors leonardo_api.py in shape and dependencies. Only the edits endpoint is needed:
it takes an image plus a mask, so the model repaints the masked region and leaves the
rest alone. Measured behaviour on gpt-image-2 is a soft mask -- edits stay inside the
mask apart from a bleed band a few hundred pixels wide, and beyond that the image is
untouched. Callers must not assume byte-exact preservation.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from pathlib import Path
from urllib import error, request

from .api_common import api_key

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"

# gpt-image-2 accepts arbitrary sizes within these bounds.
EDGE_MULTIPLE = 16
MIN_PIXELS = 655_000
MAX_PIXELS = 8_300_000
MAX_EDGE = 3840
MAX_ASPECT = 3.0
MAX_IMAGES = 16


class OpenAIApiError(RuntimeError):
    pass


def _api_key(config: dict) -> str:
    return api_key(config, default_env="OPENAI_API_KEY", error_cls=OpenAIApiError)


def validate_size(width: int, height: int, *, source: str = "") -> None:
    """Reject a canvas before anything is uploaded.

    The likely cause of a failure here is pointing this provider at a run prepared for a
    different one, so the message names the config rather than only quoting a number.
    """
    where = f"{source}: " if source else ""
    if width % EDGE_MULTIPLE or height % EDGE_MULTIPLE:
        raise OpenAIApiError(
            f"{where}canvas {width}x{height} must have both edges divisible by {EDGE_MULTIPLE}"
        )
    if max(width, height) > MAX_EDGE:
        raise OpenAIApiError(
            f"{where}canvas {width}x{height} exceeds the {MAX_EDGE}px maximum edge for gpt-image-2"
        )
    pixels = width * height
    if pixels > MAX_PIXELS:
        raise OpenAIApiError(
            f"{where}canvas {width}x{height} is {pixels / 1e6:.1f} MP, "
            f"gpt-image-2 allows {MAX_PIXELS / 1e6:.1f} MP"
        )
    if pixels < MIN_PIXELS:
        raise OpenAIApiError(
            f"{where}canvas {width}x{height} is {pixels / 1e6:.2f} MP, "
            f"below the {MIN_PIXELS / 1e6:.2f} MP minimum"
        )
    aspect = max(width / height, height / width)
    if aspect > MAX_ASPECT:
        raise OpenAIApiError(
            f"{where}canvas {width}x{height} has aspect {aspect:.2f}:1, "
            f"beyond the {MAX_ASPECT:.0f}:1 limit"
        )


def _multipart(fields: list[tuple[str, str]], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----PaintedMapBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    for name, path in files:
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode("utf-8")
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        parts.append(path.read_bytes())
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _post_multipart(url: str, api_key: str, body: bytes, boundary: str, timeout: float) -> dict:
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenAIApiError(f"OpenAI API POST {url} failed ({exc.code}): {detail[:2000]}") from exc
    except error.URLError as exc:
        raise OpenAIApiError(f"OpenAI API POST {url} failed: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OpenAIApiError(f"Invalid JSON from OpenAI API: {payload[:500]}") from exc


def edit_image(
    *,
    prompt: str,
    input_images: list[Path],
    mask: Path | None,
    output_path: Path,
    width: int,
    height: int,
    config: dict,
) -> dict:
    """Edit input_images[0] where `mask` is transparent, and write the result."""
    if not input_images:
        raise OpenAIApiError("openai edits requires at least one input image")
    if len(input_images) > MAX_IMAGES:
        raise OpenAIApiError(
            f"{len(input_images)} images supplied, gpt-image-2 accepts at most {MAX_IMAGES}"
        )
    validate_size(width, height, source=str(config.get("config_source") or ""))
    if not prompt.isascii():
        offender = next((c for c in prompt if not c.isascii()), "")
        raise OpenAIApiError(
            f"prompt contains the non-ASCII character {offender!r}; the returned filename "
            "is built from the prompt and a non-ASCII URL cannot be requested"
        )

    api_key = _api_key(config)
    base = str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    model = str(config.get("model") or DEFAULT_MODEL)

    fields = [
        ("model", model),
        ("prompt", prompt),
        ("size", f"{int(width)}x{int(height)}"),
    ]
    quality = config.get("quality")
    if quality:
        fields.append(("quality", str(quality).lower()))
    # Sent only when a config asks for it. gpt-image-2 rejects the field outright --
    # "does not support the 'input_fidelity' parameter", 400 on every call -- so defaulting it
    # on breaks the whole run. It exists here for models that do take it.
    input_fidelity = config.get("input_fidelity")
    if input_fidelity:
        fields.append(("input_fidelity", str(input_fidelity).lower()))
    # `background: transparent` is rejected by gpt-image-2; never send it.

    files: list[tuple[str, Path]] = [("image[]", path) for path in input_images]
    if mask is not None:
        files.append(("mask", mask))

    body, boundary = _multipart(fields, files)
    timeout = float(config.get("timeout_seconds", 900))
    result = _post_multipart(f"{base}/images/edits", api_key, body, boundary, timeout)

    entries = result.get("data") or []
    if not entries:
        raise OpenAIApiError(f"No image in OpenAI response: {json.dumps(result)[:500]}")
    encoded = entries[0].get("b64_json")
    if not encoded:
        raise OpenAIApiError(f"No b64_json in OpenAI response entry: {json.dumps(entries[0])[:500]}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(encoded))

    return {
        "provider": "openai",
        "model": model,
        "output_path": str(output_path),
        "width": int(width),
        "height": int(height),
        "input_images": [str(path) for path in input_images],
        "mask": str(mask) if mask else None,
        "quality": quality,
        "usage": result.get("usage"),
        "request": {field: value for field, value in fields},
    }
