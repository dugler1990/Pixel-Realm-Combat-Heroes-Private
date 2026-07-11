"""Call a saved Roboflow Workflow (same pipeline as the UI)."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from inference_sdk import InferenceHTTPClient
except ImportError as exc:
    InferenceHTTPClient = None  # type: ignore[misc, assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class WorkflowError(RuntimeError):
    pass


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _api_key(config: dict[str, Any]) -> str:
    env_name = str(config.get("api_key_env") or "ROBOFLOW_API_KEY")
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise WorkflowError(f"Missing API key in environment variable {env_name!r}")
    return key


def _client(config: dict[str, Any]) -> InferenceHTTPClient:
    if InferenceHTTPClient is None:
        raise WorkflowError(
            "inference-sdk is not installed. Run: pip install inference-sdk"
        ) from _IMPORT_ERROR
    return InferenceHTTPClient(
        api_url=str(config.get("api_url") or "https://serverless.roboflow.com"),
        api_key=_api_key(config),
    )


def chunk_output_dir(config: dict[str, Any], repo: Path, chunk_id: str) -> Path:
    root = Path(config.get("output_dir") or "levels/Frostreach/expanse/export/sam3_obstacle")
    if not root.is_absolute():
        root = (repo / root).resolve()
    return root / chunk_id


def run_workflow(image_path: Path, config: dict[str, Any]) -> Any:
    """Run the configured Roboflow workflow on one local image file."""
    image_path = Path(image_path).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Missing image: {image_path}")

    input_name = str(config.get("input_name") or "image")
    workspace = str(config["workspace_name"])
    workflow_id = str(config["workflow_id"])
    use_cache = bool(config.get("use_cache", False))

    print(
        f"  calling {workflow_id} on {image_path.name} "
        f"(workspace={workspace}, input={input_name}) …",
        flush=True,
    )
    client = _client(config)
    return client.run_workflow(
        workspace_name=workspace,
        workflow_id=workflow_id,
        images={input_name: str(image_path)},
        use_cache=use_cache,
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"__bytes__": f"<{len(value)} bytes>"}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    return str(value)


def save_workflow_response(result: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_safe(result)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def summarize_response(result: Any, *, max_depth: int = 6) -> str:
    lines: list[str] = []

    def walk(value: Any, path: str, depth: int) -> None:
        if depth > max_depth:
            lines.append(f"{path}: …")
            return
        if isinstance(value, dict):
            lines.append(f"{path}: dict keys={list(value.keys())[:20]}")
            for key, child in list(value.items())[:30]:
                walk(child, f"{path}.{key}", depth + 1)
            return
        if isinstance(value, (list, tuple)):
            lines.append(f"{path}: list len={len(value)}")
            if value:
                walk(value[0], f"{path}[0]", depth + 1)
            return
        if isinstance(value, str):
            preview = value[:80] + "…" if len(value) > 80 else value
            lines.append(f"{path}: str len={len(value)} preview={preview!r}")
            return
        if isinstance(value, bytes):
            lines.append(f"{path}: bytes len={len(value)}")
            return
        lines.append(f"{path}: {type(value).__name__}")

    walk(result, "root", 0)
    return "\n".join(lines) + "\n"


def _extract_points(mask: Any) -> list[list[float]]:
    if mask is None:
        return []
    if isinstance(mask, dict):
        for key in ("points", "polygon", "coordinates", "data"):
            raw = mask.get(key)
            if raw is not None:
                return _extract_points(raw)
        return []
    if isinstance(mask, list):
        if not mask:
            return []
        first = mask[0]
        if isinstance(first, (int, float)):
            if len(mask) < 6 or len(mask) % 2 != 0:
                return []
            return [[float(mask[i]), float(mask[i + 1])] for i in range(0, len(mask), 2)]
        if isinstance(first, (list, tuple)) and len(first) >= 2:
            pts: list[list[float]] = []
            for item in mask:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    pts.append([float(item[0]), float(item[1])])
            return pts
        if isinstance(first, dict):
            pts = []
            for item in mask:
                if isinstance(item, dict):
                    x = item.get("x", item.get("X"))
                    y = item.get("y", item.get("Y"))
                    if x is not None and y is not None:
                        pts.append([float(x), float(y)])
            return pts
    return []


def _collect_polygons_from_node(
    node: Any,
    *,
    prompt: str = "",
    confidence: float | None = None,
    class_name: str = "",
    out: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if out is None:
        out = []
    if isinstance(node, dict):
        prompt = str(node.get("class") or node.get("label") or node.get("prompt") or prompt or class_name)
        if node.get("confidence") is not None:
            try:
                confidence = float(node["confidence"])
            except (TypeError, ValueError):
                pass
        if node.get("class_name") is not None:
            class_name = str(node["class_name"])

        for key in ("points", "polygon", "coordinates"):
            pts = _extract_points(node.get(key))
            if len(pts) >= 3:
                out.append(
                    {
                        "class": class_name or prompt,
                        "prompt": prompt,
                        "confidence": confidence if confidence is not None else 0.0,
                        "points": pts,
                    }
                )

        masks = node.get("masks")
        if masks is not None:
            if isinstance(masks, dict):
                masks = [masks]
            if isinstance(masks, list):
                for mask in masks:
                    pts = _extract_points(mask)
                    if len(pts) >= 3:
                        out.append(
                            {
                                "class": class_name or prompt,
                                "prompt": prompt,
                                "confidence": confidence if confidence is not None else 0.0,
                                "points": pts,
                            }
                        )

        predictions = node.get("predictions")
        if predictions is not None:
            if isinstance(predictions, dict):
                predictions = [predictions]
            for pred in predictions or []:
                if isinstance(pred, dict):
                    _collect_polygons_from_node(
                        pred,
                        prompt=prompt,
                        confidence=confidence,
                        class_name=class_name,
                        out=out,
                    )

        prompt_results = node.get("prompt_results")
        if prompt_results is not None:
            if isinstance(prompt_results, dict):
                prompt_results = [prompt_results]
            for pr in prompt_results or []:
                if isinstance(pr, dict):
                    echo = pr.get("echo") or {}
                    pr_prompt = str(echo.get("text") or prompt) if isinstance(echo, dict) else prompt
                    _collect_polygons_from_node(
                        pr,
                        prompt=pr_prompt,
                        confidence=confidence,
                        class_name=class_name,
                        out=out,
                    )

        for value in node.values():
            if isinstance(value, (dict, list)):
                _collect_polygons_from_node(
                    value,
                    prompt=prompt,
                    confidence=confidence,
                    class_name=class_name,
                    out=out,
                )
    elif isinstance(node, list):
        for item in node:
            _collect_polygons_from_node(
                item,
                prompt=prompt,
                confidence=confidence,
                class_name=class_name,
                out=out,
            )
    return out


def _dedupe_polygons(polygons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    unique: list[dict[str, Any]] = []
    for poly in polygons:
        pts = poly.get("points") or []
        if len(pts) < 3:
            continue
        key = tuple((round(float(x), 2), round(float(y), 2)) for x, y in pts[:8])
        if key in seen:
            continue
        seen.add(key)
        unique.append(poly)
    return unique


def extract_polygons(result: Any) -> list[dict[str, Any]]:
    """Walk workflow result and collect polygon point lists."""
    if isinstance(result, list) and result and isinstance(result[0], dict):
        # Workflow often returns [{output_name: value, ...}]
        merged: list[dict[str, Any]] = []
        for item in result:
            merged.extend(_collect_polygons_from_node(item))
        return _dedupe_polygons(merged)
    return _dedupe_polygons(_collect_polygons_from_node(result))


def _decode_image_bytes(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.convert("RGBA")
    except Exception:
        return None


def _image_from_value(value: Any) -> Image.Image | None:
    if value is None:
        return None
    if isinstance(value, Image.Image):
        return value.convert("RGBA")
    if isinstance(value, bytes):
        return _decode_image_bytes(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("data:image"):
            _, _, b64 = text.partition(",")
            if b64:
                try:
                    return _decode_image_bytes(base64.b64decode(b64))
                except Exception:
                    return None
        if text.startswith("http://") or text.startswith("https://"):
            return None
        try:
            return _decode_image_bytes(base64.b64decode(text))
        except Exception:
            return None
    if isinstance(value, dict):
        for key in ("value", "image", "data", "base64"):
            raw = value.get(key)
            if raw is not None:
                img = _image_from_value(raw)
                if img is not None:
                    return img
        if value.get("type") == "base64" and value.get("value"):
            return _image_from_value(str(value["value"]))
        if value.get("type") == "url" and value.get("value"):
            return None
    if hasattr(value, "shape"):
        try:
            import numpy as np

            arr = np.asarray(value)
            if arr.ndim == 3:
                return Image.fromarray(arr.astype("uint8")).convert("RGBA")
        except Exception:
            pass
    return None


def _collect_images(node: Any, path: str = "root", out: list[tuple[str, Image.Image]] | None = None) -> list[tuple[str, Image.Image]]:
    if out is None:
        out = []
    img = _image_from_value(node)
    if img is not None:
        out.append((path, img))
        return out
    if isinstance(node, dict):
        for key, value in node.items():
            _collect_images(value, f"{path}.{key}", out)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _collect_images(value, f"{path}[{idx}]", out)
    return out


def extract_preview_image(result: Any) -> Image.Image | None:
    """Pick the best visualization image from workflow outputs."""
    candidates = _collect_images(result)
    if not candidates:
        return None

    def score(path: str) -> int:
        lower = path.lower()
        if any(k in lower for k in ("visual", "overlay", "annotated", "output_image", "render")):
            return 100
        if "image" in lower:
            return 50
        return 0

    candidates.sort(key=lambda item: score(item[0]), reverse=True)
    return candidates[0][1]


def extract_outputs(
    result: Any,
    *,
    chunk_id: str,
    painted_image: Path,
    image_size: tuple[int, int],
) -> tuple[list[dict[str, Any]], Image.Image | None]:
    polygons = extract_polygons(result)
    preview = extract_preview_image(result)
    return polygons, preview


def write_chunk_outputs(
    *,
    output_dir: Path,
    chunk_id: str,
    painted_image: Path,
    image_size: tuple[int, int],
    result: Any,
    probe_only: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    save_workflow_response(result, output_dir / "workflow_response.json")
    (output_dir / "workflow_response_summary.txt").write_text(
        summarize_response(result),
        encoding="utf-8",
    )
    if probe_only:
        return output_dir

    polygons, preview = extract_outputs(
        result,
        chunk_id=chunk_id,
        painted_image=painted_image,
        image_size=image_size,
    )
    payload = {
        "chunk_id": chunk_id,
        "painted_image": str(painted_image),
        "image_size": list(image_size),
        "polygon_count": len(polygons),
        "polygons": polygons,
    }
    (output_dir / "polygons.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if preview is not None:
        preview.save(output_dir / "overlay_preview.png")
    return output_dir
