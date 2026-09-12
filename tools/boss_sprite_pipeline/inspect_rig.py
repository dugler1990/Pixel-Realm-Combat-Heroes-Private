"""Dump a rigged model's bones to JSON (runs under .venv-bpy).

    inspect_rig.py rigged.glb bones.json

Each bone: name, parent, head/tail in world units, and a first-cut *role*
guess from position (root/spine/head/wing_l/wing_r/arm_l/arm_r/leg_l/leg_r/
tail/other). Stage 3's procedural recipes are keyed by role; the guesses are
meant to be corrected in the boss config (``bone_roles``) when they are wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


def load(path: Path) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    suffix = path.suffix.lower()
    if suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
    else:
        raise SystemExit(f"unsupported {path}")


def guess_roles(bones: list[dict], height: float, width: float) -> None:
    names = {b["name"]: b for b in bones}
    for b in bones:
        n = b["name"].lower()
        hx, hy, hz = b["head"]
        tx, ty, tz = b["tail"]
        side = "l" if hx > width * 0.08 else ("r" if hx < -width * 0.08 else "c")
        length = ((tx - hx) ** 2 + (ty - hy) ** 2 + (tz - hz) ** 2) ** 0.5
        horizontal = abs(tz - hz) < 0.5 * length
        role = "other"
        if b["parent"] is None:
            role = "root"
        elif any(k in n for k in ("wing",)):
            role = f"wing_{side}" if side != "c" else "wing_l"
        elif any(k in n for k in ("head", "neck", "jaw")):
            role = "head"
        elif any(k in n for k in ("tail",)):
            role = "tail"
        elif side != "c" and hz > height * 0.55 and horizontal and abs(hx) > width * 0.2:
            role = f"wing_{side}"
        elif side != "c" and hz > height * 0.4:
            role = f"arm_{side}"
        elif side != "c" and hz <= height * 0.4:
            role = f"leg_{side}"
        elif side == "c" and hz > height * 0.8:
            role = "head"
        elif side == "c":
            role = "spine"
        b["role"] = role
    # hand-authored bone_roles overrides are applied by animate.py, not here
    _ = names


def main(src: Path, out: Path) -> None:
    load(src)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    bpy.context.view_layer.update()
    xs, zs = [], []
    for m in meshes:
        for v in m.data.vertices:
            p = m.matrix_world @ v.co
            xs.append(p.x)
            zs.append(p.z)
    height = (max(zs) - min(zs)) if zs else 1.0
    width = (max(xs) - min(xs)) if xs else 1.0
    bones = []
    for arm in arms:
        mw = arm.matrix_world
        for bone in arm.data.bones:
            bones.append({
                "armature": arm.name,
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "head": [round(c, 4) for c in (mw @ bone.head_local)],
                "tail": [round(c, 4) for c in (mw @ bone.tail_local)],
            })
    guess_roles(bones, height, width)
    payload = {
        "source": src.name,
        "armatures": [a.name for a in arms],
        "mesh_height": height,
        "mesh_width": width,
        "bone_count": len(bones),
        "bones": bones,
        "roles": sorted({b["role"] for b in bones}),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[inspect_rig] {len(bones)} bones, roles {payload['roles']} → {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
