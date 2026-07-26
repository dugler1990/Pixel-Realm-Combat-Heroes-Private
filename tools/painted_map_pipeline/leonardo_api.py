"""Minimal Leonardo.Ai REST client (stdlib only)."""

from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib import error, parse, request

DEFAULT_V1_BASE_URL = "https://cloud.leonardo.ai/api/rest/v1"
DEFAULT_V2_BASE_URL = "https://cloud.leonardo.ai/api/rest/v2"
LUCID_ORIGIN_MODEL_ID = "7b592283-e8a7-4c5a-9ba6-d18c31f258b9"
CONTENT_REFERENCE_PREPROCESSOR_ID = 430
DEFAULT_NANO_BANANA_2_MODEL = "nano-banana-2"


class LeonardoApiError(RuntimeError):
    pass


def _api_key(config: dict) -> str:
    env_name = str(config.get("api_key_env") or "LEONARDO_API_KEY")
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise LeonardoApiError(f"Missing API key in environment variable {env_name!r}")
    return key


def is_v2_config(config: dict) -> bool:
    if str(config.get("api_version") or "").strip().lower() == "v2":
        return True
    if config.get("model"):
        return True
    base = str(config.get("base_url") or "").rstrip("/")
    return base.endswith("/v2")


def _v1_base_url(config: dict) -> str:
    for key in ("upload_base_url", "poll_base_url"):
        value = config.get(key)
        if value:
            return str(value).rstrip("/")
    base = str(config.get("base_url") or DEFAULT_V1_BASE_URL).rstrip("/")
    if base.endswith("/v2"):
        return DEFAULT_V1_BASE_URL
    return base


def _generation_base_url(config: dict) -> str:
    if is_v2_config(config):
        base = str(config.get("base_url") or DEFAULT_V2_BASE_URL).rstrip("/")
        if base.endswith("/v1"):
            return DEFAULT_V2_BASE_URL
        return base
    return _v1_base_url(config)


def _request_json(method: str, url: str, api_key: str, payload: dict | None = None, timeout: float = 120):
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {api_key}",
    }
    data = None
    if payload is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LeonardoApiError(f"Leonardo API {method} {url} failed ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise LeonardoApiError(f"Leonardo API {method} {url} failed: {exc}") from exc
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LeonardoApiError(f"Invalid JSON from Leonardo API: {body[:500]}") from exc


def _multipart_upload(url: str, fields: dict, file_field: str, file_path: Path, timeout: float = 120):
    boundary = f"----LeonardoBoundary{uuid.uuid4().hex}"
    body_parts: list[bytes] = []

    for key, value in fields.items():
        body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
        body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        body_parts.append(str(value).encode("utf-8"))
        body_parts.append(b"\r\n")

    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
    body_parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode(
            "utf-8"
        )
    )
    body_parts.append(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
    body_parts.append(file_bytes)
    body_parts.append(b"\r\n")
    body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(body_parts)

    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LeonardoApiError(f"Presigned upload failed ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise LeonardoApiError(f"Presigned upload failed: {exc}") from exc


def upload_init_image(image_path: Path, config: dict) -> str:
    api_key = _api_key(config)
    base = _v1_base_url(config)
    extension = image_path.suffix.lstrip(".").lower() or "png"
    payload = {"extension": extension}
    result = _request_json("POST", f"{base}/init-image", api_key, payload)
    upload = result.get("uploadInitImage") or result.get("upload_init_image")
    if not upload:
        raise LeonardoApiError(f"Unexpected init-image response: {result}")

    image_id = upload.get("id")
    upload_url = upload.get("url")
    raw_fields = upload.get("fields")
    if not image_id or not upload_url or raw_fields is None:
        raise LeonardoApiError(f"Incomplete init-image response: {upload}")

    if isinstance(raw_fields, str):
        fields = json.loads(raw_fields)
    else:
        fields = dict(raw_fields)

    _multipart_upload(upload_url, fields, "file", image_path)
    return str(image_id)


def create_generation(
    *,
    prompt: str,
    width: int,
    height: int,
    init_image_id: str,
    config: dict,
) -> str:
    api_key = _api_key(config)
    base = _generation_base_url(config)
    model_id = str(config.get("model_id") or LUCID_ORIGIN_MODEL_ID)
    preprocessor_id = int(config.get("preprocessor_id", CONTENT_REFERENCE_PREPROCESSOR_ID))
    strength_type = str(config.get("strength_type") or "High")

    payload = {
        "prompt": prompt,
        "width": int(width),
        "height": int(height),
        "modelId": model_id,
        "num_images": 1,
        "controlnets": [
            {
                "initImageId": init_image_id,
                "initImageType": "UPLOADED",
                "preprocessorId": preprocessor_id,
                "strengthType": strength_type,
            }
        ],
    }
    result = _request_json("POST", f"{base}/generations", api_key, payload)
    generation_id = _extract_generation_id(result)
    if not generation_id:
        raise LeonardoApiError(f"Unexpected generation response: {result}")
    return str(generation_id)


def get_generation(generation_id: str, config: dict) -> dict:
    api_key = _api_key(config)
    base = _v1_base_url(config)
    return _request_json("GET", f"{base}/generations/{generation_id}", api_key)


def create_v2_generation(
    *,
    prompt: str,
    width: int,
    height: int,
    init_image_ids: list[str],
    config: dict,
) -> str:
    api_key = _api_key(config)
    base = _generation_base_url(config)
    model = str(config.get("model") or DEFAULT_NANO_BANANA_2_MODEL)
    reference_strength = str(config.get("reference_strength") or "HIGH").upper()
    prompt_enhance = str(config.get("prompt_enhance") or "OFF").upper()
    style_ids = list(config.get("style_ids") or [])
    seed = config.get("seed")
    if not init_image_ids:
        raise LeonardoApiError("v2 generation requires at least one init image id")

    parameters: dict = {
        "width": int(width),
        "height": int(height),
        "prompt": prompt,
        "quantity": int(config.get("quantity", 1)),
        "prompt_enhance": prompt_enhance,
        "guidances": {
            "image_reference": [
                {
                    "image": {"id": image_id, "type": "UPLOADED"},
                    "strength": reference_strength,
                }
                for image_id in init_image_ids
            ]
        },
    }
    if style_ids:
        parameters["style_ids"] = style_ids
    if seed is not None:
        parameters["seed"] = int(seed)

    payload = {
        "model": model,
        "parameters": parameters,
        "public": bool(config.get("public", False)),
    }
    result = _request_json("POST", f"{base}/generations", api_key, payload)
    generation_id = _extract_generation_id(result)
    if not generation_id:
        raise LeonardoApiError(f"Unexpected v2 generation response: {result}")
    return str(generation_id)


def _first_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _pick_str(obj, *keys: str) -> str | None:
    if not isinstance(obj, dict):
        return None
    for key in keys:
        raw = obj.get(key)
        if raw is not None and str(raw).strip():
            return str(raw)
    return None


def _normalize_response(payload) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
    return {}


def _extract_generation_id(result) -> str | None:
    if isinstance(result, list):
        for entry in result:
            generation_id = _extract_generation_id(entry)
            if generation_id:
                return generation_id
        return None
    result = _normalize_response(result)
    for container in (
        result,
        _first_dict(result.get("generate")),
        _first_dict(result.get("generation")),
        _first_dict(result.get("sdGenerationJob")),
        _first_dict(result.get("generations_by_pk")),
    ):
        generation_id = _pick_str(container, "generationId", "id")
        if generation_id:
            return generation_id
    return None


def _generation_root(generation: dict) -> dict:
    return _first_dict(generation.get("generations_by_pk")) or _first_dict(generation)


def _iter_image_items(images) -> list[dict]:
    items: list[dict] = []
    if isinstance(images, dict):
        images = [images]
    if not isinstance(images, list):
        return items
    for entry in images:
        if isinstance(entry, dict):
            items.append(entry)
        elif isinstance(entry, list):
            for nested in entry:
                if isinstance(nested, dict):
                    items.append(nested)
    return items


def _extract_image_urls(generation) -> list[str]:
    urls: list[str] = []
    if isinstance(generation, list):
        for entry in generation:
            urls.extend(_extract_image_urls(entry))
        return urls
    root = _generation_root(_normalize_response(generation))
    images = root.get("generated_images") or root.get("images") or []
    for item in _iter_image_items(images):
        url = item.get("url")
        if url:
            urls.append(url)
    return urls


def _generation_status(generation) -> str:
    if isinstance(generation, list):
        for entry in generation:
            status = _generation_status(entry)
            if status:
                return status
        return ""
    root = _generation_root(_normalize_response(generation))
    return str(root.get("status") or root.get("generationStatus") or "").upper()


def wait_for_generation(generation_id: str, config: dict) -> dict:
    poll_interval = float(config.get("poll_interval_seconds", 5))
    poll_timeout = float(config.get("poll_timeout_seconds", 300))
    deadline = time.time() + poll_timeout
    last_status = ""
    while time.time() < deadline:
        result = get_generation(generation_id, config)
        status = _generation_status(result)
        last_status = status or last_status
        urls = _extract_image_urls(result)
        if urls:
            return result
        if status in {"FAILED", "ERROR"}:
            raise LeonardoApiError(f"Generation {generation_id} failed with status {status}: {result}")
        time.sleep(poll_interval)
    raise LeonardoApiError(
        f"Timed out waiting for generation {generation_id} (last status={last_status!r})"
    )


def download_url(url: str, output_path: Path, timeout: float = 120):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    req = request.Request(
        url,
        headers={
            "accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "user-agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "referer": "https://app.leonardo.ai/",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            output_path.write_bytes(resp.read())
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LeonardoApiError(f"Download failed ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise LeonardoApiError(f"Download failed: {exc}") from exc


def generate_with_image_reference(
    *,
    prompt: str,
    input_images: list[Path],
    output_path: Path,
    width: int,
    height: int,
    config: dict,
) -> dict:
    if not input_images:
        raise LeonardoApiError("v2 image reference requires at least one input image")
    init_image_ids = [upload_init_image(path, config) for path in input_images]
    generation_id = create_v2_generation(
        prompt=prompt,
        width=width,
        height=height,
        init_image_ids=init_image_ids,
        config=config,
    )
    result = wait_for_generation(generation_id, config)
    urls = _extract_image_urls(result)
    if not urls:
        raise LeonardoApiError(f"No image URLs in completed generation {generation_id}")
    download_url(urls[0], output_path)
    return {
        "provider": "leonardo",
        "api_version": "v2",
        "model": config.get("model") or DEFAULT_NANO_BANANA_2_MODEL,
        "output_path": str(output_path),
        "generation_id": generation_id,
        "init_image_ids": init_image_ids,
        "init_image_id": init_image_ids[0],
        "source_url": urls[0],
        "width": width,
        "height": height,
    }


def generate_with_content_reference(
    *,
    prompt: str,
    input_image: Path,
    output_path: Path,
    width: int,
    height: int,
    config: dict,
) -> dict:
    init_image_id = upload_init_image(input_image, config)
    generation_id = create_generation(
        prompt=prompt,
        width=width,
        height=height,
        init_image_id=init_image_id,
        config=config,
    )
    result = wait_for_generation(generation_id, config)
    urls = _extract_image_urls(result)
    if not urls:
        raise LeonardoApiError(f"No image URLs in completed generation {generation_id}")
    download_url(urls[0], output_path)
    return {
        "provider": "leonardo",
        "output_path": str(output_path),
        "generation_id": generation_id,
        "init_image_id": init_image_id,
        "source_url": urls[0],
        "width": width,
        "height": height,
    }
