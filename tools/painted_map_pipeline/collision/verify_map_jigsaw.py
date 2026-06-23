"""Verify PaintedGround vs PaintedCollision alignment and write a review PNG artifact."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from .emit import load_manifest

Image.MAX_IMAGE_PIXELS = None


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.BICUBIC)



def _object_layer(root: ET.Element, name: str) -> list[ET.Element]:
    target = name.lower()
    for node in root:
        if node.tag == "objectgroup" and node.attrib.get("name", "").lower() == target:
            return list(node.findall("object"))
    raise ValueError(f"Object layer {name!r} not found")


def _box(obj: ET.Element) -> tuple[str, str, str, str]:
    return obj.attrib["x"], obj.attrib["y"], obj.attrib["width"], obj.attrib["height"]


def verify_tmx_layers(map_path: Path) -> dict:
    root = ET.parse(map_path).getroot()
    pg = _object_layer(root, "PaintedGround")
    pc = _object_layer(root, "PaintedCollision")
    if len(pg) != len(pc):
        raise ValueError(f"PaintedGround {len(pg)} objects != PaintedCollision {len(pc)}")
    mismatches = []
    for i, (a, b) in enumerate(zip(pg, pc)):
        if _box(a) != _box(b):
            mismatches.append({"index": i, "painted": _box(a), "collision": _box(b)})
    return {
        "map": str(map_path.resolve()),
        "painted_count": len(pg),
        "collision_count": len(pc),
        "coord_mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }


def write_jigsaw_preview(
    *,
    manifest_path: Path,
    collision_trial_root: Path,
    output_png: Path,
    variant_subdir: str = "leonardo_direct",
    max_width: int = 4096,
    collision_alpha: int = 140,
) -> dict:
    manifest = load_manifest(manifest_path)
    grid_world = manifest.get("grid_world_size") or [35392, 23744]
    first = manifest["chunks"][0]["world_rect"]
    origin_x, origin_y = int(first[0]), int(first[1])
    canvas_w = origin_x + int(grid_world[0])
    canvas_h = origin_y + int(grid_world[1])

    base = Image.new("RGBA", (canvas_w, canvas_h), (20, 20, 20, 255))
    overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    missing = []
    placed = 0
    for chunk in manifest.get("chunks", []):
        chunk_id = chunk["chunk_id"]
        x, y, w, h = [int(v) for v in chunk["world_rect"]]
        painted_path = Path(chunk["painted_image"])
        collision_path = collision_trial_root / chunk_id / variant_subdir / "collision_sprite.png"
        if not painted_path.exists():
            missing.append(f"painted:{chunk_id}")
            continue
        if not collision_path.exists():
            missing.append(f"collision:{chunk_id}")
            continue
        with Image.open(painted_path) as img:
            base.alpha_composite(img.convert("RGBA"), (x, y))
        with Image.open(collision_path) as img:
            col = img.convert("RGBA")
            if collision_alpha < 255:
                r, g, b, a = col.split()
                a = a.point(lambda p: min(255, int(p * collision_alpha / 255)))
                col = Image.merge("RGBA", (r, g, b, a))
            overlay.alpha_composite(col, (x, y))
        placed += 1

    composed = Image.alpha_composite(base, overlay)
    if max_width and composed.width > max_width:
        scale = max_width / composed.width
        composed = composed.resize(
            (max_width, max(1, int(round(composed.height * scale)))),
            _resample_filter(),
        )

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    composed.save(output_png)

    return {
        "preview_png": str(output_png.resolve()),
        "canvas_size": [canvas_w, canvas_h],
        "chunks_placed": placed,
        "missing": missing,
        "ok": placed == len(manifest.get("chunks", [])) and not missing,
    }


def verify_map_jigsaw(
    *,
    map_path: Path,
    manifest_path: Path,
    collision_trial_root: Path,
    output_dir: Path | None = None,
    variant_subdir: str = "leonardo_direct",
) -> dict:
    map_path = Path(map_path).resolve()
    out = Path(output_dir or map_path.parent / "export" / "jigsaw_verify")
    out.mkdir(parents=True, exist_ok=True)

    layer_report = verify_tmx_layers(map_path)
    preview_report = write_jigsaw_preview(
        manifest_path=Path(manifest_path).resolve(),
        collision_trial_root=Path(collision_trial_root).resolve(),
        output_png=out / "jigsaw_overlay_preview.png",
        variant_subdir=variant_subdir,
    )

    report = {
        "layers": layer_report,
        "preview": preview_report,
        "ok": layer_report["ok"] and preview_report["ok"],
        "review_artifact": preview_report["preview_png"],
        "instructions": (
            "Open review_artifact PNG: painted art with semi-transparent collision on top. "
            "Obstacle shapes must sit on terrain features, not offset. "
            "Optional: confirm same layout in Tiled on the map file."
        ),
    }
    report_path = out / "jigsaw_verify.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report_json"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Verify map jigsaw and write overlay preview PNG.")
    parser.add_argument("--map", default="levels/Frostreach/expanse/map_visual.tmx")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--collision-trial",
        default="levels/Frostreach/expanse/export/collision_trial",
    )
    args = parser.parse_args(argv)

    report = verify_map_jigsaw(
        map_path=(repo / args.map).resolve(),
        manifest_path=(repo / args.manifest).resolve(),
        collision_trial_root=(repo / args.collision_trial).resolve(),
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
