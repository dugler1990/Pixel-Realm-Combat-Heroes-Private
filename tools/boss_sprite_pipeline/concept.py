"""Stage 0: concept image → subject cutout(s) for the mesh stage.

    concept/source.png   copy of the input
    concept/front.png    RGBA cutout, cropped to the subject + padding
    [concept/back.png, left.png, right.png]  extra views if you have them

Backends: ``sam3`` (the GPU box's Roboflow-inference workflow, same client as
the collision pipeline), ``rembg`` (CPU, pip install rembg), ``none`` (you put
front.png there yourself).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PAD = 16


def _cutout_from_mask(image: Image.Image, mask: np.ndarray) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3].copy()
    alpha[mask == 0] = 0
    out = np.asarray(rgba).copy()
    out[:, :, 3] = alpha
    ys, xs = np.nonzero(alpha)
    if not len(xs):
        raise SystemExit("cutout mask is empty")
    box = (max(0, xs.min() - PAD), max(0, ys.min() - PAD), min(rgba.width, xs.max() + PAD), min(rgba.height, ys.max() + PAD))
    return Image.fromarray(out).crop(box)


def cutout_sam3(image_path: Path, cfg: dict) -> Image.Image:
    from tools.painted_map_pipeline.collision.sam3.roboflow_workflow import extract_polygons, run_workflow

    result = run_workflow(image_path, cfg)
    polygons = extract_polygons(result)
    if not polygons:
        raise SystemExit("sam3 returned no polygons — check the workflow's prompt")
    image = Image.open(image_path)
    mask_img = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask_img)
    # largest polygons first; keep_top limits how many parts count as "the subject"
    polygons.sort(key=lambda p: -abs(_area(p["points"])))
    for poly in polygons[: int(cfg.get("keep_top", 1))]:
        draw.polygon([tuple(pt) for pt in poly["points"]], fill=255)
    return _cutout_from_mask(image, np.asarray(mask_img))


def _area(points) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return 0.5 * sum(xs[i] * ys[(i + 1) % len(xs)] - xs[(i + 1) % len(xs)] * ys[i] for i in range(len(xs)))


def cutout_rembg(image_path: Path, cfg: dict) -> Image.Image:
    try:
        from rembg import remove
    except ImportError:
        raise SystemExit("pip install rembg (CPU) for the rembg concept backend") from None
    rgba = remove(Image.open(image_path)).convert("RGBA")
    return _cutout_from_mask(rgba, (np.asarray(rgba)[:, :, 3] > 8).astype(np.uint8))


BACKENDS = {"sam3": cutout_sam3, "rembg": cutout_rembg}


def run(cfg: dict, workdir: Path, repo_root: Path) -> Path:
    stage = cfg.get("stages", {}).get("concept", {})
    backend = stage.get("backend", "none")
    concept_dir = workdir / "concept"
    concept_dir.mkdir(parents=True, exist_ok=True)
    front = concept_dir / "front.png"

    if backend == "none":
        if not front.exists():
            raise SystemExit(f"concept backend 'none': put a cutout at {front}")
        return front

    image_path = repo_root / cfg["concept_image"]
    shutil.copyfile(image_path, concept_dir / "source.png")
    views = {"front": image_path}
    for view in ("back", "left", "right"):
        if stage.get(f"{view}_image"):
            views[view] = repo_root / stage[f"{view}_image"]
    for view, path in views.items():
        cut = BACKENDS[backend](path, stage.get(backend, {}))
        cut.save(concept_dir / f"{view}.png")
        print(f"  {view}: {cut.size} ← {path.name}")
    return front
