"""Stage 3 (procedural): rigged GLB + bone_roles.json → animated .blend with idle / move / attack.

Runs under ``.venv-bpy`` (Blender as a Python module):

    .venv-bpy/Scripts/python.exe animate_procedural.py <rigged.glb> <bone_roles.json> <out_dir> [params.json]

Every clip is baked frame by frame from sines and eased key poses onto the bones named in
bone_roles.json, so it works on any rig with the same roles. All angles are given about WORLD
axes and converted per bone (a bone's rest roll never matters):

    X  the demon's left-right axis  → rotation = pitch (forward / back)
    Y  front-back axis (he faces -Y) → rotation = roll (wings flap, lateral sway)
    Z  up                            → rotation = yaw / twist

"forward" is resolved per bone by trying the rotation and checking which way the bone tip
moved, so the sign conventions of the rig are irrelevant.

Feet never sink or float: after posing each frame the lowest foot/toe tip is measured and the
root is shifted so it sits exactly on the rest-pose ground line.

Writes <out_dir>/animated.blend (actions on NLA tracks — what render_frames.py reads),
<out_dir>/animated.glb, and <out_dir>/preview/*.png strips for the eye check.
"""
from __future__ import annotations

import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

FPS = 24

# Amplitudes. Degrees unless noted; "%" values are fractions of standing height.
DEFAULT_PARAMS = {
    "idle": {"frames": 48, "spine_pitch": 2.0, "chest_pitch": 1.5, "head_yaw": 3.0, "head_pitch": 1.5,
             "wing_rock": 8.0, "wing_spread": 6.0, "arm_sway": 2.0, "tail_sway": 5.0, "root_bob": 0.005},
    "move": {"frames": 32, "hip_swing": 24.0, "knee_bend": 38.0, "foot_flat": 0.55, "arm_swing": 14.0,
             "elbow_bend": 12.0, "spine_lean": 6.0, "spine_twist": 4.0, "chest_twist": 3.0,
             "wing_spread": 12.0, "wing_flap": 10.0, "tail_sway": 10.0, "root_bob": 0.02, "root_sway": 0.015},
    "attack": {"frames": 30, "t_anticipate": 10, "t_hit": 16, "root_back": 0.04, "root_fwd": 0.12, "root_down": 0.03,
               "wings_up": 30.0, "wings_back": 20.0, "head_back": 10.0, "head_down": 15.0, "spine_back": 8.0,
               "spine_fwd": 20.0, "arms_back": 40.0, "arms_fwd": 70.0, "elbow_fwd": 30.0,
               "front_hip": 30.0, "front_knee": 20.0, "rear_hip": 20.0},
    # swipe: the claw travels an arc through the target. Distances are fractions of standing
    # height, measured from the hand's rest position; timing is in frames.
    "swipe": {"frames": 34, "t_wind": 13, "t_hit": 19, "t_follow": 24, "arm": "arm_r",
              "wind_out": 0.55, "wind_up": 0.45, "wind_back": 0.30,
              "hit_across": -0.75, "hit_down": -0.35, "hit_fwd": 0.55, "arc_lift": 0.35,
              "end_across": -0.95, "end_down": -0.55,
              "hip_twist": 22.0, "torso_lag": 3, "head_lag": 2, "step_in": 0.10,
              "wings_flare": 40.0, "recoil": 0.12},
    # stomp: the foot rises, then falls faster than it rose; the world shakes on contact.
    "stomp": {"frames": 32, "t_lift": 13, "t_drop": 17, "t_settle": 23, "leg": "leg_r",
              "lift_h": 0.34, "lift_fwd": 0.16, "body_rise": 0.05, "body_drop": 0.09,
              "lean_back": 9.0, "lean_fwd": 17.0, "arms_up": 45.0, "arms_slam": 25.0,
              "wings_up": 45.0, "wings_snap": -22.0, "shake": 0.02, "shake_hz": 5.0},
    # kick: a forward drive with the whole leg, hips leading, torso countering
    "kick": {"frames": 30, "t_chamber": 11, "t_hit": 15, "t_retract": 21, "leg": "leg_l",
             "chamber_h": 0.26, "chamber_back": 0.10, "hit_fwd": 0.52, "hit_h": 0.22,
             "hip_drive": 26.0, "torso_counter": 18.0, "arms_counter": 30.0,
             "support_bend": 14.0, "wings_flare": 30.0, "recoil": 0.10},
    # attack2: a big horizontal claw swipe with the right arm, torso twisting into it
    "attack2": {"frames": 32, "t_windup": 10, "t_hit": 16, "arm": "arm_r", "windup_yaw": 55.0, "swipe_yaw": -75.0,
                "windup_lift": 35.0, "elbow_windup": 40.0, "elbow_hit": 10.0, "torso_twist": 25.0, "head_follow": 15.0,
                "root_fwd": 0.06, "root_down": 0.02, "wings_flare": 25.0, "off_arm_back": 25.0,
                "front_hip": 20.0, "rear_hip": 15.0},
    # attack3: lift a leg and stomp; impact = hard root dip, wings and head snap down
    "attack3": {"frames": 30, "t_lift": 12, "t_slam": 16, "leg": "leg_r", "lift_hip": 45.0, "lift_knee": 65.0,
                "root_rise": 0.03, "root_dip": 0.05, "wings_up": 35.0, "wings_down": -15.0, "arms_out": 30.0,
                "spine_back": 6.0, "spine_fwd": 14.0, "head_down": 18.0, "settle_frames": 6},
}


def log(*a):
    print("[animate]", *a, flush=True)


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def smoothstep(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease_in(t, power=3.0):
    """Slow then violently fast — the acceleration of a strike."""
    return min(max(t, 0.0), 1.0) ** power


def ease_out(t, power=3.0):
    return 1.0 - (1.0 - min(max(t, 0.0), 1.0)) ** power


def phase(f, marks):
    """(name, local 0..1) for frame `f` given ordered [(name, end_frame), ...]."""
    start = 0
    for name, end in marks:
        if f <= end:
            return name, (f - start) / max(end - start, 1)
        start = end
    return marks[-1][0], 1.0


def lerp3(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def bez3(p0, p1, p2, t):
    """Quadratic through a control point — an arc, not a straight line."""
    u = 1 - t
    return tuple(u * u * p0[i] + 2 * u * t * p1[i] + t * t * p2[i] for i in range(3))


class Rig:
    def __init__(self, arm, mesh, roles):
        self.arm, self.mesh, self.roles = arm, mesh, roles
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"
        self.height = self._height()
        self.ground = self._lowest_tip()   # rest-pose ground line (world z)
        self._sign_cache = {}
        self.jaw = roles.get("jaw")                       # optional: a jaw bone + its closed angle
        self.jaw_closed = float(roles.get("jaw_closed_deg", 0.0))

    def _height(self):
        mw = self.mesh.matrix_world
        verts = self.mesh.data.vertices
        zs = [(mw @ verts[i].co).z for i in range(0, len(verts), 50)]
        return max(zs) - min(zs)

    def pb(self, name):
        return self.arm.pose.bones[name]

    def role(self, *path):
        node = self.roles
        for p in path:
            node = node[p]
        return node

    def tip_world(self, name):
        return self.arm.matrix_world @ self.pb(name).tail

    def reset(self):
        for pb in self.arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)

    def _local_axis(self, name, world_axis):
        m = (self.arm.matrix_world @ self.arm.data.bones[name].matrix_local).to_3x3()
        return (m.inverted() @ Vector(world_axis)).normalized()

    def rotate(self, name, world_axis, deg):
        """Compose a rotation of `deg` about a WORLD axis onto the bone (rest-frame local)."""
        if abs(deg) < 1e-6:
            return
        q = Quaternion(self._local_axis(name, world_axis), math.radians(deg))
        pb = self.pb(name)
        pb.rotation_quaternion = pb.rotation_quaternion @ q

    def translate(self, name, world_vec):
        m = (self.arm.matrix_world @ self.arm.data.bones[name].matrix_local).to_3x3()
        pb = self.pb(name)
        pb.location = pb.location + (m.inverted() @ Vector(world_vec))

    def forward_sign(self, name, world_axis, want):
        """+1/-1 such that rotate(name, axis, sign*10°) moves the bone tip toward `want`
        (a world direction). Cached per (bone, axis)."""
        key = (name, tuple(world_axis), tuple(want))
        if key in self._sign_cache:
            return self._sign_cache[key]
        saved = self.pb(name).rotation_quaternion.copy()
        before = self.tip_world(name).copy()
        self.rotate(name, world_axis, 10.0)
        bpy.context.view_layer.update()
        after = self.tip_world(name)
        self.pb(name).rotation_quaternion = saved
        bpy.context.view_layer.update()
        s = 1.0 if (after - before).dot(Vector(want)) > 0 else -1.0
        self._sign_cache[key] = s
        return s

    # semantic helpers -------------------------------------------------------------------
    def pitch(self, name, deg, forward=(0, -1, 0)):
        """+deg tips the bone tip toward `forward` (default: toward the front of the demon)."""
        self.rotate(name, (1, 0, 0), deg * self.forward_sign(name, (1, 0, 0), forward))

    def yaw(self, name, deg):
        self.rotate(name, (0, 0, 1), deg)

    def roll_back(self, name, deg):
        """+deg sweeps the bone tip toward +Y (behind the demon): wings folding back."""
        self.rotate(name, (0, 1, 0), deg * self.forward_sign(name, (0, 1, 0), (0, 1, 0)))

    def lift(self, name, deg):
        """+deg raises the bone tip (world +Z) — used for wings-up and leg lift checks."""
        self.rotate(name, (0, 1, 0), deg * self.forward_sign(name, (0, 1, 0), (0, 0, 1)))

    def set_jaw(self, open_frac):
        """0 = shut (teeth touching), 1 = as modelled (fully open). No-op without a jaw bone."""
        if not self.jaw or self.jaw_closed <= 0:
            return
        open_frac = min(max(open_frac, 0.0), 1.0)
        deg = self.jaw_closed * (1.0 - open_frac)
        self.rotate(self.jaw, (1, 0, 0), deg * self.forward_sign(self.jaw, (1, 0, 0), (0, 0, 1)))   # raise the chin

    # --- reach: aim a limb at a world point instead of rotating one bone ----------------
    def reach(self, chain, target, iterations=6, twist_axis=(0, 0, 1)):
        """Point a bone chain's tip at `target` (world) — CCD inverse kinematics.

        Rotating a shoulder by N degrees makes a limb wave; a strike is a *path the claw
        travels*. Keyframing that path and solving the arm each frame is what turns a
        nudge into a swipe: the elbow and shoulder fall out of where the hand must be.
        """
        names = [n for n in chain if n in self.arm.pose.bones]
        if not names:
            return
        tgt = Vector(target)
        for _ in range(iterations):
            for name in reversed(names):          # tip-most bone first (CCD)
                bpy.context.view_layer.update()
                pivot = self.arm.matrix_world @ self.pb(name).head
                tip = self.tip_world(names[-1])
                a = (tip - pivot)
                b = (tgt - pivot)
                if a.length < 1e-6 or b.length < 1e-6:
                    continue
                a.normalize(); b.normalize()
                axis = a.cross(b)
                if axis.length < 1e-6:
                    continue
                ang = math.acos(max(-1.0, min(1.0, a.dot(b))))
                if abs(ang) < 1e-5:
                    continue
                m = (self.arm.matrix_world @ self.arm.data.bones[name].matrix_local).to_3x3()
                local_axis = (m.inverted() @ axis.normalized()).normalized()
                pb = self.pb(name)
                pb.rotation_quaternion = pb.rotation_quaternion @ Quaternion(local_axis, ang)
        bpy.context.view_layer.update()

    def rest_tip(self, name):
        """Where a bone's tip sits in the rest pose (cached) — the anchor for reach paths."""
        if not hasattr(self, "_rest_tips"):
            self._rest_tips = {}
        if name not in self._rest_tips:
            saved = {pb.name: (pb.rotation_quaternion.copy(), pb.location.copy()) for pb in self.arm.pose.bones}
            self.reset()
            bpy.context.view_layer.update()
            self._rest_tips[name] = self.tip_world(name).copy()
            for pb in self.arm.pose.bones:
                q, loc = saved[pb.name]
                pb.rotation_quaternion, pb.location = q, loc
            bpy.context.view_layer.update()
        return self._rest_tips[name]

    def ground_feet(self):
        """Shift the root so the lowest foot/toe tip sits on the rest ground line."""
        bpy.context.view_layer.update()
        tips = []
        for leg in ("leg_l", "leg_r"):
            for part in ("foot", "toe", "ankle"):
                tips.append(self.tip_world(self.role(leg, part)).z)
        dz = self.ground - min(tips)
        self.translate(self.role("root"), (0, 0, dz))

    def _lowest_tip(self):
        bpy.context.view_layer.update()
        return min(self.tip_world(self.role(leg, part)).z for leg in ("leg_l", "leg_r") for part in ("foot", "toe", "ankle"))

    def key_all(self, frame):
        for pb in self.arm.pose.bones:
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            pb.keyframe_insert("location", frame=frame)


# ------------------------------------------------------------------------------ recipes
def pose_idle(r: Rig, P, f, N):
    ps = 2 * math.pi * f / N
    R = r.roles
    r.pitch(R["spine"], P["spine_pitch"] * math.sin(ps))
    r.pitch(R["chest"], P["chest_pitch"] * math.sin(ps))
    r.yaw(R["head"], P["head_yaw"] * math.sin(ps / 2))
    r.pitch(R["head"], P["head_pitch"] * math.sin(ps + 0.7))
    for side, sgn in (("wing_l", 1), ("wing_r", -1)):
        r.roll_back(R[side]["arm"], P["wing_spread"] + P["wing_rock"] * math.sin(ps))
        r.roll_back(R[side]["fan"], 0.5 * P["wing_rock"] * math.sin(ps - 0.6))
    for side, sgn in (("arm_l", 1), ("arm_r", -1)):
        r.pitch(R[side]["shoulder"], sgn * P["arm_sway"] * math.sin(ps))
    for i, tb in enumerate(R["tail"]):
        r.rotate(tb, (0, 0, 1), P["tail_sway"] * math.sin(ps - 0.5 * i))
    r.translate(R["root"], (0, 0, P["root_bob"] * r.height * math.sin(ps)))
    r.set_jaw(0.10 + 0.06 * math.sin(ps))                   # breathing: barely ajar


def pose_move(r: Rig, P, f, N):
    ph = 2 * math.pi * f / N
    R = r.roles
    # legs: two-beat stomp. leg_l swings with sin(ph), leg_r opposite.
    for leg, phase in (("leg_l", 0.0), ("leg_r", math.pi)):
        s = math.sin(ph + phase)
        c = math.cos(ph + phase)
        r.pitch(R[leg]["hip"], P["hip_swing"] * s)
        knee = P["knee_bend"] * max(0.0, c) ** 1.4          # bends while the leg swings forward
        r.pitch(R[leg]["knee"], -knee)
        r.pitch(R[leg]["foot"], -P["foot_flat"] * (P["hip_swing"] * s - knee))
    # weight: dip on each contact (twice per cycle), sway toward the stance leg
    r.translate(R["root"], (P["root_sway"] * r.height * math.sin(ph), 0,
                            -P["root_bob"] * r.height * (0.5 - 0.5 * math.cos(2 * ph))))
    r.pitch(R["spine"], P["spine_lean"])
    r.yaw(R["spine"], P["spine_twist"] * math.sin(ph))
    r.yaw(R["chest"], P["chest_twist"] * math.sin(ph))
    r.yaw(R["head"], -(P["spine_twist"] + P["chest_twist"]) * math.sin(ph))   # keep the face forward
    for side, sgn in (("arm_l", -1), ("arm_r", 1)):                                # opposite to same-side leg
        r.pitch(R[side]["shoulder"], sgn * P["arm_swing"] * math.sin(ph))
        r.pitch(R[side]["elbow"], P["elbow_bend"] + 0.4 * P["arm_swing"] * max(0.0, sgn * math.sin(ph)))
    for side in ("wing_l", "wing_r"):
        r.roll_back(R[side]["arm"], P["wing_spread"] + P["wing_flap"] * math.sin(ph))
        r.roll_back(R[side]["fan"], 0.5 * P["wing_flap"] * math.sin(ph - 0.8))
    for i, tb in enumerate(R["tail"]):
        r.rotate(tb, (0, 0, 1), P["tail_sway"] * math.sin(ph - 0.6 * i))
    r.set_jaw(0.15)


def pose_attack(r: Rig, P, f, N):
    R = r.roles
    ta, th = P["t_anticipate"], P["t_hit"]
    if f <= ta:
        a, b = 0.0, smoothstep(f / ta)                          # rest -> anticipation
        w_ant, w_hit = b, 0.0
    elif f <= th:
        b = smoothstep((f - ta) / (th - ta))                    # anticipation -> hit (fast)
        w_ant, w_hit = 1 - b, b
    else:
        b = smoothstep((f - th) / (N - th))                     # hit -> rest
        w_ant, w_hit = 0.0, 1 - b
    H = r.height
    # root
    r.translate(R["root"], (0, w_ant * P["root_back"] * H - w_hit * P["root_fwd"] * H, -w_hit * P["root_down"] * H))
    # torso + head
    r.pitch(R["spine"], -w_ant * P["spine_back"] + w_hit * P["spine_fwd"])
    r.pitch(R["head"], -w_ant * P["head_back"] + w_hit * P["head_down"])
    # arms: raise back, then swing forward and bend
    for side in ("arm_l", "arm_r"):
        r.pitch(R[side]["shoulder"], -w_ant * P["arms_back"] + w_hit * P["arms_fwd"])
        r.pitch(R[side]["elbow"], w_hit * P["elbow_fwd"])
    # wings: up on anticipation, sweep back on the hit
    for side in ("wing_l", "wing_r"):
        r.lift(R[side]["arm"], w_ant * P["wings_up"])
        r.roll_back(R[side]["arm"], w_hit * P["wings_back"])
    # legs: weight to the rear leg, front leg steps into the hit
    r.pitch(R["leg_l"]["hip"], w_hit * P["front_hip"] - w_ant * 0.3 * P["front_hip"])
    r.pitch(R["leg_l"]["knee"], -w_hit * P["front_knee"])
    r.pitch(R["leg_r"]["hip"], -w_ant * P["rear_hip"] - w_hit * 0.5 * P["rear_hip"])
    r.set_jaw(0.2 * w_ant + w_hit)                          # roars open on the lunge


def pose_attack2(r: Rig, P, f, N):
    """Claw swipe: wind the arm back and up, sweep it across the body, recover."""
    R = r.roles
    tw, th = P["t_windup"], P["t_hit"]
    if f <= tw:
        w_wind, w_hit = smoothstep(f / tw), 0.0
    elif f <= th:
        b = smoothstep((f - tw) / (th - tw)); w_wind, w_hit = 1 - b, b
    else:
        b = smoothstep((f - th) / (N - th)); w_wind, w_hit = 0.0, 1 - b
    H = r.height
    arm, other = P["arm"], ("arm_l" if P["arm"] == "arm_r" else "arm_r")
    across = (1, 0, 0) if arm == "arm_r" else (-1, 0, 0)          # swipe direction: toward the other side
    away = tuple(-c for c in across)
    sh, el = R[arm]["shoulder"], R[arm]["elbow"]
    # wind-up: arm out to its own side and up, elbow bent; hit: swept across the body, elbow straighter
    r.rotate(sh, (0, 0, 1), (w_wind * P["windup_yaw"] + w_hit * P["swipe_yaw"]) * r.forward_sign(sh, (0, 0, 1), across))
    r.lift(sh, w_wind * P["windup_lift"] - w_hit * 0.4 * P["windup_lift"])
    r.pitch(el, w_wind * P["elbow_windup"] + w_hit * P["elbow_hit"])
    # torso winds opposite, then twists into the swipe; head follows the claw
    r.yaw(R["spine"], (-w_wind * 0.5 + w_hit) * P["torso_twist"] * (1 if across[0] > 0 else -1))
    r.yaw(R["chest"], (-w_wind * 0.3 + w_hit * 0.6) * P["torso_twist"] * (1 if across[0] > 0 else -1))
    r.yaw(R["head"], w_hit * P["head_follow"] * (1 if across[0] > 0 else -1))
    r.pitch(R["spine"], w_hit * 8.0)
    # off arm counterbalances, wings flare on the hit, weight steps in
    r.pitch(R[other]["shoulder"], -w_hit * P["off_arm_back"])
    for side in ("wing_l", "wing_r"):
        r.lift(R[side]["arm"], w_hit * P["wings_flare"])
    r.translate(R["root"], (0, -w_hit * P["root_fwd"] * H, -w_hit * P["root_down"] * H))
    r.pitch(R["leg_l"]["hip"], w_hit * P["front_hip"])
    r.pitch(R["leg_r"]["hip"], -w_hit * P["rear_hip"])
    r.set_jaw(0.3 * w_wind + 0.9 * w_hit)


def pose_attack3(r: Rig, P, f, N):
    """Stomp: raise a leg, slam it down, whole body drops on impact, then settle."""
    R = r.roles
    tl, ts, st = P["t_lift"], P["t_slam"], P["settle_frames"]
    if f <= tl:
        w_lift, w_impact = smoothstep(f / tl), 0.0
    elif f <= ts:
        b = (f - tl) / (ts - tl); w_lift, w_impact = 1 - b * b, 0.0        # fast fall (ease-in)
    elif f <= ts + st:
        w_lift, w_impact = 0.0, 1 - smoothstep((f - ts) / st)              # hard dip then recover
    else:
        w_lift, w_impact = 0.0, 0.0
    H = r.height
    leg, plant = P["leg"], ("leg_l" if P["leg"] == "leg_r" else "leg_r")
    r.pitch(R[leg]["hip"], w_lift * P["lift_hip"])
    r.pitch(R[leg]["knee"], -w_lift * P["lift_knee"])
    r.pitch(R[plant]["knee"], -w_impact * 12.0)                            # planted leg takes the shock
    r.translate(R["root"], (0, 0, w_lift * P["root_rise"] * H - w_impact * P["root_dip"] * H))
    r.pitch(R["spine"], -w_lift * P["spine_back"] + w_impact * P["spine_fwd"])
    r.pitch(R["head"], -w_lift * 0.5 * P["spine_back"] + w_impact * P["head_down"])
    for side in ("arm_l", "arm_r"):
        r.lift(R[side]["shoulder"], w_lift * P["arms_out"] + w_impact * 0.5 * P["arms_out"])
    for side in ("wing_l", "wing_r"):
        r.lift(R[side]["arm"], w_lift * P["wings_up"] + w_impact * P["wings_down"])
    r.set_jaw(0.3 * w_lift + w_impact)                      # roar on the impact


def pose_swipe(r, P, f, N):
    """Bear swipe: the claw follows an arc - out/up/back, through the target, past the far hip.

    Not "rotate the shoulder N degrees": the hand is keyed to travel a curve and the arm is
    solved to reach it, so the strike has a path and a direction. Contact is 4-6 frames of
    the whole 34, the wind-up is slow, the follow-through overshoots and settles.
    """
    R = r.roles
    H = r.height
    arm = P["arm"]
    other = "arm_l" if arm == "arm_r" else "arm_r"
    side = 1.0 if arm == "arm_r" else -1.0
    chain = [R[arm]["shoulder"], R[arm]["elbow"], R[arm]["wrist"]]
    rest = r.rest_tip(R[arm]["wrist"])
    marks = [("wind", P["t_wind"]), ("hit", P["t_hit"]), ("follow", P["t_follow"]), ("settle", N)]
    name, u = phase(f, marks)

    wind = (rest[0] - side * P["wind_out"] * H, rest[1] + P["wind_back"] * H, rest[2] + P["wind_up"] * H)
    thru = (rest[0] + side * P["hit_across"] * H, rest[1] - P["hit_fwd"] * H, rest[2] + P["hit_down"] * H)
    ctrl = (rest[0], rest[1] - P["hit_fwd"] * H * 1.3, rest[2] + P["arc_lift"] * H)
    end = (rest[0] + side * P["end_across"] * H, rest[1] - P["hit_fwd"] * H * 0.4, rest[2] + P["end_down"] * H)

    def body_at(fr):
        n2, u2 = phase(fr, marks)
        return {"wind": -0.35 * u2, "hit": -0.35 + 1.35 * ease_in(u2, 2.0),
                "follow": 1.0 - 0.3 * u2, "settle": 0.7 * (1 - u2)}[n2]

    if name == "wind":
        target, snap = lerp3(rest, wind, smoothstep(u)), 0.0
    elif name == "hit":
        target, snap = bez3(wind, ctrl, thru, ease_in(u, 2.4)), ease_in(u, 3.0)
    elif name == "follow":
        target, snap = lerp3(thru, end, ease_out(u)), 1.0 - 0.6 * u
    else:
        target, snap = lerp3(end, rest, smoothstep(u)), 0.4 * (1 - u)
    body = body_at(f)

    r.yaw(R["spine"], side * P["hip_twist"] * body)
    r.yaw(R["chest"], side * P["hip_twist"] * 0.8 * body_at(max(f - P["torso_lag"], 0)))
    r.yaw(R["head"], side * P["hip_twist"] * 0.5 * body_at(max(f - P["torso_lag"] - P["head_lag"], 0)))
    r.pitch(R["spine"], 10.0 * max(body, 0.0))
    r.translate(R["root"], (side * P["step_in"] * H * 0.4 * max(body, 0.0),
                            -P["step_in"] * H * max(body, 0.0) + P["recoil"] * H * max(-body, 0.0), 0))
    r.pitch(R[other]["shoulder"], -35.0 * max(body, 0.0))
    for w in ("wing_l", "wing_r"):
        r.lift(R[w]["arm"], P["wings_flare"] * max(body, 0.0) * 0.6 + 20.0 * snap)
    r.set_jaw(0.25 + 0.75 * snap)
    for i, tb in enumerate(R["tail"]):
        r.rotate(tb, (0, 0, 1), -side * 18.0 * body_at(max(f - P["torso_lag"] - 2 - i, 0)))
    r.reach(chain, target)


def pose_stomp(r, P, f, N):
    """Raise the foot high, drop it faster than it rose, shake everything on contact."""
    R = r.roles
    H = r.height
    leg = P["leg"]
    plant = "leg_l" if leg == "leg_r" else "leg_r"
    chain = [R[leg]["hip"], R[leg]["knee"], R[leg]["ankle"]]
    rest = r.rest_tip(R[leg]["ankle"])
    name, u = phase(f, [("lift", P["t_lift"]), ("drop", P["t_drop"]), ("settle", P["t_settle"]), ("rec", N)])

    top = (rest[0], rest[1] - P["lift_fwd"] * H, rest[2] + P["lift_h"] * H)
    if name == "lift":
        target, rise, impact = lerp3(rest, top, smoothstep(u)), smoothstep(u), 0.0
    elif name == "drop":
        target, rise, impact = lerp3(top, rest, ease_in(u, 2.6)), 1 - ease_in(u, 2.6), 0.0
    elif name == "settle":
        target, rise, impact = rest, 0.0, 1.0 - smoothstep(u)
    else:
        target, rise, impact = rest, 0.0, 0.0

    shake = math.sin(f * P["shake_hz"]) * P["shake"] * H * impact
    r.translate(R["root"], (shake, 0, P["body_rise"] * H * rise - P["body_drop"] * H * impact))
    r.pitch(R["spine"], -P["lean_back"] * rise + P["lean_fwd"] * impact)
    r.pitch(R["chest"], -P["lean_back"] * 0.5 * rise + P["lean_fwd"] * 0.6 * impact)
    r.pitch(R["head"], -P["lean_back"] * 0.4 * rise + P["lean_fwd"] * 1.1 * impact)
    r.pitch(R[plant]["knee"], -16.0 * impact)
    for a in ("arm_l", "arm_r"):
        r.lift(R[a]["shoulder"], P["arms_up"] * rise - P["arms_slam"] * impact)
    for w in ("wing_l", "wing_r"):
        r.lift(R[w]["arm"], P["wings_up"] * rise + P["wings_snap"] * impact)
    r.set_jaw(0.2 * rise + impact)
    for tb in R["tail"]:
        r.rotate(tb, (1, 0, 0), 20.0 * rise - 25.0 * impact)
    r.reach(chain, target)


def pose_kick(r, P, f, N):
    """Chamber the knee, drive the foot forward through the target, snap it back."""
    R = r.roles
    H = r.height
    leg = P["leg"]
    support = "leg_l" if leg == "leg_r" else "leg_r"
    side = 1.0 if leg == "leg_r" else -1.0
    chain = [R[leg]["hip"], R[leg]["knee"], R[leg]["ankle"]]
    rest = r.rest_tip(R[leg]["ankle"])
    name, u = phase(f, [("chamber", P["t_chamber"]), ("hit", P["t_hit"]), ("retract", P["t_retract"]), ("settle", N)])

    cham = (rest[0], rest[1] + P["chamber_back"] * H, rest[2] + P["chamber_h"] * H)
    strike = (rest[0], rest[1] - P["hit_fwd"] * H, rest[2] + P["hit_h"] * H)
    if name == "chamber":
        target, drive = lerp3(rest, cham, smoothstep(u)), -0.3 * u
    elif name == "hit":
        target, drive = lerp3(cham, strike, ease_in(u, 2.2)), -0.3 + 1.3 * ease_in(u, 2.0)
    elif name == "retract":
        target, drive = lerp3(strike, cham, ease_out(u)), 1.0 - 0.7 * u
    else:
        target, drive = lerp3(cham, rest, smoothstep(u)), 0.3 * (1 - u)

    r.pitch(R["spine"], -P["torso_counter"] * max(drive, 0.0) + 6.0 * max(-drive, 0.0))
    r.pitch(R["chest"], -P["torso_counter"] * 0.6 * max(drive, 0.0))
    r.pitch(R["head"], P["torso_counter"] * 0.35 * max(drive, 0.0))
    r.yaw(R["spine"], side * P["hip_drive"] * 0.4 * max(drive, 0.0))
    r.pitch(R[support]["knee"], -P["support_bend"] * abs(drive))
    for a in ("arm_l", "arm_r"):
        r.pitch(R[a]["shoulder"], -P["arms_counter"] * max(drive, 0.0))
        r.pitch(R[a]["elbow"], 25.0 * max(drive, 0.0))
    for w in ("wing_l", "wing_r"):
        r.lift(R[w]["arm"], P["wings_flare"] * max(drive, 0.0))
    r.translate(R["root"], (0, -P["recoil"] * H * max(drive, 0.0) * 0.3, 0))
    r.set_jaw(0.2 + 0.6 * max(drive, 0.0))
    for tb in R["tail"]:
        r.rotate(tb, (1, 0, 0), 25.0 * max(drive, 0.0))
    r.reach(chain, target)


RECIPES = {"idle": pose_idle, "move": pose_move, "attack": pose_attack,
           "attack2": pose_attack2, "attack3": pose_attack3,
           "swipe": pose_swipe, "stomp": pose_stomp, "kick": pose_kick}
LOOPS = {"idle", "move"}


# ------------------------------------------------------------------------------ driver
def bake(r: Rig, name, P):
    N = int(P["frames"])
    action = bpy.data.actions.new(name)
    ad = r.arm.animation_data or r.arm.animation_data_create()
    ad.action = action
    if hasattr(action, "slots") and hasattr(ad, "action_slot"):
        slot = action.slots.new(id_type="OBJECT", name=name) if len(action.slots) == 0 else action.slots[0]
        ad.action_slot = slot
    for f in range(N + 1):                       # frame N == frame 0 for the loops
        r.reset()
        RECIPES[name](r, P, f % N if name in LOOPS else min(f, N), N)
        r.ground_feet()
        r.key_all(f + 1)
    for fc in action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    action.use_frame_range = True
    action.frame_start, action.frame_end = 1, N + 1
    action.use_cyclic = name in LOOPS
    action.use_fake_user = True                  # keep it listed in Blender's action dropdown
    ad.action = None
    track = ad.nla_tracks.new()
    track.name = name
    track.strips.new(name, 1, action)
    track.mute = True
    log(f"baked {name}: {N} frames")
    return action


def preview(r: Rig, actions, out_dir):
    """Front (s) and side (e) strips per clip, 6 frames each, for the eye check."""
    from PIL import Image, ImageDraw
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.eevee.taa_render_samples = 8
    sc.render.resolution_x = sc.render.resolution_y = 360
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    for s in r.mesh.material_slots:
        b = next(n for n in s.material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        for l in list(b.inputs["Metallic"].links):
            s.material.node_tree.links.remove(l)
        b.inputs["Metallic"].default_value = 0
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 1.2
    for name, loc, energy in (("key", (-2, -3, 3), 5.0), ("fill", (3, -3, 1), 2.5)):
        L = bpy.data.lights.new(name, "SUN"); L.energy = energy
        o = bpy.data.objects.new(name, L); sc.collection.objects.link(o); o.location = loc
        o.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.25, 0.25, 0.28, 1)
    ad = r.arm.animation_data
    pv = os.path.join(out_dir, "preview")
    os.makedirs(pv, exist_ok=True)
    tiles = []
    for name, action in actions.items():
        N = int(action.frame_end) - 1
        frames = [1 + round(i * N / 6) for i in range(6)]
        ad.action = action
        if hasattr(action, "slots") and hasattr(ad, "action_slot") and len(action.slots):
            ad.action_slot = action.slots[0]
        for view, yaw in (("s", 0.0), ("e", math.radians(90))):
            cam.location = (3 * math.sin(yaw), -3 * math.cos(yaw), 0)
            cam.rotation_euler = (math.radians(90), 0, yaw)
            for i, fr in enumerate(frames):
                sc.frame_set(fr)
                p = os.path.join(pv, f"{name}_{view}_{i}.png")
                sc.render.filepath = p
                bpy.ops.render.render(write_still=True)
                tiles.append((name, view, i, p))
        ad.action = None
    T = 360
    rows = [(n, v) for n in actions for v in ("s", "e")]
    sheet = Image.new("RGB", (6 * T, len(rows) * T), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for ri, (n, v) in enumerate(rows):
        for i in range(6):
            p = os.path.join(pv, f"{n}_{v}_{i}.png")
            sheet.paste(Image.open(p).convert("RGB"), (i * T, ri * T))
        d.text((8, ri * T + 8), f"{n} [{v}]", fill=(255, 255, 0))
    sheet.save(os.path.join(out_dir, "PREVIEW_SHEET.png"))
    log("preview sheet", os.path.join(out_dir, "PREVIEW_SHEET.png"))


def main():
    rigged, roles_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    params = deep_merge(DEFAULT_PARAMS, json.load(open(sys.argv[4])) if len(sys.argv) > 4 else {})
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    roles = json.load(open(roles_path))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(rigged))
    # the glTF importer parks bone display shapes (an Icosphere) in "glTF_not_exported"; it is a
    # real mesh object and would be framed and shadowed by the renderer -- remove it
    for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(coll)
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
    bpy.context.scene.render.fps = FPS
    r = Rig(arm, mesh, roles)
    log("height", round(r.height, 3), "ground z", round(r.ground, 3), "bones", len(arm.pose.bones))
    wanted = os.environ.get("ANIM_CLIPS")
    names = wanted.split(",") if wanted else ["idle", "move", "attack", "attack2", "attack3",
                                              "swipe", "stomp", "kick"]
    actions = {name: bake(r, name, params[name]) for name in names}
    r.reset()
    # pack the texture and save
    for img in bpy.data.images:
        if img.users and not img.packed_file:
            try:
                img.pack()
            except RuntimeError:
                pass
    blend = os.path.join(out_dir, "animated.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    log("saved", blend)
    try:
        bpy.ops.object.select_all(action="DESELECT"); mesh.select_set(True); arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "animated.glb"), use_selection=True,
                                  export_animations=True, export_animation_mode="ACTIONS")
        log("exported animated.glb")
    except Exception as e:  # the .blend is the source of truth; the glb is a courtesy
        log("glb export skipped:", e)
    preview(r, actions, out_dir)
    json.dump(params, open(os.path.join(out_dir, "params_used.json"), "w"), indent=1)
    log("DONE")


if __name__ == "__main__":
    main()
