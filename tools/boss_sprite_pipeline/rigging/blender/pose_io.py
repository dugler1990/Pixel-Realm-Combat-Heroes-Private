"""Blender in and out for the bake: read the target rig and a clip's matrices, write the pose keys.

No maths here; rigging.map.transfer does that on plain numpy arrays.
"""
from __future__ import annotations

import os

import bpy
import numpy as np


def _np(m) -> np.ndarray:
    return np.array([list(r) for r in m], dtype=float)


def _depth(bone) -> int:
    d = 0
    while bone.parent:
        bone, d = bone.parent, d + 1
    return d


def load_target(glb: str):
    """Factory scene + the rigged glb. Returns (armature, mesh, rig dict for transfer)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(coll)
    tgt = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
    for pb in tgt.pose.bones:
        pb.rotation_mode = "QUATERNION"
    verts = mesh.data.vertices
    mw = mesh.matrix_world
    zs = [(mw @ verts[i].co).z for i in range(0, len(verts), 50)]
    bones = sorted(tgt.data.bones, key=_depth)
    rig = {
        "tw": _np(tgt.matrix_world),
        "rest_arm": {b.name: _np(b.matrix_local) for b in bones},
        "parent": {b.name: (b.parent.name if b.parent else None) for b in bones},
        "length": {b.name: float(b.length) for b in bones},
        "height": float(max(zs) - min(zs)),
        "order": [b.name for b in bones],
    }
    return tgt, mesh, rig


def read_clip(bvh_path: str) -> dict:
    """Import one BVH (cm -> m), read every joint's world matrix on every frame, then remove it."""
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=bvh_path, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
    act = src.animation_data.action if src.animation_data else None
    sc = bpy.context.scene
    if act:
        f0, f1 = (int(round(x)) for x in act.frame_range)
    else:
        f0, f1 = int(sc.frame_start), int(sc.frame_end)
    sc.frame_start, sc.frame_end = f0, f1
    names = [pb.name for pb in src.pose.bones]
    mw = src.matrix_world
    world = {}
    height_f0 = 0.0
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        world[f] = {n: _np(mw @ src.pose.bones[n].matrix) for n in names}
        if f == f0:
            height_f0 = max((mw @ pb.head).z for pb in src.pose.bones)
    out = {
        "name": os.path.splitext(os.path.basename(bvh_path))[0],
        "frames": list(range(f0, f1 + 1)),
        "world": world,
        "rest_world": {n: _np(mw @ src.data.bones[n].matrix_local) for n in names},
        "parent": {n: (src.data.bones[n].parent.name if src.data.bones[n].parent else None) for n in names},
        "names": names,
        "height_f0": float(height_f0),
    }
    bpy.data.objects.remove(src, do_unlink=True)
    if act:
        bpy.data.actions.remove(act)
    return out


def write_action(tgt, clip: str, result: dict):
    """Key the pose basis values from transfer() onto the armature as one action on a muted NLA track."""
    tgt.animation_data_clear()
    frames = result["frames"]
    for t, qs in result["rot"].items():
        pb = tgt.pose.bones[t]
        for i, f in enumerate(frames):
            pb.rotation_quaternion = tuple(qs[i])
            pb.keyframe_insert("rotation_quaternion", frame=f)
    for t, ls in result["loc"].items():
        pb = tgt.pose.bones[t]
        for i, f in enumerate(frames):
            pb.location = tuple(ls[i])
            pb.keyframe_insert("location", frame=f)
    if result.get("jaw"):
        pb = tgt.pose.bones[result["jaw"]["bone"]]
        for f in frames:
            pb.rotation_quaternion = tuple(result["jaw"]["quat"])
            pb.keyframe_insert("rotation_quaternion", frame=f)
    action = tgt.animation_data.action
    action.name = clip
    action.use_fake_user = True
    action.use_frame_range = True
    action.frame_start, action.frame_end = frames[0], frames[-1]
    ad = tgt.animation_data
    ad.action = None
    track = ad.nla_tracks.new()
    track.name = clip
    track.strips.new(clip, frames[0], action)
    track.mute = True
    for pb in tgt.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    return action


def finish(tgt, mesh, out_dir: str, skip_glb: bool = False, log=print) -> None:
    """Corrective smooth, pack images, save animated.blend, export animated.glb (all NLA tracks)."""
    if not any(m.type == "CORRECTIVE_SMOOTH" for m in mesh.modifiers):
        cs = mesh.modifiers.new("cs", "CORRECTIVE_SMOOTH")
        cs.factor, cs.iterations, cs.smooth_type = 1.0, 25, "SIMPLE"
    for img in bpy.data.images:
        if img.users and not img.packed_file:
            try:
                img.pack()
            except RuntimeError:
                pass
    blend = os.path.join(out_dir, "animated.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    log("saved", blend)
    if skip_glb:
        log("skipped animated.glb")
        return
    try:
        for t in tgt.animation_data.nla_tracks:
            t.mute = False
        bpy.ops.object.select_all(action="DESELECT")
        mesh.select_set(True)
        tgt.select_set(True)
        bpy.context.view_layer.objects.active = tgt
        bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "animated.glb"), use_selection=True,
                                  export_animations=True, export_animation_mode="NLA_TRACKS")
        log("exported animated.glb")
    except Exception as e:  # noqa: BLE001 - the blend is already saved; the glb is a convenience
        log("glb export skipped:", e)
