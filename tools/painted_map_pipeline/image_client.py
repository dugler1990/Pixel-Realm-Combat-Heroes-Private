from __future__ import annotations

import io
import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from .leonardo_api import (
    LeonardoApiError,
    generate_with_content_reference,
    generate_with_image_reference,
    is_v2_config,
)

Image.MAX_IMAGE_PIXELS = None


class ImageClientError(RuntimeError):
    pass


class ImageClient:
    def generate(self, prompt: str, input_images: list[str], output_path: str):
        raise NotImplementedError


class CopyImageClient(ImageClient):
    """Local validation backend: copies source.png to painted.png.

    This proves the filesystem/TMX loop without requiring an image API key.
    """

    def generate(self, prompt: str, input_images: list[str], output_path: str):
        if not input_images:
            raise ImageClientError("copy backend requires at least one input image")
        src = Path(input_images[0])
        if not src.exists():
            raise ImageClientError(f"input image does not exist: {src}")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, output)
        return {"provider": "copy", "output_path": str(output)}


class ManifestOnlyImageClient(ImageClient):
    """Dry-run backend: writes request JSON and does not produce images."""

    def generate(self, prompt: str, input_images: list[str], output_path: str):
        request_path = Path(output_path).with_suffix(".request.json")
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(
                {"prompt": prompt, "input_images": input_images, "output_path": output_path},
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"provider": "manifest", "request_path": str(request_path), "output_path": output_path}


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.LANCZOS)


def _fit_gen_size(width: int, height: int, max_size: int) -> tuple[int, int]:
    max_size = max(64, int(max_size))
    scale = min(max_size / max(width, 1), max_size / max(height, 1), 1.0)
    out_w = max(64, int(round(width * scale)))
    out_h = max(64, int(round(height * scale)))
    out_w = max(64, out_w - (out_w % 8))
    out_h = max(64, out_h - (out_h % 8))
    return out_w, out_h


def _resolve_generation_size(config: dict, source_size: tuple[int, int]) -> tuple[int, int]:
    width = int(config.get("width") or 0)
    height = int(config.get("height") or 0)
    if width > 0 and height > 0:
        return width, height
    if is_v2_config(config):
        raise ImageClientError("Leonardo v2 config requires positive width and height")
    max_gen_size = int(config.get("max_gen_size", 1536))
    return _fit_gen_size(source_size[0], source_size[1], max_gen_size)


def prepare_reference_upload(
    image: Image.Image,
    *,
    target_size: tuple[int, int],
    max_upload_bytes: int,
    jpeg_quality: int = 90,
    min_jpeg_quality: int = 60,
) -> tuple[bytes, str]:
    """Return (file_bytes, extension) for Leonardo init-image upload (<= max_upload_bytes)."""
    image = image.convert("RGB")
    if image.size != target_size:
        image = image.resize(target_size, _resample_filter())

    quality = max(min_jpeg_quality, min(100, int(jpeg_quality)))
    while quality >= min_jpeg_quality:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        payload = buffer.getvalue()
        if len(payload) <= max_upload_bytes:
            return payload, "jpg"
        quality -= 5

    raise ImageClientError(
        f"Could not compress reference image to <= {max_upload_bytes} bytes "
        f"at quality >= {min_jpeg_quality} for size {target_size[0]}x{target_size[1]}"
    )


class LeonardoImageClient(ImageClient):
    """Leonardo.Ai generation (v2 Nano Banana image reference or v1 content reference)."""

    def __init__(self, config: dict):
        self.config = dict(config)

    def generate(self, prompt: str, input_images: list[str], output_path: str):
        if not input_images:
            raise ImageClientError("leonardo backend requires at least one input image")
        sources = [Path(path) for path in input_images]
        for src in sources:
            if not src.exists():
                raise ImageClientError(f"input image does not exist: {src}")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        preserve_native = bool(self.config.get("preserve_native_resolution", True))
        target_size = self.config.get("target_output_size")
        upscale_to = None
        if target_size and not preserve_native:
            upscale_to = (int(target_size[0]), int(target_size[1]))

        with Image.open(sources[0]) as primary:
            gen_w, gen_h = _resolve_generation_size(self.config, primary.size)

        temp_paths: list[Path] = []
        try:
            if is_v2_config(self.config):
                max_upload_bytes = int(self.config.get("max_upload_bytes", 10 * 1024 * 1024))
                jpeg_quality = int(self.config.get("reference_jpeg_quality", 90))
                for src in sources:
                    with Image.open(src) as image:
                        image = image.convert("RGBA")
                        payload, extension = prepare_reference_upload(
                            image,
                            target_size=(gen_w, gen_h),
                            max_upload_bytes=max_upload_bytes,
                            jpeg_quality=jpeg_quality,
                        )
                    with tempfile.NamedTemporaryFile(suffix=f".{extension}", delete=False) as tmp:
                        temp_path = Path(tmp.name)
                    temp_path.write_bytes(payload)
                    temp_paths.append(temp_path)
                try:
                    result = generate_with_image_reference(
                        prompt=prompt,
                        input_images=temp_paths,
                        output_path=output,
                        width=gen_w,
                        height=gen_h,
                        config=self.config,
                    )
                except LeonardoApiError as exc:
                    raise ImageClientError(str(exc)) from exc
            else:
                # v1 content reference still uses a single primary image.
                with Image.open(sources[0]) as image:
                    image = image.convert("RGBA")
                    if (gen_w, gen_h) != image.size:
                        if gen_w <= image.width and gen_h <= image.height:
                            thumb = image.copy()
                            thumb.thumbnail((gen_w, gen_h), _resample_filter())
                            image = thumb
                        else:
                            image = image.resize((gen_w, gen_h), _resample_filter())
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        temp_path = Path(tmp.name)
                    image.save(temp_path)
                    temp_paths.append(temp_path)
                try:
                    result = generate_with_content_reference(
                        prompt=prompt,
                        input_image=temp_paths[0],
                        output_path=output,
                        width=gen_w,
                        height=gen_h,
                        config=self.config,
                    )
                except LeonardoApiError as exc:
                    raise ImageClientError(str(exc)) from exc

            if upscale_to and upscale_to != (gen_w, gen_h):
                if not bool(self.config.get("skip_output_upscale", False)):
                    with Image.open(output) as generated:
                        generated.convert("RGBA").resize(upscale_to, _resample_filter()).save(output)
                    result["upscaled_to"] = list(upscale_to)
                else:
                    result["native_output_path"] = str(output)
                    result["target_full_size"] = list(upscale_to)
            result["generation_size"] = [gen_w, gen_h]
            result["reference_count"] = len(temp_paths)
            return result
        finally:
            for temp_path in temp_paths:
                temp_path.unlink(missing_ok=True)


def make_image_client(config: dict):
    provider = str(config.get("provider") or "copy").strip().lower()
    if provider == "copy":
        return CopyImageClient()
    if provider in {"manifest", "dry_run", "dry-run"}:
        return ManifestOnlyImageClient()
    if provider == "leonardo":
        return LeonardoImageClient(config)
    raise ImageClientError(
        f"Unknown image provider {provider!r}. Supported providers: copy, manifest, leonardo."
    )


def generate_painted_chunks(context_manifest: dict, image_config: dict):
    client = make_image_client(image_config)
    preserve_existing = bool(image_config.get("preserve_existing", False))
    results = []
    for pack in context_manifest.get("packs", []):
        context_dir = Path(pack["context_dir"])
        prompt = Path(pack["prompt_path"]).read_text(encoding="utf-8")
        output_path = Path(pack["painted_image"])
        refs = pack.get("references", {})
        source_ref = refs.get("source")
        is_current_size = True
        if output_path.exists() and source_ref and Path(source_ref).exists():
            try:
                from PIL import Image

                with Image.open(output_path) as output_image, Image.open(source_ref) as source_image:
                    is_current_size = output_image.size == source_image.size
            except OSError:
                is_current_size = False
        if preserve_existing and output_path.exists() and is_current_size:
            result_path = context_dir / "image_result.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    result = {}
            else:
                result = {}
            result.setdefault("provider", "preserve_existing")
            result.setdefault("output_path", str(output_path))
            result["preserved"] = True
            result["chunk_id"] = pack["chunk_id"]
            results.append(result)
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            continue
        input_images = []
        for key in ("source", "world_map_reference", "region_reference", "asset_contact_sheet"):
            value = refs.get(key)
            if value and Path(value).exists():
                input_images.append(value)
        result = client.generate(prompt, input_images, str(output_path))
        result["chunk_id"] = pack["chunk_id"]
        results.append(result)
        (context_dir / "image_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"results": results}
