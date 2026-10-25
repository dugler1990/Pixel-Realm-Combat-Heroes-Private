"""Probe the demon rig for linear skinning. Does not write a pack.

    .venv-bpy/Scripts/python.exe probe_skin.py <idle.blend> <walk.blend> [tris]
"""
from __future__ import annotations

import os
import sys

import bpy
import numpy as np

SRC = os.path.abspath(sys.argv[1])
WALK = os.path.abspath(sys.argv[2])
TRIS = int(sys.argv[3]) if len(sys.argv) > 3 else 120000


def log(*a):
    print("[probe]", *a, flush=True)


def mat_str(m):
    a = np.array(m)
    return np.array2string(a, precision=5, suppress_small=True)


bpy.ops.wm.open_mainfile(filepath=SRC)
with bpy.data.libraries.load(WALK, link=False) as (data_from, data_to):
    data_to.actions = [n for n in data_from.actions if n == "walk"]
log("appended", [a.name for a in data_to.actions])

arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
scene = bpy.context.scene

log("shape_keys", mesh.data.shape_keys is not None)
mods = [(m.name, m.type) for m in mesh.modifiers]
log("modifier_stack", mods)
arm_mods = [m for m in mesh.modifiers if m.type == "ARMATURE"]
if not arm_mods:
    log("FAIL no armature modifier")
else:
    last = arm_mods[-1]
    after = [m.name for m in mesh.modifiers[mesh.modifiers.find(last.name) + 1:]]
    log("preserve_volume", bool(getattr(last, "use_deform_preserve_volume", None)))
    log("bone_envelopes", bool(getattr(last, "use_bone_envelopes", None)))
    log("vertex_groups", bool(getattr(last, "use_vertex_groups", None)))
    log("modifiers_after_armature", after or "none")

# Decimate the rest shape the same way the exporter does, then read weights.
for m in arm_mods:
    m.show_viewport = False
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
bpy.context.view_layer.objects.active = mesh
mesh.data.calc_loop_triangles()
n_tris = len(mesh.data.loop_triangles) or len(mesh.data.polygons) * 2
mod = mesh.modifiers.new("runtime_dec", "DECIMATE")
mod.decimate_type = "COLLAPSE"
mod.ratio = min(1.0, TRIS / max(n_tris, 1))
mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=mod.name)
for m in arm_mods:
    m.show_viewport = True
log("decimated_verts", len(mesh.data.vertices), "from_tris", n_tris)

deform = {b.name for b in arm.data.bones if b.use_deform}
groups = {g.index: g.name for g in mesh.vertex_groups}
deform_groups = {i for i, name in groups.items() if name in deform}
other_groups = sorted({name for name in groups.values() if name not in deform})
log("deform_bones", len(deform), "deform_groups", len(deform_groups), "other_groups", other_groups[:12], "n_other", len(other_groups))

n = len(mesh.data.vertices)
fifth = 0
zero = 0
max_inf = 0
for v in mesh.data.vertices:
    weights = []
    for g in v.groups:
        if g.group in deform_groups and g.weight > 0:
            weights.append(g.weight)
    weights.sort(reverse=True)
    max_inf = max(max_inf, len(weights))
    if not weights or sum(weights) <= 1e-8:
        zero += 1
    if len(weights) >= 5 and weights[4] > 0.05:
        fifth += 1
log("max_influences", max_inf, "verts", n, "fifth_above_0.05", fifth, "zero_deform", zero)

def pose(action_name, frame):
    action = bpy.data.actions[action_name]
    ad = arm.animation_data
    if ad is None:
        arm.animation_data_create()
        ad = arm.animation_data
    for t in ad.nla_tracks:
        t.mute = True
    ad.action = action
    if hasattr(action, "slots") and hasattr(ad, "action_slot") and len(action.slots):
        ad.action_slot = action.slots[0]
    scene.frame_set(frame)
    bpy.context.view_layer.update()


def world_co():
    dg = bpy.context.evaluated_depsgraph_get()
    ev = mesh.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    mw = np.array(mesh.matrix_world)
    world = (np.c_[co.reshape(-1, 3), np.ones(len(me.vertices))] @ mw.T)[:, :3]
    ev.to_mesh_clear()
    return world


samples = []
for name, frame in (("settle_01", 1), ("walk", 75)):
    pose(name, frame)
    samples.append(np.array(mesh.matrix_world))
    log("matrices", name, "frame", frame)
    log("arm", mat_str(arm.matrix_world))
    log("mesh", mat_str(mesh.matrix_world))

same = np.allclose(samples[0], samples[1], atol=1e-5)
log("mesh_matrix_world_constant", bool(same), "max_abs", float(np.max(np.abs(samples[0] - samples[1]))))

# Corrective smooth sits after the armature, so linear skinning will not match to_mesh().
pose("walk", 75)
with_cs = world_co()
post = [m for m in mesh.modifiers if m.type == "CORRECTIVE_SMOOTH"]
saved = [(m, m.show_viewport, m.show_render) for m in post]
for m, _, _ in saved:
    m.show_viewport = False
    m.show_render = False
arm_only = world_co()
for m, vp, rd in saved:
    m.show_viewport = vp
    m.show_render = rd
if with_cs.shape == arm_only.shape:
    delta = np.abs(with_cs - arm_only)
    log("cs_delta_walk75", "max", float(delta.max()), "mean", float(delta.mean()), "verts", len(delta))
else:
    log("cs_delta_walk75", "vert_count_mismatch", with_cs.shape, arm_only.shape)
log("done")
