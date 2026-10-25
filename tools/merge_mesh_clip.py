"""Append a renamed clip from a skin bake into an existing mesh pack.

Usage:
  python tools/merge_mesh_clip.py \\
    --pack Graphics/Meshes/demon \\
    --source tmp/cast1_swift_bake \\
    --from-name kneepunch \\
    --as-name cast1_swift
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="Existing pack dir (skin.npz + pack.json)")
    ap.add_argument("--source", required=True, help="Fresh bake dir with the clip")
    ap.add_argument("--from-name", required=True, help="Clip name in the source bake")
    ap.add_argument("--as-name", required=True, help="Name to store in the pack")
    args = ap.parse_args()

    pack_dir = Path(args.pack)
    src_dir = Path(args.source)
    dst_skin = pack_dir / "skin.npz"
    src_skin = src_dir / "skin.npz"
    if not dst_skin.is_file() or not src_skin.is_file():
        raise SystemExit("both pack and source need skin.npz")

    dst = dict(np.load(dst_skin, allow_pickle=True))
    src = dict(np.load(src_skin, allow_pickle=True))
    dst_ranges = json.loads(str(dst["ranges"]))
    src_ranges = json.loads(str(src["ranges"]))
    if args.from_name not in src_ranges:
        raise SystemExit(f"{args.from_name!r} not in source ranges {list(src_ranges)}")
    if args.as_name in dst_ranges:
        print(f"replacing existing range {args.as_name}: {dst_ranges[args.as_name]}")

    dst_bones = [str(x) for x in dst["bone_names"].tolist()]
    src_bones = [str(x) for x in src["bone_names"].tolist()]
    if dst_bones != src_bones:
        raise SystemExit(
            f"bone_names mismatch\n  pack: {dst_bones}\n  src:  {src_bones}"
        )

    lo, hi = src_ranges[args.from_name]
    clip = src["skin_mats"][lo : hi + 1]
    start = int(dst["skin_mats"].shape[0])
    merged = np.concatenate([dst["skin_mats"], clip], axis=0)
    end = int(merged.shape[0] - 1)
    dst_ranges[args.as_name] = [start, end]

    # Drop old from-name if somehow present under that key.
    dst_ranges.pop(args.from_name, None)

    bak = pack_dir / "skin.npz.bak"
    if not bak.exists():
        shutil.copy2(dst_skin, bak)

    np.savez_compressed(
        dst_skin,
        rest_pos=dst["rest_pos"],
        rest_nrm=dst["rest_nrm"],
        uv=dst["uv"],
        indices=dst["indices"],
        joints=dst["joints"],
        weights=dst["weights"],
        skin_mats=merged.astype(np.float32),
        bone_names=dst["bone_names"],
        ranges=json.dumps(dst_ranges),
        fps=dst["fps"],
        bbox_lo=dst["bbox_lo"],
        bbox_hi=dst["bbox_hi"],
        pivot=dst["pivot"],
    )

    pack_path = pack_dir / "pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack["ranges"] = dst_ranges
    pack["frames"] = int(merged.shape[0])
    pack_path.write_text(json.dumps(pack, indent=1), encoding="utf-8")

    clips_path = pack_dir / "clips.json"
    clips = {}
    if clips_path.is_file():
        clips = json.loads(clips_path.read_text(encoding="utf-8"))
    clips[args.as_name] = {
        "source_action": args.from_name,
        "source_bake": str(src_dir.resolve()),
        "frames": int(hi - lo + 1),
        "range": [start, end],
        "used_by": clips.get(args.as_name, {}).get("used_by", []),
    }
    if "MeteorShower/Summoning" not in clips[args.as_name]["used_by"]:
        clips[args.as_name]["used_by"].append("MeteorShower/Summoning")
    clips_path.write_text(json.dumps(clips, indent=2), encoding="utf-8")

    print(f"merged {args.from_name} -> {args.as_name} as frames [{start}, {end}]")
    print(f"pack frames={merged.shape[0]} ranges={dst_ranges}")
    print(f"wrote {clips_path}")


if __name__ == "__main__":
    main()
