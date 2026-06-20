from __future__ import annotations

import json
import shutil
from pathlib import Path


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


def make_image_client(config: dict):
    provider = str(config.get("provider") or "copy").strip().lower()
    if provider == "copy":
        return CopyImageClient()
    if provider in {"manifest", "dry_run", "dry-run"}:
        return ManifestOnlyImageClient()
    raise ImageClientError(
        f"Unknown image provider {provider!r}. Supported providers: copy, manifest."
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

