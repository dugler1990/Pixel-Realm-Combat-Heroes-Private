"""Bake one capsule per bone from a skinned mesh pack's skin.npz.

For each bone, take the rest vertices whose largest weight is that bone. The
capsule axis is the principal direction of those points, the ends sit at their
extremes along it, and the radius is the 90th-percentile distance from the axis
so stray vertices do not inflate it. Bones that own fewer than 15 vertices get
no capsule.

Writes Graphics/Meshes/<name>/body.json with a version, the sha1 of skin.npz,
and for each capsule the bone index, two rest-space ends, and a radius.

    python -m tools.boss_sprite_pipeline.bake_body_capsules demon
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

BODY_VERSION = 1
MIN_OWNED_VERTS = 15
RADIUS_PERCENTILE = 90.0


def _mesh_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "Graphics", "Meshes"))


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fit_capsule(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Return (end_a, end_b, radius) in rest space, or None if the cloud is degenerate."""
    if points.shape[0] < MIN_OWNED_VERTS:
        return None
    pts = points.astype(np.float64)
    mean = pts.mean(axis=0)
    centered = pts - mean
    if pts.shape[0] == 1 or float(np.linalg.norm(centered)) < 1e-12:
        return None
    # Principal axis from the largest singular vector of the centered cloud.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    axis = vt[0]
    axis_norm = float(np.linalg.norm(axis))
    if axis_norm < 1e-12:
        return None
    axis = axis / axis_norm
    along = centered @ axis
    a = mean + axis * float(along.min())
    b = mean + axis * float(along.max())
    # Distance from each point to the infinite axis through the mean.
    cross = np.cross(centered, axis)
    dists = np.linalg.norm(cross, axis=1)
    radius = float(np.percentile(dists, RADIUS_PERCENTILE))
    if radius < 1e-6:
        # A perfectly linear chain still needs a tiny thickness so projection
        # produces at least a stroke of pixels.
        radius = 1e-4
    return a.astype(np.float64), b.astype(np.float64), radius


def bake_pack(name: str, mesh_root: str | None = None) -> dict:
    root = os.path.join(mesh_root or _mesh_root(), name)
    skin_path = os.path.join(root, "skin.npz")
    if not os.path.isfile(skin_path):
        raise FileNotFoundError(f"no skin.npz at {skin_path}")
    data = np.load(skin_path)
    rest = np.asarray(data["rest_pos"], dtype=np.float64)
    joints = np.asarray(data["joints"])
    weights = np.asarray(data["weights"], dtype=np.float64)
    n_bones = int(np.asarray(data["skin_mats"]).shape[1])

    # Owned bone = joint slot with the largest weight for that vertex.
    owner = joints[np.arange(joints.shape[0]), np.argmax(weights, axis=1)].astype(np.int32)

    capsules = []
    for bone in range(n_bones):
        pts = rest[owner == bone]
        fitted = fit_capsule(pts)
        if fitted is None:
            continue
        a, b, radius = fitted
        capsules.append({
            "bone": int(bone),
            "a": [float(a[0]), float(a[1]), float(a[2])],
            "b": [float(b[0]), float(b[1]), float(b[2])],
            "radius": float(radius),
        })

    body = {
        "version": BODY_VERSION,
        "skin_sha1": sha1_file(skin_path),
        "capsules": capsules,
    }
    out_path = os.path.join(root, "body.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="mesh pack name under Graphics/Meshes/")
    parser.add_argument(
        "--mesh-root",
        default=None,
        help="override Graphics/Meshes directory",
    )
    args = parser.parse_args(argv)
    body = bake_pack(args.name, mesh_root=args.mesh_root)
    print(
        f"baked {args.name}: {len(body['capsules'])} capsules "
        f"(sha1={body['skin_sha1'][:12]}...)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
