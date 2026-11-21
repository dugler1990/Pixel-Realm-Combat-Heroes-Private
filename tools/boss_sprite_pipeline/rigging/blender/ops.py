"""Rig edits applied in Blender. Each op: open the glb, change the armature, export to a new glb, return numbers.

move_pivot: generalises rigfix/fix_jaw_hinge.py - only the bone's head moves; direction, length and
            every weight are untouched. The pivot is not derived from any weight cut (fix_head_weights:
            tying the two together cancelled the pivot raise).
add_bone_joint: a bone where the source clip's joint is, relative to its parent joint, at the clip's
            first frame (never the BVH rest, which lies along +X), scaled by target / source height.
            No weights: the region stays on the parent until a weight step moves it.
"""
from __future__ import annotations

import json

import bpy
import numpy as np
from mathutils import Vector


def _open(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(coll)
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    return arm, mesh


def _export(arm, mesh, out):
    for img in bpy.data.images:
        if img.users and not img.packed_file:
            try:
                img.pack()
            except RuntimeError:
                pass
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(filepath=out, use_selection=True)


def _weighted_points(mesh, bone, min_w=0.5):
    vg = mesh.vertex_groups.get(bone)
    if vg is None:
        return np.zeros((0, 3))
    mw = mesh.matrix_world
    pts = [mw @ v.co for v in mesh.data.vertices for g in v.groups if g.group == vg.index and g.weight >= min_w]
    return np.array([list(p) for p in pts]) if pts else np.zeros((0, 3))


def move_pivot(glb, p, out):
    """p: bone, target ("geometry_top" | "geometry_bottom" | "point"), point [x,y,z] world, percentile."""
    arm, mesh = _open(glb)
    bone = p["bone"]
    if bone not in arm.data.bones:
        raise ValueError(f"no bone {bone}")
    was = arm.matrix_world @ arm.data.bones[bone].head_local
    if p["target"] == "point":
        z = None
        new_world = Vector(p["point"])
    else:
        pts = _weighted_points(mesh, bone)
        if not len(pts):
            raise ValueError(f"no vertices weighted >= 0.5 to {bone}")
        q = float(p.get("percentile", 97.0))
        z = np.percentile(pts[:, 2], q if p["target"] == "geometry_top" else 100 - q)
        new_world = Vector((was.x, was.y, float(z)))
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones[bone]
    eb.use_connect = False
    d = eb.tail - eb.head
    eb.head = arm.matrix_world.inverted() @ new_world
    eb.tail = eb.head + d
    bpy.ops.object.mode_set(mode="OBJECT")
    now = arm.matrix_world @ arm.data.bones[bone].head_local
    _export(arm, mesh, out)
    return {"bone": bone, "was": [round(x, 4) for x in was], "now": [round(x, 4) for x in now],
            "moved": round((now - was).length, 4)}


def add_bone_joint(glb, p, out):
    """p: name, parent (bone), parent_joint, joint (source joint names), bvh, length_frac."""
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))
    from tools.boss_sprite_pipeline.rigging.blender import pose_io
    clip = pose_io.read_clip(p["bvh"])
    f0 = clip["frames"][0]
    W = clip["world"][f0]
    for j in (p["parent_joint"], p["joint"]):
        if j not in W:
            raise ValueError(f"clip has no joint {j}")
    off = W[p["joint"]][:3, 3] - W[p["parent_joint"]][:3, 3]
    arm, mesh = _open(glb)
    if p["name"] in arm.data.bones:
        raise ValueError(f"{p['name']} exists")
    verts = mesh.data.vertices
    zs = [(mesh.matrix_world @ verts[i].co).z for i in range(0, len(verts), 50)]
    scale = (max(zs) - min(zs)) / max(clip["height_f0"], 1e-6)
    parent_head = arm.matrix_world @ arm.data.bones[p["parent"]].head_local
    head = parent_head + Vector((off * scale).tolist())
    d = Vector((off * scale).tolist())
    length = max(d.length * float(p.get("length_frac", 0.3)), 1e-3)
    tail = head + (d.normalized() if d.length > 1e-6 else Vector((0, -1, 0))) * length
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones.new(p["name"])
    inv = arm.matrix_world.inverted()
    eb.head, eb.tail = inv @ head, inv @ tail
    eb.parent = arm.data.edit_bones[p["parent"]]
    eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    mesh.vertex_groups.new(name=p["name"])          # empty: weights stay on the parent
    _export(arm, mesh, out)
    return {"bone": p["name"], "head": [round(x, 4) for x in head], "tail": [round(x, 4) for x in tail],
            "offset_scaled": [round(x, 4) for x in d], "scale": round(scale, 4)}


OPS = {"move_pivot": move_pivot, "add_bone_joint": add_bone_joint}


def run(name, glb, params_json, out):
    return OPS[name](glb, json.loads(open(params_json).read()), out)
