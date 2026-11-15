"""Put a weapon mesh in a character's hand: find its grip from its shape, size it to the holder, show it held.

    .venv-bpy/Scripts/python.exe weapon_grip.py <weapon.glb> <body.glb> <roles.json> <out_dir>
        [--length 0.45] [--offset 0.12] [--turn 0] [--hand r] [--save-blend <slot.blend>] [--no-sheet]

weapon.glb  the weapon on its own (the picked TRELLIS mesh), any size and placement
body.glb    the holder's rigged body (its rig_fit), roles.json its bone roles (arm_l / arm_r: hand); or his clips
            .blend (player_clips.py output: the armature with idle / move / attack and his body)
--save-blend  write a pack-ready blend: the weapon joined into one mesh, skinned 100 % to the hand bone, on the
            armature with its clips, the body removed (export_mesh_runtime.py --skin then makes the pack)
--length    the weapon's length as a share of the holder's height (dagger 0.2, sword 0.45, staff 1.0)
--offset    the grip point, as a share of the weapon's length from its handle end (0.12)
--turn      degrees about the hand bone: 0 points the weapon forward, out of the fist
--hand      r | l: which hand (his right: arm_r)

Shape: the long axis is the mesh's first principal direction; the handle end is the thinner of the two ends (mean
distance from the axis over the last 15 % of the length at each end). The weapon is turned so handle -> tip points
forward (the way his feet point), square to the hand bone, then --turn about it; scaled to --length; its grip point
put at the palm (40 % along the hand bone). Parented to the hand bone, so it moves with the hand.
Writes <out_dir>/grip.json (the numbers, for export) and <out_dir>/GRIP_CHECK.png: rest and the cut pose (arms
raised), front / 3/4 / side. Prints GRIP_OK.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pose_render import apply_pose, cut_pose  # noqa: E402

RES = 640
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]


def opt(name, default):
    return type(default)(ARGS[ARGS.index(name) + 1]) if name in ARGS else default


WEAPON, BODY, ROLES, OUT = (os.path.abspath(a) for a in ARGS[:4])
LENGTH, OFFSET, TURN, HAND = opt("--length", 0.45), opt("--offset", 0.12), opt("--turn", 0.0), opt("--hand", "r")
os.makedirs(OUT, exist_ok=True)
roles = json.load(open(ROLES))

SAVE = os.path.abspath(ARGS[ARGS.index("--save-blend") + 1]) if "--save-blend" in ARGS else None
if BODY.lower().endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=BODY)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=BODY)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
arm.data.pose_position = "REST"                     # placed on the rest pose, whatever frame the file was saved at
bpy.context.view_layer.update()
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=WEAPON)
parts = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
for o in bpy.data.objects:
    if o not in before and o.type != "MESH":
        o.select_set(False)
if not parts:
    sys.exit(f"no mesh in {WEAPON}")
for o in parts:                                     # free of the import's empties, world placement kept
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
bpy.context.view_layer.update()


def world_verts(o):
    M = np.array(o.matrix_world)
    V = np.array([v.co[:] for v in o.data.vertices], np.float64)
    return V @ M[:3, :3].T + M[:3, 3]


W = np.concatenate([world_verts(o) for o in parts])
centre = W.mean(0)
_, _, vt = np.linalg.svd(W - centre, full_matrices=False)
axis = vt[0]
t = (W - centre) @ axis
lo, hi = t.min(), t.max()
L = hi - lo
radial = np.linalg.norm((W - centre) - np.outer(t, axis), axis=1)
end_lo = radial[t < lo + 0.15 * L].mean()
end_hi = radial[t > hi - 0.15 * L].mean()
if end_hi < end_lo:                                 # the handle is the thinner end: make the axis run handle -> tip
    axis, t, lo, hi = -axis, -t, -hi, -lo
grip_t = lo + OFFSET * L
near = np.abs(t - grip_t) < 0.03 * L
grip = W[near].mean(0) if near.any() else centre + axis * grip_t

B = world_verts(body)
height = float(np.ptp(B[:, 2]))
scale = LENGTH * height / L
side = roles["arm_r" if HAND == "r" else "arm_l"]
hb = arm.data.bones[side["hand"]]
Mw = arm.matrix_world
head, tail = Mw @ hb.head_local, Mw @ hb.tail_local
h = (tail - head).normalized()
palm = head + (tail - head) * 0.4
# Forward: where his feet point (ankle -> toe bones, flattened), not an assumed axis.
feet = [arm.data.bones[roles[leg]["foot"]] for leg in ("leg_l", "leg_r") if roles.get(leg, {}).get("foot")]
forward = sum(((Mw @ b.tail_local) - (Mw @ b.head_local) for b in feet), Vector((0, 0, 0)))
forward.z = 0
forward = forward.normalized() if forward.length > 1e-6 else Vector((0, -1, 0))
d = (forward - forward.dot(h) * h)
d = d.normalized() if d.length > 1e-6 else Vector((0, 0, 1))
d = Matrix.Rotation(math.radians(TURN), 3, h) @ d
R = Vector(axis.tolist()).rotation_difference(d).to_matrix().to_4x4()
M = Matrix.Translation(palm) @ R @ Matrix.Diagonal((scale, scale, scale, 1)) @ Matrix.Translation(-Vector(grip.tolist()))
for o in parts:
    o.matrix_world = M @ o.matrix_world
bpy.context.view_layer.update()
if SAVE:                                            # one mesh, skinned to the hand bone; the body out
    for o in bpy.data.objects:
        o.select_set(o in parts)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
    weapon = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    g = weapon.vertex_groups.new(name=hb.name)
    g.add(list(range(len(weapon.data.vertices))), 1.0, "REPLACE")
    weapon.parent = arm
    weapon.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = weapon.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not weapon]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    parts = [weapon]
else:
    for o in parts:
        mw = o.matrix_world.copy()
        o.parent = arm
        o.parent_type = "BONE"
        o.parent_bone = hb.name
        bpy.context.view_layer.update()
        o.matrix_world = mw
    bpy.context.view_layer.update()
arm.data.pose_position = "POSE"

info = {"weapon": WEAPON, "body": BODY, "hand_bone": hb.name, "hand": HAND, "length_share": LENGTH,
        "offset": OFFSET, "turn": TURN, "scale": scale, "weapon_length_model": float(L), "holder_height": height,
        "axis_handle_to_tip": axis.tolist(), "grip_point_model": grip.tolist(),
        "handle_end_radius": float(min(end_lo, end_hi)), "tip_end_radius": float(max(end_lo, end_hi)),
        "matrix_world_rest": [list(r) for r in M]}
json.dump(info, open(os.path.join(OUT, "grip.json"), "w"), indent=1)
if SAVE:
    bpy.ops.wm.save_as_mainfile(filepath=SAVE)
    print("SAVED", SAVE, flush=True)
if "--no-sheet" in ARGS:
    print("GRIP_OK", os.path.join(OUT, "grip.json"), flush=True)
    sys.exit(0)

sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "TEXTURE"
sc.display.shading.show_specular_highlight = False
sc.render.resolution_x = sc.render.resolution_y = RES
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.3, 0.3, 0.32)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = height * 1.6
mid = Vector(((B.min(0) + B.max(0)) / 2).tolist())
VIEWS = {"front": (0, -1, 0), "3/4": (-0.7, -0.7, 0), "side": (1, 0, 0) if HAND == "r" else (-1, 0, 0)}
POSES = {"rest": [], "cut pose": cut_pose(roles)}
LABEL = 22
sheet = Image.new("RGB", (RES * len(VIEWS), (RES + LABEL) * len(POSES)), (25, 25, 28))
draw = ImageDraw.Draw(sheet)
frames = os.path.join(OUT, "grip_frames")
os.makedirs(frames, exist_ok=True)
for r, (pname, rots) in enumerate(POSES.items()):
    apply_pose(arm, rots)
    y = r * (RES + LABEL)
    draw.text((6, y + 4), f"{pname} | length {LENGTH} of his height, grip {OFFSET} from the handle end, turn {TURN} deg"
              f"      " + "   ".join(VIEWS), fill=(230, 230, 230))
    for c, (vname, v) in enumerate(VIEWS.items()):
        v = Vector(v).normalized()
        cam.location = mid + v * height * 3
        cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(frames, f"{pname}_{vname}.png".replace(" ", "_").replace("/", ""))
        bpy.ops.render.render(write_still=True)
        sheet.paste(Image.open(sc.render.filepath).convert("RGB"), (c * RES, y + LABEL))
sheet.save(os.path.join(OUT, "GRIP_CHECK.png"))
print("GRIP_OK", os.path.join(OUT, "GRIP_CHECK.png"), flush=True)
