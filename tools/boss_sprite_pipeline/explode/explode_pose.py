"""Step 8: pose test — the exploded parts worn over the naked rigged body.

    .venv-bpy/Scripts/python.exe explode_pose.py [--hide-body] [--texture] <base_rigged.glb> <roles.json> <out_dir> <label>=<parts.glb> [...]

For each parts GLB (one object per part, all in the outfit's frame: input_parts.glb = cut shells,
merged_parts.glb = shells + HoloPart infill):
1. align   one similarity for all parts, as whole_fit.py: scale from height, then the parts' head
           ICP-matched onto the base head
2. weights each part vertex copies the base skin weights of its 4 nearest body vertices
           (inverse distance, top 4 bones)
3. render  the body stays visible in bright green under the parts: any green showing in a pose is
           a gap between parts or body poking through. Parts in flat part colours.
           --hide-body: the body is not rendered and backfaces are culled, on a red background:
           red inside the figure = a see-through gap (a game hides the body under worn gear).
           --texture: parts in their own paint instead of flat part colours.
           No parts GLB given (use with --texture): the bare rigged body alone, in the same poses.
           --dqs: Blender "Preserve Volume" (dual quaternion) skinning on every mesh. Sprite route only:
           the in-game GPU skinning (PLAN_mesh_skinning.md) is linear blend.
           --rigid: armour weights by piece instead of copied skin (rigid_weights below): plates move
           as plates; the pauldron rides 1/4 collarbone / 3/4 upper arm; the skirt blends to the thighs.
Explode v2:
  --aligned        the parts are already in the base's coordinates (explode2/outfit_skeleton.py aligned
                   the outfit in step 0): no similarity fit (which needs every part for the height).
  --only a,b       wear only these parts (e.g. --only torso: the breastplate alone on the naked body).
  --hide-under     delete the body faces a worn part covers or that poke out through it, as a game
                   hides the body under worn gear; the rest of the body stays (see hide_under).
  --hide-head      delete the body's head and neck faces before rendering, so any skin left in the image is
                   skin the armour should cover (explode2/measure/skin_metric.py counts it).
  --mask           flat colours, no anti-aliasing: body pure green, every piece grey, black background, so a
                   pixel is exactly body, piece or nothing (explode2/measure/skin_metric.py). Each visible body pixel is
                   then split by its camera ray (split_mask): armour just behind it = poking through (green),
                   none = an opening or hole in the armour (cyan).
  --tuck-from <npz> the tuck explode2/options/fit_set.py computed for a whole worn set (tuck_offsets.npz), applied to
                   this copy of the body by position (works on an animated.blend too); use instead of --tuck.
  --tuck           instead of --hide-under: push the skin a worn piece covers inward, behind it, by what the
                   worst of the test poses needs (see tuck_under). Nothing is deleted, so there is no hole in
                   the body to see into through the piece's openings, and skin that would poke out when he
                   bends (lower back under a chest-rigid plate) stays inside.
  --sweep          instead of the 6 still poses: each motion in SWEEPS swept smoothly (12 steps there and
                   back), front-3/4 and side, as SWEEP_<motion>.gif + SWEEP_SHEET.png (every 3rd step).
  --clips a,b      play these retargeted clips instead: <base_rigged> is then retarget_bvh.py's
                   animated.blend (one action per clip). Every 3rd frame, front-3/4 and side, camera
                   on his root: _anim_<clip>/<frame>.png and ANIM_<clip>.gif.
Writes POSE_<label>.png (poses x views) per variant and POSE_COMPARE.png (key poses side by side).
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector, kdtree
from PIL import Image, ImageDraw

from explode_common import fit_poses, piece_weights, set_pose, test_poses, world_verts
from explode_common import skin_bones as common_skin_bones

HIDE_BODY = "--hide-body" in sys.argv
TEXTURE = "--texture" in sys.argv
DQS = "--dqs" in sys.argv
RIGID = "--rigid" in sys.argv
ALIGNED = "--aligned" in sys.argv
HIDE_UNDER = "--hide-under" in sys.argv
SWEEP = "--sweep" in sys.argv
HIDE_HEAD = "--hide-head" in sys.argv
MASK = "--mask" in sys.argv      # flat colours, no anti-aliasing: body pure green, pieces grey (explode2/measure/skin_metric.py)
TUCK = "--tuck" in sys.argv
TUCK_MARGIN, TUCK_THICK = 0.004, 0.004   # x height: skin stays this far inside the plate's inner side
ONLY = None
if "--only" in sys.argv:
    _i = sys.argv.index("--only")
    ONLY = set(sys.argv[_i + 1].split(","))
    del sys.argv[_i:_i + 2]
TUCK_FROM = None                 # explode2/options/fit_set.py's tuck_offsets.npz: rest position -> offset per skin vertex
if "--tuck-from" in sys.argv:
    _i = sys.argv.index("--tuck-from")
    TUCK_FROM = os.path.abspath(sys.argv[_i + 1])
    del sys.argv[_i:_i + 2]
CLIPS = None
if "--clips" in sys.argv:
    _i = sys.argv.index("--clips")
    CLIPS = sys.argv[_i + 1].split(",")
    del sys.argv[_i:_i + 2]
# Every frame is 4 renders of a 1M-face figure on the laptop (~5 s). A check renders only what is reviewed:
# KEY_FRAMES frames per clip (picked from the every-3rd-frame grid, so they match an earlier full bare run
# frame for frame) and each sweep at start / middle / end. --gif renders every CLIP_STEP-th frame and
# SWEEP_STEPS steps and writes the GIFs (~25 min for the two clips and the sweeps).
GIF = "--gif" in sys.argv
if GIF:
    sys.argv.remove("--gif")
KEY_FRAMES, CLIP_STEP, SWEEP_STEPS = 5, 6, (8 if GIF else 2)
ARGS = [a for a in sys.argv[1:] if a not in ("--hide-body", "--texture", "--dqs", "--rigid", "--aligned", "--hide-under",
                                             "--sweep", "--tuck", "--hide-head", "--mask")]
HIDE_OUT, HIDE_IN = 0.06, 0.03     # x height: part in front of the skin / skin poking out through the part
PIECE_BONES = set()                # bones the worn parts sit on (copied skin, >= 10 % of a part's weight)
BASE, ROLES, OUT = (os.path.abspath(a) for a in ARGS[:3])
VARIANTS = [(a.split("=", 1)[0], os.path.abspath(a.split("=", 1)[1])) for a in ARGS[3:]]
os.makedirs(OUT, exist_ok=True)
RES = 512
HEAD_FRAC = 0.12
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
           (170, 110, 40), (255, 250, 200)]
BODY_COLOUR = (0.05, 1.0, 0.1, 1)


def log(*a):
    print(*a, flush=True)


def kd(points):
    t = kdtree.KDTree(len(points))
    for i, p in enumerate(points):
        t.insert(p, i)
    t.balance()
    return t


def nearest(tree, points, k=1):
    idx = np.empty((len(points), k), np.int64)
    dist = np.empty((len(points), k), np.float32)
    for i, p in enumerate(points):
        for j, (_, n, d) in enumerate(tree.find_n(p, k)):
            idx[i, j], dist[i, j] = n, d
    return idx, dist


if BASE.endswith(".blend"):                 # retarget_bvh.py output: the rig with one action per clip
    bpy.ops.wm.open_mainfile(filepath=BASE)
    for o in bpy.data.objects:
        o.hide_viewport = False
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=BASE)
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
# the body's own armature (an animated.blend also holds the BVH source skeletons)
arm = next((m.object for m in body.modifiers if m.type == "ARMATURE" and m.object), None) or \
    next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not body]:
    bpy.data.objects.remove(o, do_unlink=True)
if arm.animation_data:
    arm.animation_data.action = None          # rest while the parts are loaded and weighted
body.color = BODY_COLOUR
roles = json.load(open(ROLES))
B = world_verts(body)
hB = float(np.ptp(B[:, 2]))
tree_body = kd(B)
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
if TUCK_FROM:                    # the fitted set's tucked skin, matched to this copy of the body by position
    from scipy.spatial import cKDTree as _KD
    _t = np.load(TUCK_FROM)
    _d, _j = _KD(_t["rest"]).query(B, workers=-1)
    _ok = _d < 1e-4 * hB
    _Bt = B + np.where(_ok[:, None], _t["offset"][_j], 0)
    _mi = np.linalg.inv(np.array(body.matrix_world))
    body.data.vertices.foreach_set("co", (_Bt @ _mi[:3, :3].T + _mi[:3, 3]).astype(np.float32).ravel())
    body.data.update()
    log(f"tuck-from: {int(_ok.sum())} of {len(B)} body verts matched, "
        f"{int((np.linalg.norm(_t['offset'][_j], axis=1) * _ok > 1e-5 * hB).sum())} moved")
head_b = B[B[:, 2] > B[:, 2].max() - HEAD_FRAC * hB]
tree_head = kd(head_b)


def box_anchor(P):
    return np.array([(P[:, 0].min() + P[:, 0].max()) / 2, (P[:, 1].min() + P[:, 1].max()) / 2, P[:, 2].min()])


PAULDRON_ARM = None              # with --tuck-from: the pauldron split the fit used (fit_set.json beside the npz)
if TUCK_FROM:
    _fj = os.path.join(os.path.dirname(TUCK_FROM), "fit_set.json")
    PAULDRON_ARM = json.load(open(_fj)).get("pauldron_arm", 0.5) if os.path.isfile(_fj) else None  # older fits: 0.5
    log(f"pauldron weights as the fit: {PAULDRON_ARM} upper arm")


def rigid_weights(part, P, Wa):
    """Plate armour weights (explode_common.piece_weights, shared with explode2/options/fit_set.py)."""
    if PAULDRON_ARM is None:
        return piece_weights(part, P, Wa, roles, gnames, hB)
    return piece_weights(part, P, Wa, roles, gnames, hB, pauldron_arm=PAULDRON_ARM)


def skin_bones(part):
    """The bones whose skin a worn piece covers (explode_common.skin_bones)."""
    return common_skin_bones(part, roles)


def load_parts(path, label):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    parts = sorted((o for o in new if o.type == "MESH"), key=lambda o: o.name)
    for o in parts:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    for o in new:
        if o not in parts:
            bpy.data.objects.remove(o, do_unlink=True)
    if ONLY is not None:
        for o in [o for o in parts if o.name.split(".")[0] not in ONLY]:
            bpy.data.objects.remove(o, do_unlink=True)
        parts = [o for o in bpy.data.objects if o.type == "MESH" and o.name.split(".")[0] in ONLY and o in new]
        assert parts, f"none of {ONLY} in {path}"
    # 1. align: one similarity for every part
    A = np.concatenate([world_verts(o) for o in parts])
    s = 1.0 if ALIGNED else hB / float(np.ptp(A[:, 2]))
    a0, b0 = (np.zeros(3), np.zeros(3)) if ALIGNED else (box_anchor(A), box_anchor(B))
    A = (A - a0) * s + b0
    shift = np.zeros(3)
    rng = np.random.default_rng(0)
    for _ in range(0 if ALIGNED else 40):
        hpts = A[A[:, 2] > A[:, 2].max() - HEAD_FRAC * hB]
        hpts = hpts[rng.choice(len(hpts), min(6000, len(hpts)), replace=False)]
        idx, dist = nearest(tree_head, hpts)
        keep = dist[:, 0] < np.percentile(dist[:, 0], 90)
        delta = (head_b[idx[keep, 0]] - hpts[keep]).mean(0)
        A += delta
        shift += delta
        if np.linalg.norm(delta) < 1e-5 * hB:
            break
    if ALIGNED:
        log(f"{label}: {len(parts)} parts, already aligned ({', '.join(o.name for o in parts)})")
    else:
        log(f"{label}: {len(parts)} parts, scale {s:.4f}, head residual median {np.median(dist[:, 0]) / hB * 100:.2f}% of height")
    # 2. weights per part
    for j, o in enumerate(parts):
        P = (world_verts(o) - a0) * s + b0 + shift
        o.data.vertices.foreach_set("co", P.astype(np.float32).ravel())
        o.data.update()
        idx4, d4 = nearest(tree_body, P, k=4)
        inv = 1.0 / np.maximum(d4, 1e-6)
        Wa = (W[idx4] * inv[:, :, None]).sum(1) / inv.sum(1, keepdims=True)
        share = Wa.sum(0) / max(Wa.sum(), 1e-9)
        PIECE_BONES.update(np.nonzero(share >= 0.10)[0].tolist())
        if RIGID:
            Wa = rigid_weights(o.name.split(".")[0], P, Wa)
        top = np.argsort(-Wa, 1)[:, :4]
        m4 = np.zeros_like(Wa, bool)
        np.put_along_axis(m4, top, True, 1)
        Wa = np.where(m4, Wa, 0)
        Wa /= np.maximum(Wa.sum(1, keepdims=True), 1e-9)
        for gi, name in enumerate(gnames):
            nz = np.nonzero(Wa[:, gi] > 1e-3)[0]
            if not len(nz):
                continue
            vg = o.vertex_groups.new(name=name)
            q = np.round(Wa[nz, gi] * 255).astype(int)
            for level in np.unique(q):
                vg.add(nz[q == level].tolist(), level / 255.0, "REPLACE")
        o.parent = arm
        o.matrix_parent_inverse = arm.matrix_world.inverted()
        o.modifiers.new("Armature", "ARMATURE").object = arm
        o.color = tuple(x / 255 for x in PALETTE[j % len(PALETTE)]) + (1,)
    return parts


sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "TEXTURE" if TEXTURE else "OBJECT"
sc.render.resolution_x = sc.render.resolution_y = RES
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.18, 0.18, 0.2)
if HIDE_BODY:
    body.hide_render = True
    sc.world.color = (0.8, 0.08, 0.08)
    sc.display.shading.show_backface_culling = True
SHOWING = "red = see-through gap" if HIDE_BODY else "green = body showing"
if TEXTURE:                               # judging the look: neutral background
    sc.world.color = (0.3, 0.3, 0.32)
    sc.display.shading.show_specular_highlight = False   # Workbench adds a gloss the paint does not have
    SHOWING = "real paint"
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = hB * 1.25
centre = Vector(((B.min(0) + B.max(0)) / 2).tolist())
VIEWS = {"front": Vector((0, -1, 0)), "3/4": Vector((-0.7, -0.7, 0)), "side": Vector((1, 0, 0)),
         "back": Vector((0, 1, 0))}
POSES = fit_poses(roles)        # the 6 test poses and the 8 stretch extremes, all checked from 4 sides


def pose(name):
    global _BVH
    set_pose(arm, POSES[name])
    _BVH = None


SPLIT_DEPTH = 0.02   # x height: armour this close behind a visible body pixel = the body pokes through it
_BVH = None          # the posed body and worn pieces as ray trees, rebuilt after every pose change


def split_mask(path):
    """--mask: why each visible body pixel shows. Its camera ray goes on past the body: armour within
    SPLIT_DEPTH behind = the body pokes through that armour (the tuck should have put it behind; stays green);
    no armour that close = an opening or a hole in the armour (coverage / cut; made cyan)."""
    global _BVH
    from mathutils.bvhtree import BVHTree
    a = np.asarray(Image.open(path).convert("RGB")).copy()
    ys, xs = np.nonzero((a[..., 1] > 200) & (a[..., 0] < 60))
    if not len(ys):
        return
    if _BVH is None:
        dg = bpy.context.evaluated_depsgraph_get()
        objs = [body] + [o for parts in variants.values() for o in parts if not o.hide_render]
        _BVH = [(o is body, BVHTree.FromObject(o, dg), o.matrix_world.copy(), o.matrix_world.inverted())
                for o in objs]
    M = cam.matrix_world.to_3x3()
    right, up, fwd = M.col[0], M.col[1], -M.col[2]
    s = cam.data.ortho_scale
    for y, x in zip(ys, xs):
        o = cam.location + right * (((x + 0.5) / RES - 0.5) * s) + up * ((0.5 - (y + 0.5) / RES) * s)
        hit = {True: math.inf, False: math.inf}
        for is_body, t, mw, mi in _BVH:
            loc = t.ray_cast(mi @ o, (mi.to_3x3() @ fwd).normalized())[0]
            if loc is not None:
                hit[is_body] = min(hit[is_body], ((mw @ loc) - o).length)
        if hit[False] - hit[True] > SPLIT_DEPTH * hB:
            a[y, x] = (0, 255, 255)
    Image.fromarray(a).save(path)


def shot(view, path):
    d = VIEWS[view].normalized()
    cam.location = centre + d * hB * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if MASK:
        split_mask(path)
    return Image.open(path).convert("RGB")


def hide_under(parts):
    """Delete the body faces the worn parts cover. A face goes when a ray along its normal meets a part
    within HIDE_OUT x h (skin under the plate) or against its normal within HIDE_IN x h (skin poking out
    through it: the naked barb is bulkier than the armour), and one of its vertices' main bone is a bone the
    piece covers (skin_bones: an arm hanging beside the torso keeps its skin). Done once, at rest."""
    import bmesh
    from mathutils.bvhtree import BVHTree
    verts, tris = [], []
    for o in parts:
        P = world_verts(o)
        T = np.empty(len(o.data.polygons) * 3, np.int64)
        o.data.polygons.foreach_get("vertices", T)
        tris += (T.reshape(-1, 3) + len(verts)).tolist()
        verts += P.tolist()
    bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    main = W.argmax(1)
    covered = {gnames.index(b) for o in parts for b in skin_bones(o.name.split(".")[0]) if b in gnames}
    PIECE_BONES.clear()
    PIECE_BONES.update(covered)
    keep_bone = np.isin(main, list(covered))
    mw, rot = body.matrix_world, body.matrix_world.to_3x3()
    bm = bmesh.new()
    bm.from_mesh(body.data)
    kill = []
    for f in bm.faces:
        if not any(keep_bone[v.index] for v in f.verts):
            continue
        c, n = mw @ f.calc_center_median(), (rot @ f.normal).normalized()
        if bvh.ray_cast(c + n * 1e-5 * hB, n, HIDE_OUT * hB)[0] is not None or \
                bvh.ray_cast(c - n * 1e-5 * hB, -n, HIDE_IN * hB)[0] is not None:
            kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()
    log(f"hide-under: {len(kill)} body faces removed under {', '.join(o.name for o in parts)} "
        f"(bones {', '.join(gnames[i] for i in sorted(PIECE_BONES))})")


def rigid_bone(part):
    """The one bone a rigid piece rides (rigid_weights), or None for blended pieces."""
    base = part[:-2] if part[-2:] in ("_l", "_r") else part
    return {"torso": roles["chest"], "head": roles["head"], "belt": roles["root"]}.get(base)


def tuck_under(parts):
    """Push the skin each rigid piece covers inward until it stays TUCK_MARGIN inside the piece's inner side
    (outer radius - TUCK_THICK) in every test and stretch pose (fit_poses). Measured in the piece's bone frame, where the piece never
    moves: per pose the body is moved into that frame, binned round a vertical axis through the piece (1 % h
    x 5 deg), and each covered skin vertex (skin_bones) gets the largest shortfall over the poses. The push is
    radial at rest, spread to neighbours so the skin does not crease, and nothing is pushed where the piece
    is absent (its openings): there the skin stays visible and whole."""
    global B
    for o in parts:
        name = o.name.split(".")[0]
        bone = rigid_bone(name)
        if bone is None:
            log(f"tuck: {name} is not rigid, skipped")
            continue
        P = world_verts(o)
        ax = (P[:, :2].min(0) + P[:, :2].max(0)) / 2
        z0, DZ, NAZ = float(B[:, 2].min()), 0.01 * hB, 72
        NZ = int(math.ceil(hB / DZ)) + 2

        def cyl(X):
            d = X[:, :2] - ax
            r = np.linalg.norm(d, axis=1)
            az = ((np.arctan2(d[:, 1], d[:, 0]) + math.pi) / (2 * math.pi) * NAZ).astype(int) % NAZ
            zi = np.clip(((X[:, 2] - z0) / DZ).astype(int), 0, NZ - 1)
            return r, az, zi, d / np.maximum(r, 1e-9)[:, None]
        rp, azp, zp, _ = cyl(P)
        outer = np.zeros((NZ, NAZ))
        np.maximum.at(outer, (zp, azp), rp)
        allowed = np.where(outer > 0, outer - (TUCK_THICK + TUCK_MARGIN) * hB, np.inf)
        cand = np.nonzero(np.isin(W.argmax(1), [gnames.index(b) for b in skin_bones(name) if b in gnames]))[0]
        need = np.zeros(len(B))
        set_pose(arm, [])
        C_rest = np.array(arm.matrix_world @ arm.pose.bones[bone].matrix)
        for pname, rots in fit_poses(roles).items():      # the test poses and the stretch extremes
            set_pose(arm, rots)
            dg = bpy.context.evaluated_depsgraph_get()
            ev = body.evaluated_get(dg)
            me = ev.to_mesh()
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            ev.to_mesh_clear()
            mw = np.array(body.matrix_world)
            X = co.reshape(-1, 3)[cand] @ mw[:3, :3].T + mw[:3, 3]
            T = C_rest @ np.linalg.inv(np.array(arm.matrix_world @ arm.pose.bones[bone].matrix))
            X = X @ T[:3, :3].T + T[:3, 3]
            r, az, zi, _ = cyl(X)
            need[cand] = np.maximum(need[cand], r - allowed[zi, az])
        set_pose(arm, [])
        need = np.where(np.isfinite(need), np.maximum(need, 0), 0)
        # spread over the skin so the pushed patch has no step at its edge (max, then average, over edges)
        Fb = np.array([p.vertices[:] for p in body.data.polygons if len(p.vertices) == 3])
        E = np.concatenate([Fb[:, [0, 1]], Fb[:, [1, 2]], Fb[:, [2, 0]]])
        for _ in range(3):
            m2 = need.copy()
            np.maximum.at(m2, E[:, 0], need[E[:, 1]])
            np.maximum.at(m2, E[:, 1], need[E[:, 0]])
            need = m2
        deg = np.bincount(E[:, 0], minlength=len(B)) + np.bincount(E[:, 1], minlength=len(B))
        for _ in range(6):
            s = np.bincount(E[:, 0], weights=need[E[:, 1]], minlength=len(B)) + \
                np.bincount(E[:, 1], weights=need[E[:, 0]], minlength=len(B))
            need = 0.5 * need + 0.5 * s / np.maximum(deg, 1)
        _, _, _, dirs = cyl(B)
        Bn = B.copy()
        Bn[:, :2] -= dirs * need[:, None]
        mwi = np.linalg.inv(np.array(body.matrix_world))
        body.data.vertices.foreach_set("co", (Bn @ mwi[:3, :3].T + mwi[:3, 3]).astype(np.float32).ravel())
        body.data.update()
        B = Bn
        moved = need > 1e-5 * hB
        log(f"tuck: {name} on {bone}: {int(moved.sum())} skin verts pushed in, max {need.max() / hB * 100:.2f}% h, "
            f"median {np.median(need[moved]) / hB * 100 if moved.any() else 0:.2f}% h")


variants = {label: load_parts(path, label) for label, path in VARIANTS}
if HIDE_UNDER:
    assert len(variants) == 1, "--hide-under edits the body: one parts GLB per run"
    hide_under(next(iter(variants.values())))
if TUCK:
    assert len(variants) == 1, "--tuck edits the body: one parts GLB per run"
    tuck_under(next(iter(variants.values())))
if HIDE_HEAD:                    # the bare head is meant to show: take it out so only stray skin is left
    import bmesh
    _hb = {gnames.index(b) for b in (roles["head"], roles["neck"]) if b in gnames}
    _main = W.argmax(1)
    _bm = bmesh.new()
    _bm.from_mesh(body.data)
    _kill = [f_ for f_ in _bm.faces if any(_main[v_.index] in _hb for v_ in f_.verts)]
    bmesh.ops.delete(_bm, geom=_kill, context="FACES")
    _bm.to_mesh(body.data)
    _bm.free()
    body.data.update()
    log(f"hide-head: {len(_kill)} head/neck faces removed")
if MASK:                         # every pixel is exactly body, piece or background
    sc.display.shading.light = "FLAT"
    sc.display.shading.color_type = "OBJECT"
    sc.display.shading.show_backface_culling = False
    sc.display.render_aa = "OFF"
    sc.view_settings.view_transform = "Standard"
    sc.world.color = (0, 0, 0)
    body.color = (0, 1, 0, 1)
    for o in [o for parts in variants.values() for o in parts]:
        o.color = (0.5, 0.5, 0.5, 1)
    SHOWING = "mask"

MOVE_VIEWS = ("front", "3/4", "side", "back")   # every movement check is seen from all four sides


def all_sides(path_stem):
    """One frame: the four MOVE_VIEWS side by side (each also saved as <path_stem>_<view>.png)."""
    fr = Image.new("RGB", (RES * len(MOVE_VIEWS), RES))
    for i, v in enumerate(MOVE_VIEWS):
        fr.paste(shot(v, f"{path_stem}_{v.replace('/', '')}.png"), (i * RES, 0))
    return fr


if CLIPS:
    for o in [o for parts in variants.values() for o in parts]:
        o.hide_render = False
    arm.animation_data_create()
    root_pb = arm.pose.bones[roles["root"]]
    z_mid = float(centre.z)
    for clip in CLIPS:
        act = bpy.data.actions[clip]
        arm.animation_data.action = act
        f0, f1 = (int(round(x)) for x in act.frame_range)
        tmp = os.path.join(OUT, f"_anim_{clip}")
        os.makedirs(tmp, exist_ok=True)
        frames_c = []
        grid = list(range(f0, f1 + 1, 3))
        picks = range(f0, f1 + 1, CLIP_STEP) if GIF else \
            [grid[int(i * (len(grid) - 1) / (KEY_FRAMES - 1))] for i in range(KEY_FRAMES)]
        for f in picks:
            sc.frame_set(f)
            _BVH = None
            r = arm.matrix_world @ root_pb.head
            centre = Vector((r.x, r.y, z_mid))  # shot() frames on centre: follow him as he walks
            fr = all_sides(os.path.join(tmp, f"{f:04d}"))
            fr.save(os.path.join(tmp, f"{f:04d}.png"))
            frames_c.append(fr)
        if GIF:
            frames_c[0].save(os.path.join(OUT, f"ANIM_{clip}.gif"), save_all=True, append_images=frames_c[1:],
                             duration=int(1000 / 30 * CLIP_STEP), loop=0)   # the clip's own speed (30 fps)
        log(f"played {clip}: {len(frames_c)} frames")
    log("POSE_OK")
    sys.exit(0)

if SWEEP:
    # each motion: angle at step t in [0, 1] -> [(bone, axis, deg)]; past the 6 still poses' angles
    al, ar = roles["arm_l"], roles["arm_r"]
    SWEEPS = {
        "twist": lambda t: [(roles["chest"], "Z", -45 + 90 * t)],
        "bend": lambda t: [(roles["spine"], "X", -15 + 55 * t)],
        "side bend": lambda t: [(roles["spine"], "Y", -25 + 50 * t)],
        "arms swing": lambda t: [(al["elbow"], "X", 40 - 130 * t), (ar["elbow"], "X", 40 - 130 * t)],
        "arms raise": lambda t: [(al["elbow"], "Y", -90 * t), (ar["elbow"], "Y", 90 * t)],
    }
    STEPS = SWEEP_STEPS
    for o in [o for parts in variants.values() for o in parts]:
        o.hide_render = False
    sheet_rows = []
    for mname, fn in SWEEPS.items():
        frames_m = []
        for k in list(range(STEPS + 1)) + (list(range(STEPS - 1, 0, -1)) if GIF else []):
            set_pose(arm, fn(k / STEPS))
            _BVH = None
            frames_m.append(all_sides(os.path.join(OUT, "_sweep")))
        name = mname.replace(" ", "_")
        if GIF:
            frames_m[0].save(os.path.join(OUT, f"SWEEP_{name}.gif"), save_all=True, append_images=frames_m[1:],
                             duration=120, loop=0)
        sheet_rows.append((mname, [frames_m[0], frames_m[STEPS // 2], frames_m[STEPS]]))   # start, middle, end
        log(f"swept {mname}")
    LABEL = 22
    cols = max(len(r) for _, r in sheet_rows)
    W = RES * len(MOVE_VIEWS)
    sheet = Image.new("RGB", (W * cols, (RES + LABEL) * len(sheet_rows)), (25, 25, 28))
    draw = ImageDraw.Draw(sheet)
    for r, (mname, fr_list) in enumerate(sheet_rows):
        draw.text((6, r * (RES + LABEL) + 4), mname, fill=(230, 230, 230))
        for c, fr in enumerate(fr_list):
            sheet.paste(fr, (c * W, r * (RES + LABEL) + LABEL))
    sheet.save(os.path.join(OUT, "SWEEP_SHEET.png"))
    set_pose(arm, [])
    log("POSE_OK")
    sys.exit(0)
if DQS:
    for o in bpy.data.objects:
        for m in getattr(o, "modifiers", []):
            if m.type == "ARMATURE":
                m.use_deform_preserve_volume = True
if not VARIANTS:                          # no parts given: the bare rigged body alone, in its own paint
    body.hide_render = False
    sc.display.shading.show_backface_culling = False
    variants = {"body": []}
frames = {}
for label, parts in variants.items():
    for other in variants.values():
        for o in other:
            o.hide_render = other is not parts
    tmp = os.path.join(OUT, f"_frames_{label}{'_dqs' if DQS else ''}{'_rigid' if RIGID else ''}")
    os.makedirs(tmp, exist_ok=True)
    for pname in POSES:
        pose(pname)
        for v in VIEWS:
            frames[label, pname, v] = shot(v, os.path.join(tmp, f"{pname}_{v}.png".replace(" ", "_").replace("/", "")))
    log("rendered", label)
    LABEL = 22
    sheet = Image.new("RGB", (RES * len(VIEWS), (RES + LABEL) * len(POSES)), (25, 25, 28))
    draw = ImageDraw.Draw(sheet)
    for r, pname in enumerate(POSES):
        y = r * (RES + LABEL)
        draw.text((6, y + 4), f"{pname} | {label} ({SHOWING})      " + "   ".join(VIEWS), fill=(230, 230, 230))
        for c, v in enumerate(VIEWS):
            sheet.paste(frames[label, pname, v], (c * RES, y + LABEL))
    sheet.save(os.path.join(OUT, f"POSE_{label}{'_nobody' if HIDE_BODY else ''}{'_tex' if TEXTURE else ''}{'_dqs' if DQS else ''}{'_rigid' if RIGID else ''}.png"))

# side by side: each key pose, every variant, front and 3/4
KEY = [("rest", "front"), ("arms up", "front"), ("arms up", "3/4"), ("twist", "3/4"), ("step", "side"), ("bend", "side")]
labels = list(variants)
cmp = Image.new("RGB", (RES * len(labels), (RES + 22) * len(KEY)), (25, 25, 28))
draw = ImageDraw.Draw(cmp)
for r, (pname, v) in enumerate(KEY):
    for c, label in enumerate(labels):
        cmp.paste(frames[label, pname, v], (c * RES, r * (RES + 22) + 22))
        draw.text((c * RES + 6, r * (RES + 22) + 4), f"{label} | {pname} {v}", fill=(230, 230, 230))
cmp.save(os.path.join(OUT, f"POSE_COMPARE{'_nobody' if HIDE_BODY else ''}{'_tex' if TEXTURE else ''}.png"))
pose("rest")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "pose_test.blend"))
log("POSE_OK")
