"""SAM3 face masks → vertex groups on the rigged mesh → a jaw bone. Runs under .venv-bpy.

    .venv-bpy/Scripts/python.exe face_parts.py <rigged.glb> <masks_dir> <elev_deg> <out_dir>

<masks_dir> holds the .npy boolean masks written by the SAM3 batch (scratch sam_face.py) for the
render made by head_ref_elev.py at <elev_deg> (2048², head camera). Uses project_paint.render_uv_id
to map every mask pixel back to the atlas texel it shows, then to the vertices that own that texel.

Jaw: the 'lower_jaw' mask gives the visible jaw; its 3D extent (z below the hinge, in front of the
hinge plane) collects the underside the camera cannot see. Hinge = the highest jaw vertices at each
side; bone head = their midpoint, tail = the chin tip. Weights fade to the head bone over the top
15 % of the jaw so the cheeks don't tear.

Writes <out_dir>/rigged_jaw.glb, <out_dir>/face_groups.json (vertex counts), <out_dir>/jaw_*.png.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_paint as pp  # noqa: E402

RIGGED, MASKS, ELEV, OUT = sys.argv[1], sys.argv[2], float(sys.argv[3]), os.path.abspath(sys.argv[4])
SIDE_MASKS, SIDE_YAW = (sys.argv[5], float(sys.argv[6])) if len(sys.argv) > 6 else (None, 90.0)
os.makedirs(OUT, exist_ok=True)


def best_mask(name):
    files = sorted(glob.glob(os.path.join(MASKS, f"{name}_0_*.npy")))
    if not files:
        raise SystemExit(f"no mask for {name} in {MASKS}")
    return np.load(files[0])                     # top-scoring instance, (H, W) bool, top-down rows


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(RIGGED))
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
sc = bpy.context.scene

# --- pixels -> atlas texels: same camera as the SAM render ------------------------------------
res = best_mask("lower_jaw").shape[0]
cam = pp.head_camera(sc, ELEV, res)


def aim(elev_deg, yaw_deg):
    e, a = math.radians(elev_deg), math.radians(yaw_deg)
    cam.location = (pp.HEAD_CENTRE.x + pp.R * math.sin(a) * math.cos(e), pp.HEAD_CENTRE.y - pp.R * math.cos(a) * math.cos(e),
                    pp.HEAD_CENTRE.z + pp.R * math.sin(e))
    cam.rotation_euler = (math.radians(90) - e, 0, a)
def render_pos_id(path):
    """Emission = world position (x,y,z), alpha = coverage. 32-bit EXR, no AA."""
    mat = bpy.data.materials.new("posid"); mat.use_nodes = True; nt = mat.node_tree
    for nd in list(nt.nodes): nt.nodes.remove(nd)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    # emission cannot be negative: encode (P + 1) * 0.5, decode below
    enc = nt.nodes.new("ShaderNodeVectorMath"); enc.operation = "MULTIPLY_ADD"
    enc.inputs[1].default_value = (0.5, 0.5, 0.5); enc.inputs[2].default_value = (0.5, 0.5, 0.5)
    nt.links.new(geo.outputs["Position"], enc.inputs[0]); nt.links.new(enc.outputs[0], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])
    saved = [s.material for s in mesh.material_slots]
    for s in mesh.material_slots: s.material = mat
    sc.render.engine = "BLENDER_EEVEE_NEXT"; sc.eevee.taa_render_samples = 1; sc.render.filter_size = 0.0
    sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "OPEN_EXR"; sc.render.image_settings.color_depth = "32"
    sc.render.image_settings.color_mode = "RGBA"; sc.render.image_settings.exr_codec = "NONE"
    sc.render.filepath = path; bpy.ops.render.render(write_still=True)
    for s, m in zip(mesh.material_slots, saved): s.material = m
    im = bpy.data.images.load(path); im.colorspace_settings.name = "Non-Color"
    w, h = im.size; px = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4); bpy.data.images.remove(im)
    px[..., :3] = px[..., :3] * 2.0 - 1.0
    return px
aim(ELEV, 0.0)
idpx = render_pos_id(os.path.join(OUT, "pos_id.exr"))   # bottom-up rows, xyz world
pp.log("pos-id", idpx.shape)
idpx_side = None
if SIDE_MASKS:
    aim(0.0, SIDE_YAW)
    idpx_side = render_pos_id(os.path.join(OUT, "pos_id_side.exr"))
    aim(ELEV, 0.0)

me = mesh.data
n = len(me.vertices)
mw = np.array(mesh.matrix_world)
co = np.empty(n * 3, np.float32); me.vertices.foreach_get("co", co)
V = (np.c_[co.reshape(-1, 3), np.ones(n)] @ mw.T)[:, :3]
VOX = 0.004                                              # ~ one texel of surface at this scale
vkey = np.floor(V / VOX).astype(np.int64)


def mask_points(mask2d, pos=None):
    pos = idpx if pos is None else pos
    m = np.flipud(mask2d) & (pos[..., 3] > 0.5)
    return pos[..., :3][m]


def verts_from_mask(mask2d, grow=1, pos=None):
    """mask (top-down) -> world points of those pixels -> vertices within `grow` voxels."""
    P = mask_points(mask2d, pos)
    keys = set(map(tuple, np.floor(P / VOX).astype(np.int64)))
    if grow:
        ks = np.array(list(keys)); grown = set()
        for dx in range(-grow, grow + 1):
            for dy in range(-grow, grow + 1):
                for dz in range(-grow, grow + 1):
                    grown.update(map(tuple, ks + np.array([dx, dy, dz])))
        keys = grown
    sel = np.fromiter((tuple(k) in keys for k in vkey), bool, n)
    return np.nonzero(sel)[0]


groups = {}
for part in ("lower_jaw", "eye", "teeth", "horn"):
    try:
        idx = verts_from_mask(best_mask(part))
    except SystemExit:
        continue
    vg = mesh.vertex_groups.new(name=f"face_{part}")
    vg.add(idx.tolist(), 1.0, "REPLACE")
    groups[part] = int(len(idx))
pp.log("visible-mask groups", groups)

# --- jaw: weights by distance to the SAM jaw surface (front cloud + side cloud), no box ---------
from mathutils.kdtree import KDTree
vis = verts_from_mask(best_mask("lower_jaw"))
J = V[vis]
z_top = np.percentile(J[:, 2], 97)
cloud = mask_points(best_mask("lower_jaw"))
if idpx_side is not None:
    union = np.zeros_like(best_mask("lower_jaw"))
    for sm in sorted(glob.glob(os.path.join(SIDE_MASKS, "jaw_*_*.npy"))):
        union |= np.load(sm)
    SJ = mask_points(union, idpx_side)
    SJ = SJ[(SJ[:, 2] >= J[:, 2].min() - 0.01) & (SJ[:, 2] <= z_top + 0.06)]
    SJm = SJ.copy(); SJm[:, 0] *= -1                      # mirror the side cloud to the other cheek
    cloud = np.concatenate([cloud, SJ, SJm])
    y_hinge = np.percentile(SJ[:, 1], 97)
    rear = SJ[SJ[:, 1] > np.percentile(SJ[:, 1], 80)]
    z_top = max(z_top, np.percentile(rear[:, 2], 90))
    pp.log("side jaw points", len(SJ), "y range %.3f..%.3f" % (SJ[:, 1].min(), SJ[:, 1].max()))
else:
    top_band = J[J[:, 2] > np.percentile(J[:, 2], 85)]
    y_hinge = np.percentile(top_band[:, 1], 90)
cloud = cloud[::3]
kd = KDTree(len(cloud))
for i, c in enumerate(cloud):
    kd.insert(Vector(c), i)
kd.balance()
lo, hi = cloud.min(0) - 0.03, cloud.max(0) + 0.03
cand = np.nonzero((V >= lo).all(1) & (V <= hi).all(1) & (V[:, 1] <= y_hinge + 0.005))[0]
dist = np.array([kd.find(Vector(V[i]))[2] for i in cand])
ramp = lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1))
NEAR, FAR, REAR = 0.004, 0.022, 0.03
w_dist = 1 - ramp((dist - NEAR) / (FAR - NEAR))                              # 1 on the jaw surface -> 0 at FAR
w_top = ramp((z_top - V[cand, 2]) / (0.15 * (z_top - J[:, 2].min()) + 1e-6))   # keep the upper lip / skull still
w_rear = ramp((y_hinge - V[cand, 1]) / REAR)                                   # fade at the hinge plane
# --- mouth opening (front centre): the jaw's top edge at the front is the bottom of the opening --
mouth_union = np.zeros_like(best_mask("lower_jaw"))
for mm_ in glob.glob(os.path.join(MASKS, "open_mouth_0_*.npy")) + glob.glob(os.path.join(MASKS, "mouth_0_*.npy")):
    mouth_union |= np.load(mm_)
M = mask_points(mouth_union)
Mc = M[np.abs(M[:, 0]) < 0.025]
mouth_top, mouth_bottom = np.percentile(Mc[:, 2], 97), np.percentile(Mc[:, 2], 3)
y_mouth = np.percentile(M[:, 1], 50)                                     # depth of the opening
pp.log("mouth opening z %.3f..%.3f at y %.3f" % (mouth_bottom, mouth_top, y_mouth))

# jaw line: from the mouth floor at the lips, rising linearly to the hinge height at the hinge plane
ty = np.clip((V[cand, 1] - y_mouth) / (y_hinge - y_mouth + 1e-6), 0, 1)
z_cut = mouth_bottom + (z_top - mouth_bottom) * ty
w_line = 1 - ramp((V[cand, 2] - (z_cut + 0.003)) / 0.03)                 # nothing above the jaw line moves
f = w_dist * w_line * w_rear
keep = f > 0.01
jaw, f = cand[keep], f[keep]
pp.log("jaw visible", len(vis), "-> weighted", len(jaw), "z_top %.3f y_hinge %.3f" % (z_top, y_hinge))

# hinge: rearmost-top jaw points per side; chin: lowest, most forward of the FRONT cloud
def rear_top(ids):
    Q = V[ids]; back = Q[Q[:, 1] > np.percentile(Q[:, 1], 90)]
    return back[back[:, 2].argmax()]
x_l, x_r = np.percentile(J[:, 0], 2), np.percentile(J[:, 0], 98)
side_l = jaw[(V[jaw, 0] < x_l + 0.25 * (x_r - x_l))]
side_r = jaw[(V[jaw, 0] > x_r - 0.25 * (x_r - x_l))]
hl, hr = rear_top(side_l), rear_top(side_r)
head = (hl + hr) / 2
tail = J[np.argmin(J[:, 2] * 1.0 + J[:, 1] * 0.5)].copy()
pp.log("jaw hinge", head.round(3), "chin", tail.round(3))

# --- bone --------------------------------------------------------------------------------------
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones
head_bone_name = json.load(open(os.path.join(os.path.dirname(RIGGED), "bone_roles.json")))["head"]
b = eb.new("jaw")
inv = arm.matrix_world.inverted()
b.head = inv @ Vector(head)
b.tail = inv @ Vector(tail)
b.parent = eb[head_bone_name]
b.use_connect = False
bpy.ops.object.mode_set(mode="OBJECT")

# --- weights: f on the jaw, existing bones scaled by (1 - f) ---------------------------------
vg = mesh.vertex_groups.new(name="jaw")
for i, fi in zip(jaw, f):
    v = me.vertices[int(i)]
    for g in v.groups:
        if mesh.vertex_groups[g.group].name != "jaw":
            mesh.vertex_groups[g.group].add([int(i)], g.weight * (1 - fi), "REPLACE")
q = np.round(f * 40) / 40
for val in np.unique(q):
    if val > 0:
        vg.add(jaw[q == val].tolist(), float(val), "REPLACE")

# --- closed angle: rotate the jaw until it collides with the static upper jaw / teeth ------------
moving = jaw[f > 0.9]
moving = moving[(np.abs(V[moving, 0]) < 0.06) & (V[moving, 1] < y_mouth + 0.02)]        # front of the lower jaw
static_mask = np.ones(n, bool); static_mask[jaw[f > 0.05]] = False
near_mouth = static_mask & (np.abs(V[:, 0]) < 0.07) & (V[:, 1] < y_mouth + 0.03) & (V[:, 2] > mouth_bottom - 0.01) & (V[:, 2] < mouth_top + 0.04)
static = V[np.nonzero(near_mouth)[0]]
kds = KDTree(len(static))
for i, c in enumerate(static):
    kds.insert(Vector(c), i)
kds.balance()
P = V[moving] - head
sign = None
def min_gap(deg):
    a = math.radians(deg); y, z = P[:, 1], P[:, 2]
    R_ = np.stack([P[:, 0], y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)], 1) + head
    return min(kds.find(Vector(q))[2] for q in R_[::4])
up = 1 if (P[:, 1] * math.sin(math.radians(5)) + P[:, 2] * math.cos(math.radians(5))).mean() > P[:, 2].mean() else -1
CONTACT = 0.003                                                    # ~ one edge length
deg = 0.0
while deg < 40 and min_gap(up * deg) > CONTACT:
    deg += 0.5
jaw_closed_deg = round(max(deg - 0.5, 0.0), 1)
pp.log("collision closure: %d moving verts vs %d static | gap at rest %.4f | closes at %.1f deg" % (len(moving), len(static), min_gap(0), jaw_closed_deg))

# --- export + roles ----------------------------------------------------------------------------
bpy.ops.object.select_all(action="DESELECT"); mesh.select_set(True); arm.select_set(True)
bpy.context.view_layer.objects.active = arm
out_glb = os.path.join(OUT, "rigged_jaw.glb")
bpy.ops.export_scene.gltf(filepath=out_glb, use_selection=True)
json.dump({"groups": groups, "jaw_region_verts": int(len(jaw)), "hinge": head.tolist(), "chin": tail.tolist(),
           "jaw_closed_deg": jaw_closed_deg},
          open(os.path.join(OUT, "face_groups.json"), "w"), indent=1)
roles = json.load(open(os.path.join(os.path.dirname(RIGGED), "bone_roles.json")))
roles["jaw"] = "jaw"
roles["jaw_closed_deg"] = jaw_closed_deg          # rotate the jaw by -this to shut the mouth; never beyond
json.dump(roles, open(os.path.join(OUT, "bone_roles.json"), "w"), indent=1)
pp.log("EXPORTED", out_glb)

# --- check renders: jaw closed 25° / rest / open 20° from the front ----------------------------
for s in mesh.material_slots:
    bs = next(nd for nd in s.material.node_tree.nodes if nd.type == "BSDF_PRINCIPLED")
    for l in list(bs.inputs["Metallic"].links):
        s.material.node_tree.links.remove(l)
    bs.inputs["Metallic"].default_value = 0
pp.neutral_lights(sc, Vector((0, 0, 0.2)))
sc.render.engine = "BLENDER_EEVEE_NEXT"; sc.eevee.taa_render_samples = 8; sc.render.filter_size = 1.5
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_depth = "8"
sc.render.resolution_x = sc.render.resolution_y = 1024
cam.data.ortho_scale = pp.ORTHO_HEAD
cam.location = (pp.HEAD_CENTRE.x, pp.HEAD_CENTRE.y - pp.R, pp.HEAD_CENTRE.z); cam.rotation_euler = (math.radians(90), 0, 0)
pbj = arm.pose.bones["jaw"]; pbj.rotation_mode = "XYZ"
local_x = ((arm.matrix_world @ arm.data.bones["jaw"].matrix_local).to_3x3().inverted() @ Vector((1, 0, 0))).normalized()
from mathutils import Quaternion
for name, deg in (("rest", 0), ("closed", -jaw_closed_deg), ("half", -0.5 * jaw_closed_deg), ("open15", 15)):
    pbj.rotation_mode = "QUATERNION"
    pbj.rotation_quaternion = Quaternion(local_x, math.radians(deg))
    sc.render.filepath = os.path.join(OUT, f"jaw_{name}.png"); bpy.ops.render.render(write_still=True)
pp.log("DONE")
