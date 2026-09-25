"""Retarget BVH humanoid motion (Kimodo/SOMA) onto our boss rig. Runs under .venv-bpy.

    .venv-bpy/Scripts/python.exe retarget_bvh.py <rigged.glb> <bone_roles.json> <bvh_dir> <out_dir>

**Method: world-space rotation delta against a standing reference frame.**

Two facts about these BVH files decide the whole design, and both were measured
(`scratchpad/orient.py`), not assumed:

1. **The SOMA leg chain is `Leg -> Shin -> Foot`, not `UpLeg -> Leg -> Foot`.** `LeftUpLeg`
   does not exist in the file. The obvious-looking map silently dropped the hips and fed the
   *thigh's* rotation into the *knee* - which is most of what "twisted into pretzels" was.
2. **The BVH rest skeleton is lying on its side.** Its spine runs along world +X, so
   `up = +X`; only the motion channels stand the figure up. Posed, frame 1 measures
   `side +X, up +Z, forward -Y` - the same frame our demon's rest pose is in. So any method
   that copies *absolute* world orientation (a plain WORLD-space `COPY_ROTATION`, which is
   what the constraint+bake version did) tips him 90 degrees, every time.

Hence the transfer is a **delta**, taken in world space, against frame 1 of the clip:

    world_rotation(target bone, t) = Rsrc(t) . Rsrc(ref)^-1 . rest_world_rotation(target bone)

`Rsrc(t) . Rsrc(ref)^-1` is a plain world-space rotation, so differing bone rolls and bone-axis
conventions between the two rigs cancel out of it - that is the part the earlier local-space
delta and rest-conjugation attempts kept getting wrong. Frame 1 is the reference because every
clip starts from a standing idle and the file's own rest pose is unusable (see 2). The demon
therefore begins each clip in his own rest pose and moves out of it.

Bones are written parent-first through `pose_bone.matrix` (world space), so each bone's final
orientation is set explicitly rather than inherited from whatever its parent just did.

What is deliberately not driven:
  * wings and tail - not in the source skeleton, left at rest for a procedural overlay
  * jaw - pinned shut at `jaw_closed_deg` (-18, measured in JAW_ANGLES.png; the mesh was
    sculpted mouth-open, so 0 is wide open). It rides bone_34, which is why it looked loose
    while bone_34 was being driven.
  * bone_34, the snout - it has no counterpart in the source and rides the head

Knobs, both environment variables:

  ARM_ELEV_CAP   degrees above horizontal the upper arm may point. Default 35. His arms are
                 fused to the torso in the source mesh - there is no armpit - so a full
                 overhead raise stretches that bridge into a sheet no weighting can fix.
                 Set high (90) to disable. Only elevation is limited; horizontal swing,
                 which is what a haymaker needs, is untouched.
  RUN_LABEL      names the run: output goes to <out_dir>/<label>/ with a run.json recording
                 the rig, the knobs and the code commit. The outputs are gitignored, so that
                 manifest is the only record of what produced a given set of videos.
  BIND_MATCH     1 (default) to aim his bones along the source's frame-1 directions before
                 applying deltas, 0 to apply them to his rest pose instead. See "Bind pose"
                 below - without it every clip carries the rest-pose difference between a
                 human neutral stance and his.

Writes <out_dir>/animated.blend + animated.glb with one action per BVH file.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

RIGGED, ROLES, BVH_DIR, OUT = (os.path.abspath(p) for p in sys.argv[1:5])
BIND_MATCH = os.environ.get("BIND_MATCH", "1") != "0"
# RUN_LABEL puts this run in its own directory and writes run.json beside it, so a run can be
# gone back to. The outputs are gitignored (8.7 GB of them), so the manifest is the only record
# of which rig and which knobs produced a given set of videos.
LABEL = os.environ.get("RUN_LABEL", "").strip()
if LABEL:
    OUT = os.path.join(OUT, LABEL)
os.makedirs(OUT, exist_ok=True)

# SOMA bone -> path into bone_roles.json. Absent entries are simply not driven.
#
# Two naming traps, both measured (scratchpad/skel_dump.py) after the first pass came back with
# a distorted chest and a mangled face; see `_anatomy` in bone_roles.json:
#
#  * **The BVH's leg chain is `Leg -> Shin -> Foot`**, not the usual `UpLeg -> Leg -> Foot`.
#  * **Our own role names are off by one on the arms, and "head" is not the head.** The bone
#    labelled `arm_l.shoulder` (bone_14) is the *clavicle* - it carries 18k of upper-chest
#    weight, so driving it with the upper arm's swing dragged the chest with it. And `head`
#    (bone_34) is a 3.6 cm *snout* bone; the head is the one labelled `neck` (bone_13), which
#    owns 56k of weight centred on the skull. Driving the snout with the head's rotation is
#    what threw the face around. The names are left alone because animate_procedural.py uses
#    them; this table maps to the bones that are actually there.
MAP = {
    "Hips": ("root",),                        # bone_0  pelvis
    "Spine1": ("spine",),                     # bone_1  torso
    "Chest": ("chest",),                      # bone_12 chest
    "Head": ("neck",),                        # bone_13 the actual head
    "LeftShoulder": ("arm_l", "shoulder"),    # bone_14 clavicle
    "LeftArm": ("arm_l", "elbow"),            # bone_15 upper arm
    "LeftForeArm": ("arm_l", "wrist"),        # bone_16 forearm
    "LeftHand": ("arm_l", "hand"),            # bone_17 hand
    "RightShoulder": ("arm_r", "shoulder"),
    "RightArm": ("arm_r", "elbow"),
    "RightForeArm": ("arm_r", "wrist"),
    "RightHand": ("arm_r", "hand"),
    "LeftLeg": ("leg_l", "hip"),              # bone_2  thigh
    "LeftShin": ("leg_l", "knee"),            # bone_3  shin
    "LeftFoot": ("leg_l", "ankle"),           # bone_4  metatarsus - he is digitigrade, so this
    "LeftToeBase": ("leg_l", "foot"),         # bone_5  toes (11k weight - the part on the ground)
    "RightLeg": ("leg_r", "hip"),
    "RightShin": ("leg_r", "knee"),
    "RightFoot": ("leg_r", "ankle"),
    "RightToeBase": ("leg_r", "foot"),
}
# bone_6 / the source's ToeEnd are tips with no counterpart worth driving, so they ride the toes.


def log(*a):
    print("[retarget]", *a, flush=True)


def role_of(roles, path):
    node = roles
    for p in path:
        if p not in node:
            return None
        node = node[p]
    return node if isinstance(node, str) else None


def depth(bone):
    d = 0
    while bone.parent:
        bone, d = bone.parent, d + 1
    return d


def cap_elevation(m3, max_deg):
    """Stop a bone pointing higher than max_deg above horizontal.

    His arms are fused to the torso in the source mesh - there is no armpit, so a full overhead
    raise has to stretch that bridge into a sheet and no weighting fixes it. Capping how high
    the upper arm may point keeps the motion and avoids the worst of the web. Returns the
    correction rotation as well, so the forearm and hand can ride it down and keep their pose
    relative to the upper arm instead of folding.

    Only elevation is limited; the horizontal swing a haymaker needs is untouched.
    """
    d = (m3 @ Vector((0, 1, 0))).normalized()          # bone local +Y runs along the bone
    elev = math.degrees(math.asin(max(-1.0, min(1.0, d.z))))
    if elev <= max_deg:
        return m3, None
    horiz = Vector((d.x, d.y, 0.0))
    if horiz.length < 1e-6:
        horiz = Vector((1.0, 0.0, 0.0))
    axis = horiz.normalized().cross(Vector((0.0, 0.0, 1.0)))
    if axis.length < 1e-6:
        return m3, None
    r = Matrix.Rotation(-math.radians(elev - max_deg), 3, axis.normalized())
    return r @ m3, r


def main():
    roles = json.load(open(ROLES))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=RIGGED)
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
    tgt_height = max(zs) - min(zs)
    root_name = role_of(roles, ("root",))
    jaw = roles.get("jaw")
    jaw_closed = float(roles.get("jaw_closed_deg", 0.0))

    arm_cap = float(os.environ.get("ARM_ELEV_CAP", "35"))
    # role names are off by one (see MAP): "elbow" is the upper arm, "wrist" the forearm
    capped = {role_of(roles, (s, "elbow")): [role_of(roles, (s, "wrist")),
                                             role_of(roles, (s, "hand"))]
              for s in ("arm_l", "arm_r")}
    capped = {k: [v for v in vs if v] for k, vs in capped.items() if k}
    log("arm elevation capped at %+.0f deg above horizontal" % arm_cap)

    pairs = [(s, role_of(roles, p)) for s, p in MAP.items()]
    pairs = [(s, t) for s, t in pairs if t and t in tgt.pose.bones]
    pairs.sort(key=lambda st: depth(tgt.data.bones[st[1]]))       # parents first
    log("target height %.3f, root %s, driving %d bones" % (tgt_height, root_name, len(pairs)))

    # the target's rest pose in world space: the orientation each delta is applied to
    tw = tgt.matrix_world
    rest_rot = {t: (tw @ tgt.data.bones[t].matrix_local).to_3x3().normalized() for _, t in pairs}
    rest_head = {t: (tw @ tgt.data.bones[t].matrix_local).translation.copy() for _, t in pairs}

    actions = {}
    for bvh_path in sorted(glob.glob(os.path.join(BVH_DIR, "*.bvh"))):
        clip = os.path.splitext(os.path.basename(bvh_path))[0]
        before = set(bpy.data.objects)
        bpy.ops.import_anim.bvh(filepath=bvh_path, global_scale=0.01, rotate_mode="NATIVE")
        src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
        src_act = src.animation_data.action if src.animation_data else None
        if src_act:
            src_act.name = clip + "__src"      # the importer claims the clip name; we want it
        sc = bpy.context.scene
        # the importer does not touch the scene range, so ask the action how long the clip is;
        # the scene default (1-250) would pad every one of these 90-frame clips with a held pose
        f0, f1 = ((int(round(x)) for x in src_act.frame_range) if src_act
                  else (int(sc.frame_start), int(sc.frame_end)))
        f0, f1 = int(f0), int(f1)
        sc.frame_start, sc.frame_end = f0, f1
        use = [(s, t) for s, t in pairs if s in src.pose.bones]

        def src_world(name):
            return src.matrix_world @ src.pose.bones[name].matrix

        # reference = frame 1 posed; the file's own rest pose is lying on its side
        sc.frame_set(f0)
        bpy.context.view_layer.update()
        ref_inv = {s: src_world(s).to_3x3().normalized().inverted() for s, _ in use}

        # Bind pose. Deltas have to land on a *matching* starting angle: his arms hang about
        # 59 degrees below horizontal, the source's neutral is elsewhere, and mapping one onto
        # the other leaves that difference in every frame of every clip. So instead of applying
        # each delta to his rest pose, apply it to a reference pose in which each of his bones
        # already points the way its source counterpart points at frame 1. Computed, not hand
        # posed - `rotation_difference` gives the minimal rotation from his rest direction to
        # the source's, so bone roll is disturbed as little as possible.
        #
        # Frame 1 of each clip is the reference, so a clip whose first frame is not a neutral
        # stance will bind to whatever it does start in. Every keeper clip starts standing.
        bind_rot = dict(rest_rot)
        if BIND_MATCH:
            for s, t in use:
                ds = (src_world(s).to_3x3() @ Vector((0, 1, 0))).normalized()
                dt = (rest_rot[t] @ Vector((0, 1, 0))).normalized()
                bind_rot[t] = dt.rotation_difference(ds).to_matrix() @ rest_rot[t]
        src_h = max((src.matrix_world @ pb.head).z for pb in src.pose.bones)
        travel = tgt_height / max(src_h, 1e-6)
        root_src = next((s for s, t in use if t == root_name), None)
        ref_root = src_world(root_src).translation.copy() if root_src else Vector()

        tgt.animation_data_clear()
        for frame in range(f0, f1 + 1):
            sc.frame_set(frame)
            bpy.context.view_layer.update()
            ride = {}                       # correction the capped arm passes to its children
            for s, t in use:                                    # parent-first, world space
                pb = tgt.pose.bones[t]
                m = src_world(s)
                delta = m.to_3x3().normalized() @ ref_inv[s]
                want = delta @ bind_rot[t]
                if t in capped:
                    want, r = cap_elevation(want, arm_cap)
                    for child in capped[t]:
                        ride[child] = r
                elif ride.get(t) is not None:
                    want = ride[t] @ want
                if t == root_name:
                    loc = rest_head[t] + (m.translation - ref_root) * travel
                else:
                    loc = (tw @ pb.matrix).translation
                pb.matrix = tw.inverted() @ (Matrix.Translation(loc) @ want.to_4x4())
                bpy.context.view_layer.update()
                pb.keyframe_insert("rotation_quaternion", frame=frame)
                if t == root_name:
                    pb.keyframe_insert("location", frame=frame)
            if jaw and jaw_closed > 0 and jaw in tgt.pose.bones:
                jpb = tgt.pose.bones[jaw]
                axis = ((tw @ tgt.data.bones[jaw].matrix_local).to_3x3().inverted()
                        @ Vector((1, 0, 0))).normalized()
                jpb.rotation_quaternion = Quaternion(axis, math.radians(-jaw_closed))
                jpb.keyframe_insert("rotation_quaternion", frame=frame)

        action = tgt.animation_data.action
        action.name = clip
        action.use_fake_user = True
        action.use_frame_range = True
        action.frame_start, action.frame_end = f0, f1
        ad = tgt.animation_data
        ad.action = None
        track = ad.nla_tracks.new()
        track.name = clip
        track.strips.new(clip, f0, action)
        track.mute = True
        actions[clip] = action

        for pb in tgt.pose.bones:                      # leave nothing behind for the next clip
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
        bpy.data.objects.remove(src, do_unlink=True)
        if src_act:
            bpy.data.actions.remove(src_act)
        log("retargeted", clip, f1 - f0 + 1, "frames")

    # His arms are fused to the torso in the source mesh, so a big arm raise has to stretch the
    # armpit into a sheet. Blurred weights took the worst out of it (p99 edge stretch 6.8 -> 2.9);
    # this takes it to 2.2 and stops the sheet shredding. Measured in scratchpad/smooth_test.py.
    # Added after baking, never before: it re-evaluates 662k vertices on every depsgraph update,
    # and the bake does ~1800 of those per clip.
    if not any(m.type == "CORRECTIVE_SMOOTH" for m in mesh.modifiers):
        cs = mesh.modifiers.new("cs", "CORRECTIVE_SMOOTH")
        cs.factor, cs.iterations, cs.smooth_type = 1.0, 25, "SIMPLE"

    for img in bpy.data.images:
        if img.users and not img.packed_file:
            try:
                img.pack()
            except RuntimeError:
                pass
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, cwd=os.path.dirname(os.path.abspath(__file__))).stdout.strip()
    except Exception:
        sha = "?"
    json.dump({
        "label": LABEL or "(unlabelled)",
        "when": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "code": sha,
        "rig": RIGGED,
        "roles": ROLES,
        "bvh_dir": BVH_DIR,
        "method": "world-space rotation delta" + (" + bind-pose match" if BIND_MATCH else ""),
        "BIND_MATCH": BIND_MATCH,
        "ARM_ELEV_CAP": arm_cap,
        "bones_driven": len(pairs),
        "clips": {k: int(v.frame_end - v.frame_start + 1) for k, v in actions.items()},
    }, open(os.path.join(OUT, "run.json"), "w"), indent=1)

    blend = os.path.join(OUT, "animated.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    log("saved", blend, "with", len(actions), "actions")
    try:
        for t in tgt.animation_data.nla_tracks:
            t.mute = False
        bpy.ops.object.select_all(action="DESELECT")
        mesh.select_set(True)
        tgt.select_set(True)
        bpy.context.view_layer.objects.active = tgt
        bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "animated.glb"), use_selection=True,
                                  export_animations=True, export_animation_mode="NLA_TRACKS")
        log("exported animated.glb")
    except Exception as e:
        log("glb export skipped:", e)
    log("DONE")


if __name__ == "__main__":
    main()
