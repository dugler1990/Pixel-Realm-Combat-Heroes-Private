"""Retarget BVH humanoid motion (Kimodo\SOMA) onto our boss rig. Runs under .venv-bpy.

    .venv-bpy\\Scripts/python.exe retarget_bvh.py <rigged.glb> <bone_roles.json> <bvh_dir> <out_dir>

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
  RETARGET_MODE  "rot" (default) copies bone rotations. "ik" instead copies where the hands
                 and feet GO, **body-relative**: the source's end-effector position measured
                 from its hips, scaled by height, placed relative to his hips, solved with
                 closed-form two-bone IK. Spine, chest, head and clavicles stay on rotation
                 copy either way - they measure 0.0 deg and need nothing.

                 Anchoring at the shoulder instead, scaled by arm length, is provably the
                 same thing as rotation copy and was measured to produce identical output; the
                 difference only appears body-relative, because what actually differs between
                 the two bodies is the torso, not the limb ratios.
  CLAVICLE_DAMP  0..1, default 1.0 (off). How much of the source's clavicle rotation to keep. The
                 source is a narrow-shouldered human and we are a wide-shouldered demon, so
                 copying it in full drags his shoulders inward and collapses the torso.
  BIND_SKIP      comma-separated bones to exclude from bind matching, on top of the head,
                 which is always excluded. A bone belongs here when its source counterpart is
                 not geometrically the same bone - aiming one along the other then introduces a
                 fixed error into every frame rather than removing one.
  SOURCE         "soma" (default) or "gargoyle" - which bone table to use. The gargoyle is the
                 free winged rig; it drives wings, jaw and neck, which SOMA cannot.
  JAW_CLOSED     degrees the jaw is held shut, overriding bone_roles.json. Negative closes;
                 the mesh was sculpted mouth-open so 0 is wide open. See rig/jaw/JAW_ANGLES.png.
  IDLE_POSE      path to idle_pose.json (rigfix/idle_pick.py writes it). Every clip then binds
                 to that one pose instead of its own frame 1, so all clips share a start pose.
                 The same file is the basis for Kimodo's frame-0/final-frame constraint - the
                 point is not which pose it is, it is that generation and retargeting use the
                 same one.
  IK_BODY        0..1, default 0.35. How far to dial the IK target from limb-anchored (0, i.e.
                 rotation copy) toward body-anchored (1). Pure body-anchored preserves contacts
                 but cramps him: his arms are a smaller fraction of his height than a human's,
                 so hips-relative targets land inside his reach and tuck the elbows in.
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

# Two call forms. The positional one is unchanged, so nothing that already calls this breaks:
#
#     retarget_bvh.py <rigged.glb> <roles.json> <bvh_dir> <out_dir>
#     retarget_bvh.py --source g1 --target demon <bvh_dir> <out_dir>
#
# The second resolves the rig, the roles and every per-character constant from the profile
# tables below, so a run names only what it is mapping FROM and TO.
# repo root, so the TARGETS table can hold short repo-relative paths
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_argv = sys.argv[1:]


def _opt(flag):
    if flag in _argv:
        i = _argv.index(flag)
        v = _argv[i + 1]
        del _argv[i:i + 2]
        return v
    return None


CLI_SOURCE = _opt("--source")
CLI_TARGET = _opt("--target")
if CLI_TARGET:
    BVH_DIR, OUT = (os.path.abspath(x) for x in _argv[0:2])
    RIGGED = ROLES = None           # filled in from TARGETS once the tables are defined
else:
    RIGGED, ROLES, BVH_DIR, OUT = (os.path.abspath(x) for x in _argv[0:4])
# MODE, IK_BODY and BIND_REF are resolved below, once SOURCES/TARGETS/PAIRS and setting()
# exist - they are profile-able like every other knob and must not be read from the
# environment directly here.
# One canonical idle, used both here as the bind reference and as Kimodo's start/end keyframe
# constraint. Which pose it is matters far less than that the same one is used in both places:
# if they differ, generated clips begin and end somewhere his idle animation never goes.
# Without it each clip binds to its own frame 1 and no two clips share a start pose.
IDLE_POSE = os.environ.get("IDLE_POSE", "")
# Both rigs bind to one agreed pose - the source file's T-pose - which is the whole
# point of a bind. "frame1" is the old behaviour and binds to whatever this clip
# happens to start in; it is kept only to reproduce the pre-2026-10-03 bakes.
IDLE_ROTS = {}
if IDLE_POSE and os.path.exists(IDLE_POSE):
    IDLE_ROTS = {k: Matrix(v).to_3x3() for k, v in json.load(open(IDLE_POSE))["rots"].items()}
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

# Second source: the free winged gargoyle (Objaverse, 3ds Max Biped naming). Selected with
# SOURCE=gargoyle. Unlike SOMA it has wings, a jaw and a neck, so those bones can be driven from
# real motion instead of sitting at rest. Same transfer, same caps, same wrap filter - only this
# table differs, which is the whole reason for routing it through here rather than a second
# implementation.
MAP_GARGOYLE = {
    "Bip01-Pelvis_03": ("root",),
    "Bip01-Spine_00": ("spine",),
    "Bip01-Spine2_05": ("chest",),
    "Bip01-Head_09": ("neck",),            # bone_13 is the actual head
    "Bip01-L-Clavicle_011": ("arm_l", "shoulder"),
    "Bip01-L-UpperArm_012": ("arm_l", "elbow"),
    "Bip01-L-Forearm_013": ("arm_l", "wrist"),
    "Bip01-R-Clavicle_019": ("arm_r", "shoulder"),
    "Bip01-R-UpperArm_020": ("arm_r", "elbow"),
    "Bip01-R-Forearm_021": ("arm_r", "wrist"),
    "Bip01-L-Thigh_045": ("leg_l", "hip"),
    "Bip01-L-Calf_046": ("leg_l", "knee"),
    "Bip01-L-Foot_047": ("leg_l", "ankle"),
    "Bip01-R-Thigh_049": ("leg_r", "hip"),
    "Bip01-R-Calf_050": ("leg_r", "knee"),
    "Bip01-R-Foot_051": ("leg_r", "ankle"),
    "Bone_Lwing001_028": ("wing_l", "arm"),
    "Bone_Lwing002_029": ("wing_l", "fan"),
    "Bone_Rwing001_036": ("wing_r", "arm"),
    "Bone_Rwing002_037": ("wing_r", "fan"),
}
# SOURCE=anunaki: same SOMA clips, but onto the UniRig Anunnaki rigs, whose roles are named
# literally (anun_roles.py derives them from the skeleton). They have a fourth torso bone and a
# real neck, so Spine2 and Neck1 drive something here - on the demon both had nowhere to go and
# were dropped, which is part of why his upper body reads stiff.
MAP_ANUNNAKI = {
    "Hips": ("root",),
    "Spine1": ("spine",),
    "Spine2": ("spine2",),
    "Chest": ("chest",),
    "Neck1": ("neck",),
    "Head": ("head",),
    "LeftShoulder": ("arm_l", "shoulder"),
    "LeftArm": ("arm_l", "elbow"),             # upper arm, as on the demon
    "LeftForeArm": ("arm_l", "wrist"),         # forearm
    "LeftHand": ("arm_l", "hand"),
    "RightShoulder": ("arm_r", "shoulder"),
    "RightArm": ("arm_r", "elbow"),
    "RightForeArm": ("arm_r", "wrist"),
    "RightHand": ("arm_r", "hand"),
    "LeftLeg": ("leg_l", "hip"),
    "LeftShin": ("leg_l", "knee"),
    "LeftFoot": ("leg_l", "ankle"),
    "LeftToeBase": ("leg_l", "foot"),
    "RightLeg": ("leg_r", "hip"),
    "RightShin": ("leg_r", "knee"),
    "RightFoot": ("leg_r", "ankle"),
    "RightToeBase": ("leg_r", "foot"),
}
# SOURCE=g1: the demo's robot mode, converted to BVH by rigfix/g1_to_bvh.py. The G1 splits every
# joint into single-axis links - a hip is pitch/roll/yaw as three separate bones - so the full
# rotation of a limb only exists at the LAST link in its chain; mapping the first gives a third
# of the motion. Hence yaw for hips and shoulders, roll for ankles and wrists.
#
# It has no head, no neck and no clavicles at all, so those demon bones stay at rest. Its waist
# is three links, which is one more torso segment than the demon has, so waist_pitch (the last)
# carries the chest and waist_yaw the spine.
MAP_G1 = {
    "pelvis_skel": ("root",),
    "waist_yaw_skel": ("spine",),
    "waist_pitch_skel": ("chest",),
    "left_shoulder_yaw_skel": ("arm_l", "elbow"),     # upper arm, as on the demon
    "left_elbow_skel": ("arm_l", "wrist"),            # forearm
    "left_wrist_roll_skel": ("arm_l", "hand"),
    "right_shoulder_yaw_skel": ("arm_r", "elbow"),
    "right_elbow_skel": ("arm_r", "wrist"),
    "right_wrist_roll_skel": ("arm_r", "hand"),
    "left_hip_yaw_skel": ("leg_l", "hip"),
    "left_knee_skel": ("leg_l", "knee"),
    # G1_FEET=1 to drive them: he is digitigrade - "ankle" is his metatarsus and "foot" his
    # toes - so a flat-footed robot's ankle angle points the whole foot down. Left at rest the
    # digitigrade shape is preserved and only the leg above the ankle is driven.
    "left_ankle_roll_skel": ("leg_l", "ankle"),
    "left_toe_base": ("leg_l", "foot"),
    "right_hip_yaw_skel": ("leg_r", "hip"),
    "right_knee_skel": ("leg_r", "knee"),
    "right_ankle_roll_skel": ("leg_r", "ankle"),
    "right_toe_base": ("leg_r", "foot"),
}
# ---------------------------------------------------------------------------------------
# Profiles. Every constant that used to be typed on a command line now lives beside the thing
# it is a fact about, because none of them were ever run-specific:
#
#   SOURCES  what the motion came from - which bone map, whether it needs converting first,
#            and what the skeleton simply does not have.
#   TARGETS  what it goes onto - the rig, and that character's permanent quirks.
#   PAIRS    only what emerges from the COMBINATION, owned by neither side alone.
#
# A run picks --source and --target; a knob is typed only to override deliberately.
SOURCES = {
    "soma": dict(map=MAP, to_bvh=None, expect_bones=20,
                 note="the default. 77-joint SOMA skeleton, has head and clavicles"),
    "gargoyle": dict(map=MAP_GARGOYLE, to_bvh="rigfix/gargoyle_to_bvh.py", expect_bones=20,
                     # Both graded bakes (animate_gargoyle2/3) recorded BIND_MATCH False. It is
                     # a real creature rig, not a human in a T-pose, so aiming his bones along
                     # a SOMA counterpart's direction is the wrong correction here.
                     bind_match=False,
                     # ROOT_LOC: None in animate_gargoyle2/3 means the setting did not exist
                     # when they were baked, i.e. root translation was NOT copied. Copying it
                     # sends him off-screen - peek.py renders an empty frame.
                     root_loc=False,
                     note="Objaverse 3ds Max Biped naming; has wings, jaw and a real neck"),
    "anunaki": dict(map=MAP_ANUNNAKI, to_bvh=None, expect_bones=22,
                    note="UniRig rigs with literal role names; fourth torso bone and a neck"),
    "g1": dict(map=MAP_G1, to_bvh="rigfix/g1_to_bvh.py", expect_bones=17,
               note="Unitree G1 robot, 34 joints. NO head, NO neck, NO clavicles - those three "
                    "demon bones cannot be driven from it, hence 17 and not 20. Its joints are "
                    "single-axis (a hip is pitch/roll/yaw as separate bones), so MAP_G1 targets "
                    "the LAST link of each chain, where the full rotation actually is."),
}

TARGETS = {
    "demon": dict(
        rig="generated/bosses/demon/rig/jaw/rigged_jaw_hinge.glb",
        roles="generated/bosses/demon/rig/jaw/bone_roles.json",
        # his arms are fused to the torso - there is no armpit - so a full overhead raise
        # stretches that bridge into a sheet no weighting can fix. This is a fact about him.
        arm_elev_cap=35.0,
        jaw_closed=14.0,
        # "ankle" is his metatarsus and "foot" his toes: he walks on his toes, not flat.
        digitigrade=True,
    ),
    "anunaki": dict(
        rig="generated/bosses/anunaki/rig/anun1_rigged.glb",
        roles="generated/bosses/anunaki/rig/anun1_roles.json",
        # Verified 2026-10-12 by rendering frame 1: bind matching ON collapses his spine and
        # sinks his head into his shoulders - he already stands correctly, so there is nothing
        # for it to correct. Cap left open; the 35 deg cap is for the demon's fused armpit and
        # the 0.0 in animate_anun1 pins his arms flat to his sides.
        bind_match=False,
        arm_elev_cap=90.0,
        digitigrade=False,
    ),
    "anun0": dict(
        rig="generated/bosses/anunaki/rig/anun0_rigged.glb",
        roles="generated/bosses/anunaki/rig/anun0_roles.json",
        bind_match=False, arm_elev_cap=90.0, digitigrade=False,
    ),
    "anun2": dict(
        rig="generated/bosses/anunaki/rig/anun2_rigged.glb",
        roles="generated/bosses/anunaki/rig/anun2_roles.json",
        bind_match=False, arm_elev_cap=90.0, digitigrade=False,
    ),
    "anun3": dict(
        rig="generated/bosses/anunaki/rig/anun3_rigged.glb",
        roles="generated/bosses/anunaki/rig/anun3_roles.json",
        bind_match=False, arm_elev_cap=90.0, digitigrade=False,
    ),
}

PAIRS = {
    # A flat-footed source onto a digitigrade target: bind matching would aim his metatarsus
    # along the source's flat foot and splay it. Bind-skipped bones keep their rest
    # orientation and take the motion on top, which is exactly what BIND_SKIP is for.
    ("g1", "demon"): dict(bind_skip=("leg_l.ankle", "leg_l.foot",
                                     "leg_r.ankle", "leg_r.foot")),
}

SOURCE = (CLI_SOURCE or os.environ.get("SOURCE", "") or "soma").lower()
TARGET = (CLI_TARGET or os.environ.get("TARGET", "") or "").lower()
if SOURCE not in SOURCES:
    raise SystemExit("unknown --source %r; have %s" % (SOURCE, sorted(SOURCES)))
if TARGET and TARGET not in TARGETS:
    raise SystemExit("unknown --target %r; have %s" % (TARGET, sorted(TARGETS)))
MAP = SOURCES[SOURCE]["map"]

_PROFILE = {}
_PROFILE.update(SOURCES[SOURCE])
if TARGET:
    _PROFILE.update(TARGETS[TARGET])
    _PROFILE.update(PAIRS.get((SOURCE, TARGET), {}))
    if RIGGED is None:
        RIGGED = os.path.abspath(os.path.join(REPO, TARGETS[TARGET]["rig"]))
        ROLES = os.path.abspath(os.path.join(REPO, TARGETS[TARGET]["roles"]))

SETTINGS_USED = {}


def setting(name, env, default, cast=str):
    """Resolve one knob: env var > pair > target > source > default, and record the winner."""
    raw, src = os.environ.get(env), "env"
    if raw is None or raw == "":
        if name in _PROFILE:
            raw, src = _PROFILE[name], "profile"
        else:
            raw, src = default, "default"
    val = raw if not isinstance(raw, str) or cast is str else cast(raw)
    if cast is not str and isinstance(raw, str):
        val = cast(raw)
    SETTINGS_USED[name] = {"value": val if not isinstance(val, tuple) else list(val),
                           "from": src}
    return val


BIND_MATCH = setting("bind_match", "BIND_MATCH", True,
                     lambda s: str(s).strip() not in ("", "0", "false", "False"))
MODE = setting("mode", "RETARGET_MODE", "rot", lambda s: str(s).strip().lower())
IK_BODY = setting("ik_body", "IK_BODY", 0.35, lambda s: max(0.0, min(1.0, float(s))))
# What the whole transfer is measured against. "tpose" uses the source's own rest skeleton
# (stood upright first, see the bind block); "frame1" is the old per-clip behaviour. An
# IDLE_POSE, when given, overrides both.
# "frame1" is what every bake that was ever graded good used - "tpose" was added on
# 2026-10-03, is unvalidated, and binding to a rest skeleton that lies along +X tips
# the character onto his side. Default stays with the known-good behaviour.
BIND_REF = setting("bind_ref", "BIND_REF", "frame1", lambda s: str(s).strip().lower())


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


def aim(m3, direction):
    """Point a bone along `direction`, keeping as much of its twist as possible.

    The rotation-copy orientation already carries the source's twist about the bone axis, which
    IK says nothing about. So rather than build an orientation from scratch, rotate the one we
    have by the minimal rotation that lands its axis on the target direction.
    """
    d = direction.normalized()
    cur = (m3 @ Vector((0, 1, 0))).normalized()
    return cur.rotation_difference(d).to_matrix() @ m3


def two_bone_ik(a, target, pole, l1, l2):
    """Closed-form two-link IK. Returns the middle joint position.

    Analytic rather than iterative: a two-link chain has an exact solution, so there is nothing
    to converge and nothing to flip. The pole only picks which way the elbow/knee bends - it is
    projected off the root-to-target axis, so it can never fight the reach.
    """
    to = target - a
    d = to.length
    if d < 1e-6:
        return a + Vector((0, 0, -l1))
    d = max(abs(l1 - l2) + 1e-4, min(l1 + l2 - 1e-4, d))     # keep it inside the reachable band
    n = to.normalized()
    u = (pole - a)
    u = u - n * u.dot(n)                                      # the bend plane, perpendicular to n
    if u.length < 1e-6:
        u = n.cross(Vector((0, 0, 1)))
        if u.length < 1e-6:
            u = n.cross(Vector((1, 0, 0)))
    u.normalize()
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2.0 * l1 * d)))
    ang = math.acos(cos_a)
    return a + l1 * (math.cos(ang) * n + math.sin(ang) * u)


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

    # **Measured 10x.** The bake calls frame_set once per frame per clip, and every one of those
    # re-evaluates the whole 55 MB skinned mesh - 662k vertices of armature deform - even though
    # the bake only ever reads bone matrices. Hiding the mesh from the viewport takes it out of
    # the depsgraph evaluation entirely: 0.5 -> 5 clips/min. It is restored before the file is
    # saved so the .blend and any glb export still contain a visible, skinned demon.
    # (This lived as a pod-side patch for the best-40 bake and was missing here, which is why a
    # two-clip run took 3m48s instead of ~40s.)
    _hidden = [m for m in bpy.data.objects if m.type == "MESH"]
    for m in _hidden:
        m.hide_viewport = True

    verts = mesh.data.vertices
    mw = mesh.matrix_world
    zs = [(mw @ verts[i].co).z for i in range(0, len(verts), 50)]
    tgt_height = max(zs) - min(zs)
    root_name = role_of(roles, ("root",))
    jaw = roles.get("jaw")
    jaw_closed = setting("jaw_closed", "JAW_CLOSED",
                         roles.get("jaw_closed_deg", 0.0), float)

    arm_cap = setting("arm_elev_cap", "ARM_ELEV_CAP", 35.0, float)
    # Clavicles. The source is a human with narrow shoulders; ours is a demon with a wide
    # shoulder girdle. Copying the human's clavicle rotation therefore pulls his shoulders in
    # towards a human's width on every arm movement, and the torso visibly collapses to follow
    # (seen in SOURCE_VS_DEMON.mp4). A clavicle's real job is a small shrug, so damp it hard and
    # let the upper arm carry the motion - his shoulder width then stays where it was sculpted.
    # RECONSTRUCTED 2026-10-04: this one declaration was the only line with no verbatim
    # source in the transcript. Semantics are fixed by its own surviving comment below
    # ("ROOT_LOC=0 pins the root and takes rotation only") and by run.json ("ROOT_LOC": true).
    root_loc = setting("root_loc", "ROOT_LOC", True,
                       lambda s: str(s).strip() not in ("", "0", "false", "False"))
    clav_damp = setting("clav_damp", "CLAVICLE_DAMP", 1.0, float)   # 1.0 = off
    clavicles = {role_of(roles, (s, "shoulder")) for s in ("arm_l", "arm_r")}
    clavicles = {c for c in clavicles if c}
    log("clavicle damping %.2f on %s" % (clav_damp, sorted(clavicles)))
    # role names are off by one (see MAP): "elbow" is the upper arm, "wrist" the forearm
    capped = {role_of(roles, (s, "elbow")): [role_of(roles, (s, "wrist")),
                                             role_of(roles, (s, "hand"))]
              for s in ("arm_l", "arm_r")}
    capped = {k: [v for v in vs if v] for k, vs in capped.items() if k}
    log("arm elevation capped at %+.0f deg above horizontal" % arm_cap)

    # IK chains: (upper bone, lower bone, source root joint, source mid joint, source end joint)
    # Role names are off by one, so "elbow" is the upper arm and "wrist" the forearm.
    CHAINS = []
    for side, sroot, smid, send in (("arm_l", "LeftArm", "LeftForeArm", "LeftHand"),
                                    ("arm_r", "RightArm", "RightForeArm", "RightHand"),
                                    ("leg_l", "LeftLeg", "LeftShin", "LeftFoot"),
                                    ("leg_r", "RightLeg", "RightShin", "RightFoot")):
        up = role_of(roles, (side, "elbow" if side.startswith("arm") else "hip"))
        lo = role_of(roles, (side, "wrist" if side.startswith("arm") else "knee"))
        if up in tgt.pose.bones and lo in tgt.pose.bones:
            CHAINS.append((up, lo, sroot, smid, send))
    if MODE == "ik":
        log("IK mode: %d chains %s" % (len(CHAINS), [c[0] for c in CHAINS]))

    pairs = [(s, role_of(roles, p)) for s, p in MAP.items()]
    pairs = [(s, t) for s, t in pairs if t and t in tgt.pose.bones]
    pairs.sort(key=lambda st: depth(tgt.data.bones[st[1]]))       # parents first
    log("target height %.3f, root %s, driving %d bones" % (tgt_height, root_name, len(pairs)))
    _want = SOURCES[SOURCE].get("expect_bones")
    if _want and len(pairs) != _want:
        log("WARNING: %s normally drives %d bones here, got %d - the map and this rig "
            "disagree, which looks plausible in the viewer and is not" % (SOURCE, _want, len(pairs)))

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

        # BIND_REF picks what the whole transfer is measured against:
        #
        #   frame1  (default)  frame 1 of this clip. Correct only while every clip starts from
        #                      the same neutral stance - which held for the generated suite
        #                      because it was constrained to a canonical idle, and does NOT hold
        #                      for clips typed into the demo UI with no constraint. There,
        #                      frame 1 is wherever the motion happens to begin, so each clip
        #                      binds to a different pose and the result is correct relative to
        #                      a wrong starting point: every bone measures 0.0 deg error and the
        #                      body still reads wrong.
        #   tpose              the BVH skeleton header's rest pose. It is the same for every
        #                      clip in every file, so alignment stops depending on the content
        #                      of the clip. This is the textbook bind - both rigs in one agreed
        #                      pose, everything else relative to it.
        #
        # The rest skeleton lies along +X, which is why it cannot be copied as an absolute
        # orientation; as a *reference* that cancels, because bind_rot is built from the same
        # pose and the transfer is a delta between the two.
        ref_rots = dict(IDLE_ROTS)
        if BIND_REF == "tpose" and not IDLE_ROTS:
            # **The rest skeleton's orientation is not consistent between files.** Clips saved
            # out of the Kimodo demo carry a rest spine along +X; the earlier generated suite's
            # runs along +Y. Binding straight to the header therefore binds some files to a
            # figure lying on its side, and the result is correct relative to a wrong reference
            # - every bone reads 0.0 deg in dir_check and the body still comes out mangled.
            # (That is exactly what happened to kick/stomp/stomp2 on 2026-10-04.)
            #
            # So measure the rest spine, hips -> chest, and rotate the whole rest frame to a
            # canonical up before using it. Applying one rotation to every bone leaves the
            # relative pose untouched, which is all a bind reference has to preserve.
            # REVERTED 2026-10-12, left opt-in behind REST_UPRIGHT=1 and OFF by default.
            # The reasoning below was wrong: the rest skeleton lying along +X does not matter,
            # because the transfer is a *delta* and bind_rot is built from the same rest pose,
            # so its orientation cancels (see "The transfer" in NOTES_retarget_kimodo.md).
            # Standing it up therefore changed nothing that was broken and broke the clips that
            # were binding correctly - every file, groundslam included, came out crumpled.
            # Whatever makes kick/stomp differ from the groundslams, it is not this.
            spine_lo = next((s for s, p_ in MAP.items() if p_ == ("root",)), None)
            spine_hi = next((s for s, p_ in MAP.items() if p_ == ("chest",)), None)
            fix = Matrix.Identity(3)
            if (os.environ.get("REST_UPRIGHT")
                    and spine_lo in src.data.bones and spine_hi in src.data.bones):
                lo = (src.matrix_world @ src.data.bones[spine_lo].matrix_local).translation
                hi = (src.matrix_world @ src.data.bones[spine_hi].matrix_local).translation
                up = (hi - lo)
                if up.length > 1e-6:
                    up.normalize()
                    if abs(up.z) < 0.9:          # not already standing up in Z
                        fix = up.rotation_difference(Vector((0.0, 0.0, 1.0))).to_matrix()
                        log("rest skeleton leans %s - standing it up for the bind"
                            % (", ".join("%.2f" % v for v in up)))
            for s, _ in use:
                ref_rots[s] = (fix @ (src.matrix_world
                                      @ src.data.bones[s].matrix_local).to_3x3()).normalized()

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
        # Bind matching is only valid where the two bones mean the same thing. SOMA's Head runs
        # toward the face; his bone_13 runs toward the crown - measured at +18..+52 deg against
        # his +82 - so aiming one along the other pitches his head 30-65 deg forward and buries
        # the chin in his chest. Bones listed here keep their rest orientation as the bind and
        # take the delta on top, which is the correct treatment for a bone with no true twin.
        # The profile gives role paths ("leg_l.ankle") so the tables stay readable and
        # survive a re-rig; an env override may still name raw bones ("bone_4").
        _skip = setting("bind_skip", "BIND_SKIP", (),
                        lambda s: tuple(x for x in str(s).split(",") if x))
        bind_skip = {role_of(roles, ("neck",))}
        for x in _skip:
            bind_skip.add(role_of(roles, tuple(x.split("."))) if "." in x else x)
        bind_skip = {b for b in bind_skip if b}
        bind_rot = dict(rest_rot)
        if BIND_MATCH:
            for s, t in use:
                if t in bind_skip:
                    continue
                ref = ref_rots.get(s) or src_world(s).to_3x3()
                ds = (ref.normalized() @ Vector((0, 1, 0))).normalized()
                dt = (rest_rot[t] @ Vector((0, 1, 0))).normalized()
                bind_rot[t] = dt.rotation_difference(ds).to_matrix() @ rest_rot[t]
        # ref_inv must be taken at the SAME pose the bind was built from, or the two disagree
        # and every frame carries the difference. With a canonical idle that means measuring the
        # source at the idle pose, not at this clip's frame 1.
        for s, t in use:
            if s in ref_rots and t not in bind_skip:
                ref_inv[s] = ref_rots[s].normalized().inverted()
        # Each chain gets its own scale, from its own length. Scaling hand targets by overall
        # height would leave him unable to reach: his arms are not the same fraction of his
        # height that a human's are. Anchored at his own shoulder/hip, so his wider chest moves
        # the whole target with it rather than stretching the arm across.
        chain_scale, chain_len = {}, {}
        for up, lo, sroot, smid, send in CHAINS:
            if sroot not in src.pose.bones:
                continue
            sl = ((src_world(smid).translation - src_world(sroot).translation).length
                  + (src_world(send).translation - src_world(smid).translation).length)
            tl1 = (tw @ tgt.data.bones[up].matrix_local.translation
                   - tw @ tgt.data.bones[lo].matrix_local.translation).length
            tl2 = tgt.data.bones[lo].length * tw.to_scale().x
            chain_len[up] = (tl1, tl2)
            chain_scale[up] = (tl1 + tl2) / max(sl, 1e-6)
        if MODE == "ik":
            log("  %s chain lengths %s" % (clip, {k: (round(a, 3), round(b, 3))
                                                  for k, (a, b) in chain_len.items()}))

        src_h = max((src.matrix_world @ pb.head).z for pb in src.pose.bones)
        travel = tgt_height / max(src_h, 1e-6)
        # ROOT_LOC=0 pins the root and takes rotation only. The gargoyle export needs it: its
        # pelvis hangs on a 114x179-unit offset below joints that are themselves at 0.55-unit
        # scale, so any rotation up-chain swings the whole body thousands of units out of frame
        # (body span stayed a correct 0.80 while its centre reached 24000). Losing that
        # translation costs nothing here - the game drives the entity's position, and every
        # Kimodo clip already measures drift 0.00.
        root_src = next((s for s, t in use if t == root_name), None)
        ref_root = src_world(root_src).translation.copy() if root_src else Vector()

        tgt.animation_data_clear()
        for frame in range(f0, f1 + 1):
            sc.frame_set(frame)
            bpy.context.view_layer.update()
            ride = {}                       # correction the capped arm passes to its children
            aim_at = {}                     # direction IK wants a bone to point, set by its parent
            for s, t in use:                                    # parent-first, world space
                pb = tgt.pose.bones[t]
                m = src_world(s)
                delta = m.to_3x3().normalized() @ ref_inv[s]
                if t in clavicles and clav_damp < 1.0:
                    # slerp from identity toward the source's rotation - lerping the matrices
                    # would not stay a rotation
                    delta = Quaternion().slerp(delta.to_quaternion(), clav_damp).to_matrix()
                want = delta @ bind_rot[t]
                if MODE == "ik" and t in chain_scale:
                    # Anchor at the HIPS, not the shoulder.
                    #
                    # Anchoring at the shoulder and scaling by the chain's own length is exactly
                    # equivalent to rotation copy - measured, identical output - because his
                    # upper-arm:forearm ratio (1.03) matches a human's, so both the direction and
                    # the bend angle come out the same. Two-bone IK only diverges when those
                    # ratios differ, and they do not.
                    #
                    # What differs is the torso: his chest is far wider, so the same joint angles
                    # put his hand somewhere else *on his own body*. Anchoring body-relative and
                    # scaling by height is what preserves that - a hand that came to the source's
                    # chest comes to his chest. Where the target is out of reach the solver clamps
                    # to full extension, which is the right failure: he stretches for it.
                    up, lo, sroot, smid, send = next(c for c in CHAINS if c[0] == t)
                    a = (tw @ pb.matrix).translation
                    hips = (tw @ tgt.pose.bones[root_name].matrix).translation
                    sh = src_world(root_src).translation
                    sa = src_world(sroot).translation
                    k = chain_scale[t]
                    # IK_BODY dials between the two anchors. Limb-anchored is rotation copy
                    # exactly, so 0 reproduces "rot" and 1 is pure body-relative; in between is
                    # the useful range, since body-relative alone cramps him - his arms are
                    # shorter relative to his height than a human's, so a hips-relative target
                    # lands inside his reach and tucks the elbows into his chest.
                    lim_t = a + (src_world(send).translation - sa) * k
                    lim_p = a + (src_world(smid).translation - sa) * k
                    bod_t = hips + (src_world(send).translation - sh) * travel
                    bod_p = hips + (src_world(smid).translation - sh) * travel
                    target = lim_t.lerp(bod_t, IK_BODY)
                    pole = lim_p.lerp(bod_p, IK_BODY)
                    if t in capped:                 # cap the reach, not the angle, in IK mode
                        to = target - a
                        elev = math.degrees(math.asin(max(-1.0, min(1.0, to.normalized().z))))
                        if elev > arm_cap:
                            horiz = Vector((to.x, to.y, 0.0))
                            if horiz.length > 1e-6:
                                ax = horiz.normalized().cross(Vector((0.0, 0.0, 1.0)))
                                if ax.length > 1e-6:
                                    to = (Matrix.Rotation(-math.radians(elev - arm_cap), 3,
                                                          ax.normalized()) @ to)
                                    target = a + to
                    l1, l2 = chain_len[t]
                    mid = two_bone_ik(a, target, pole, l1, l2)
                    want = aim(want, mid - a)
                    aim_at[lo] = (mid, target)
                elif MODE == "ik" and t in aim_at:
                    mid, target = aim_at[t]
                    want = aim(want, target - mid)
                elif t in capped:
                    want, r = cap_elevation(want, arm_cap)
                    for child in capped[t]:
                        ride[child] = r
                elif ride.get(t) is not None:
                    want = ride[t] @ want
                if t == root_name:
                    loc = (rest_head[t] if not root_loc else
                           rest_head[t] + (m.translation - ref_root) * travel)
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

    # Baking is done, so the mesh can come back - everything below this point (the smooth
    # modifier, the save, the glb export) needs a visible, skinned demon.
    for m in _hidden:
        m.hide_viewport = False

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
        "mode": MODE,
        "IK_BODY": IK_BODY if MODE == "ik" else None,
        "method": ("end-effector IK on 4 chains, rotation copy elsewhere" if MODE == "ik"
                   else "world-space rotation delta")
                  + (" + bind-pose match" if BIND_MATCH else ""),
        "BIND_MATCH": BIND_MATCH,
        # every knob, not a subset: four bad bakes came from settings that were carried
        # over from a different character or a different clip type, and this file - the
        # only record of what produced a set - did not record them to be diffed against.
        "IDLE_POSE": IDLE_POSE or None,
        "ROOT_LOC": root_loc,
        "CLAVICLE_DAMP": clav_damp,
        "JAW_CLOSED": jaw_closed,
        "BIND_SKIP": sorted(bind_skip),
        "SOURCE": SOURCE,
        "TARGET": TARGET or None,
        # which layer supplied each knob - env override, profile table, or the built-in
        # default. Without this a manifest says what was set but never why.
        "settings_from": SETTINGS_USED,
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
