"""Step 3: SAM3 masks -> one part label per mesh face -> part-coloured renders + split GLB.

    .venv-bpy/Scripts/python.exe explode_label.py <work_dir> [--facing-power K] [--diag <file>]

Posed cameras (explode_render.py --pose, "pose" in cams.json) look pixels up in that pose's vertex
positions (posed_<pose>_verts.npy), so the plate under the arms - hidden behind the arm at rest - votes
from views where the arm is raised. --no-posed leaves them out (for comparison).

Every covered pixel of every camera is tied to its nearest (welded) mesh vertex through the world
position image, so a mask votes for the vertices it shows: votes += score x priority, normalised by
how many pixels of that camera saw the vertex.
--facing-power K (explode v2): each camera's vote for a vertex is weighted by |normal . view|^K and the
votes are averaged with those weights, so the views that see a surface head-on decide its part (v1, 96
views: grazing low views outvoted the head-on ones on the pauldrons). Without it: v1's plain average. Votes are smoothed over the mesh, the best label wins
where it is strong enough, islands under MIN_ISLAND vertices are dropped, and every vertex still
unlabelled takes the label of the nearest labelled vertex along the surface (the parts the cameras
could not see). Paired parts are split left/right by the sign of x (+x = character's left).

Writes labels_face.npy (int per face of the imported mesh), parts.json, parts_<view>.png,
split_preview.png (parts pulled apart, NOT completed) and input_parts.glb (one object per part).
"""
import glob
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector, kdtree
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

FLAGS = ("--facing-power", "--diag", "--dirs", "--out")
opt = {f: sys.argv[sys.argv.index(f) + 1] for f in FLAGS if f in sys.argv}
FACING_POWER = float(opt["--facing-power"]) if "--facing-power" in opt else None
DIAG_OUT = os.path.abspath(opt["--diag"]) if "--diag" in opt else None
# --dirs N: only the first N greedy directions (cameras named gNNN_...), to measure what more views buy
MAX_DIRS = int(opt["--dirs"]) if "--dirs" in opt else None
# --belt-gate (v2): BELT_GATE + MIN_BY_PROMPT below; without it v1's rules are unchanged
BELT_GATING = "--belt-gate" in sys.argv
# --crease-snap (v2, step 7): borders moved onto the folds where plates meet (see the block before cleanup)
CREASE_SNAP = "--crease-snap" in sys.argv
# band half-width (x h), crease cost, full-crease angle (deg). Band 0.02 let the arm flood a pauldron
# (most of a small plate lay inside the band, so too little of it was left to regrow it); the
# ragged fringe it is for is ~1 % h wide (explode2/measure/border_zoom.py, 2026-11-02).
SNAP_BAND, SNAP_K, SNAP_ANGLE = 0.008, 50.0, 30.0
WORK = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(opt["--out"]) if "--out" in opt else WORK   # results; inputs stay in WORK
os.makedirs(OUT, exist_ok=True)
RESULTS = {}
MIN_VOTE = 0.12         # smoothed vote (score x priority, per camera that saw the vertex)
MIN_ISLAND = 200
PROMPT_PART = {
    "head": "head", "hair": "head", "beard": "head",
    "neck_armor": "torso", "breastplate": "torso",
    "shoulder_armor": "pauldron",
    "upper_arm_armor": "arm", "elbow_armor": "arm", "forearm_armor": "arm",
    "hand": "gauntlet", "glove": "gauntlet",          # "gauntlet" itself scored 0.2-0.47; "hand" 0.87-0.96
    "belt": "belt", "armored_skirt": "skirt",
    # "waist_armor" (v2 prompt) is NOT used: from behind it takes the back plate with the skirt (0.63)
    "thigh_armor": "leg", "knee_armor": "leg", "shin_armor": "leg",
    "armored_boot": "leg",                            # SAM3's "boot" is the whole lower leg
    "foot": "boot", "shoe": "boot",
}
SKIP = {("lower", "armored_skirt")}                   # in the lower crop "armored skirt" took the legs too
MIN_INSTANCE = 0.5                                    # instances below this are mostly wrong guesses
MIN_BY_PROMPT = {"armored_skirt": 0.4}                # v2 painted full plate: the exact front skirt mask scored 0.44
# v2: parts that may only lie above / below the belt line (world height; the belt line = median height
# of SAM's belt masks). From the side and back "armored skirt" also covers the torso's sides, and the
# breastplate mask takes the pointed plate below the belt (explode2/measure/sam_check.py, 2026-11-02).
BELT_GATE = {"skirt": "below", "torso": "above"}
BELT_MARGIN = 0.01                                    # x height
# overlapping masks: the smaller, more specific part wins (a forearm mask usually includes the hand)
PRIORITY = {"gauntlet": 1.6, "boot": 1.6, "belt": 1.5, "head": 1.3, "pauldron": 1.2, "arm": 1.0, "leg": 1.0,
            "skirt": 1.0, "torso": 0.8}
PAIRED = {"pauldron", "arm", "gauntlet", "leg", "boot"}


def log(*a):
    print(*a, flush=True)


meta = json.load(open(os.path.join(WORK, "cams.json")))
if MAX_DIRS is not None:   # the rest-pose greedy views up to N; posed views (explode_render --pose) always count
    meta["cams"] = [c for c in meta["cams"] if c.get("pose")
                    or (c["name"].startswith("g") and int(c["name"][1:4]) < MAX_DIRS)]
if "--no-posed" in sys.argv:
    meta["cams"] = [c for c in meta["cams"] if not c.get("pose")]
# a camera SAM never ran on would count as "saw it, voted for nothing" and dilute the real votes
_n = len(meta["cams"])
meta["cams"] = [c for c in meta["cams"] if glob.glob(os.path.join(WORK, "masks", c["name"] + "__*.png"))]
if len(meta["cams"]) < _n:
    print(f"{_n - len(meta['cams'])} cameras have no SAM masks: left out", flush=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=meta["glb"])
mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not mesh]:
    bpy.data.objects.remove(o, do_unlink=True)
me = mesh.data
n = len(me.vertices)
co = np.empty(n * 3, np.float32)
me.vertices.foreach_get("co", co)
m = np.array(mesh.matrix_world)
V = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
h = float(V[:, 2].max() - V[:, 2].min())
tri = np.empty(len(me.polygons) * 3, np.int64)
me.polygons.foreach_get("vertices", tri)
F = tri.reshape(-1, 3)
# weld UV-seam duplicates: one graph node per position
_, wid = np.unique(np.round(V / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
wid = wid.ravel()
nW = int(wid.max()) + 1
PW = np.zeros((nW, 3))
PW[wid] = V
E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
EW = wid[E]
EW = EW[EW[:, 0] != EW[:, 1]]
log(f"mesh {n} verts -> {nW} welded, {len(F)} faces")

tree = cKDTree(PW)              # exact nearest vertex, vectorised (96 views = ~36M pixel lookups)

parts = sorted(set(PROMPT_PART.values()))
pidx = {p: i for i, p in enumerate(parts)}
votes = np.zeros((nW, len(parts)))
seen = np.zeros(nW)            # cameras that saw the vertex (with --facing-power: their summed weights)
seen_any = np.zeros(nW, bool)
if FACING_POWER is not None:   # welded vertex normals, world space
    vn = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("normal", vn)
    vn = vn.reshape(-1, 3) @ m[:3, :3].T
    NW = np.zeros((nW, 3))
    np.add.at(NW, wid, vn)
    NW /= np.maximum(np.linalg.norm(NW, axis=1, keepdims=True), 1e-12)


POSED = {}


def posed(name):
    """A posed camera's lookup (explode_render --pose): the welded vertex positions and normals in that pose,
    so its pixels vote for the same vertices as the rest views do."""
    if name not in POSED:
        Vp = np.load(os.path.join(WORK, f"posed_{name}_verts.npy"))
        Np = np.load(os.path.join(WORK, f"posed_{name}_normals.npy"))
        PWp = np.zeros((nW, 3))
        PWp[wid] = Vp
        NWp = np.zeros((nW, 3))
        np.add.at(NWp, wid, Np)
        NWp /= np.maximum(np.linalg.norm(NWp, axis=1, keepdims=True), 1e-12)
        POSED[name] = (cKDTree(PWp), NWp)
        log(f"posed views '{name}': lookup built")
    return POSED[name]


def load_pos(path):
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color"
    w, hh = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(hh, w, 4)
    bpy.data.images.remove(img)
    px = np.flipud(px)                                   # top-down rows, like the masks
    return px[..., :3] * 2.0 - 1.0, px[..., 3] > 0.5


def min_score(prompt):
    return MIN_BY_PROMPT.get(prompt, MIN_INSTANCE) if BELT_GATING else MIN_INSTANCE


belt_z = None
if BELT_GATING:                 # the belt line: median world height of the belt masks (first 24 cameras)
    zs = []
    for c in meta["cams"][:24]:
        fs = [f for f in glob.glob(os.path.join(WORK, "masks", c["name"] + "__belt__*.png"))
              if float(os.path.basename(f)[:-4].split("__")[3]) >= MIN_INSTANCE]
        if not fs:
            continue
        pos, cov = load_pos(os.path.join(WORK, c["name"] + "_pos.exr"))
        for f in fs:
            mk = (np.asarray(Image.open(f).convert("L")) > 127) & cov
            zs.append(pos[mk][:, 2])
    belt_z = float(np.median(np.concatenate(zs)))
    log(f"belt line at z {belt_z:.4f} ({100 * (belt_z - V[:, 2].min()) / h:.1f}% of height)")
    RESULTS["belt_line_pct_height"] = round(100 * (belt_z - float(V[:, 2].min())) / h, 2)

for c in meta["cams"]:
    pos, cov = load_pos(os.path.join(WORK, c["name"] + "_pos.exr"))
    ys, xs = np.nonzero(cov)
    c_tree, c_norm = posed(c["pose"]) if c.get("pose") else (tree, NW if FACING_POWER is not None else None)
    pix_v = c_tree.query(pos[ys, xs], workers=-1)[1]
    hits = np.bincount(pix_v, minlength=nW).astype(float)
    if FACING_POWER is None:
        wv = np.ones(nW)
    else:                       # direction towards the camera, as explode_render places it
        a_, e_ = math.radians(c["yaw"]), math.radians(c["elev"])
        dcam = np.array([math.sin(a_) * math.cos(e_), -math.cos(a_) * math.cos(e_), math.sin(e_)])
        wv = np.abs(c_norm @ dcam) ** FACING_POWER
    seen += wv * (hits > 0)
    seen_any |= hits > 0
    vmap = np.full(cov.shape, -1, np.int64)
    vmap[ys, xs] = pix_v
    cam_votes = np.zeros_like(votes)
    for f in glob.glob(os.path.join(WORK, "masks", c["name"] + "__*.png")):
        _, prompt, k, score = os.path.basename(f)[:-4].split("__")
        part = PROMPT_PART.get(prompt)
        if part is None or (c["crop"], prompt) in SKIP or float(score) < min_score(prompt):
            continue
        mk = np.asarray(Image.open(f).convert("L")) > 127
        if belt_z is not None and part in BELT_GATE:
            side = BELT_GATE[part]
            z = pos[..., 2]
            mk &= (z <= belt_z + BELT_MARGIN * h) if side == "below" else (z >= belt_z - BELT_MARGIN * h)
        vv = vmap[mk & cov]
        cnt = np.bincount(vv, minlength=nW)
        frac = np.divide(cnt, hits, out=np.zeros(nW), where=hits > 0)
        # a part takes its strongest prompt, not the sum: three arm prompts must not outvote one shoulder
        j = pidx[part]
        cam_votes[:, j] = np.maximum(cam_votes[:, j], frac * float(score) * PRIORITY[part])
    votes += cam_votes * wv[:, None]
    log(f"cam {c['name']}: {len(ys)} px -> {int((hits > 0).sum())} verts")
votes /= (np.maximum(seen, 1) if FACING_POWER is None else np.maximum(seen, 1e-9))[:, None]
log(f"DIRECT COVERAGE {100 * seen_any.mean():.1f}% of {nW} welded verts seen by >= 1 camera ({len(meta['cams'])} cameras)")
RESULTS["direct_coverage_pct_welded_verts"] = round(100 * float(seen_any.mean()), 2)


def smooth(f, iters):
    deg = np.bincount(EW[:, 0], minlength=nW) + np.bincount(EW[:, 1], minlength=nW)
    for _ in range(iters):
        s = np.zeros_like(f)
        for j in range(f.shape[1]):
            s[:, j] = np.bincount(EW[:, 0], weights=f[EW[:, 1], j], minlength=nW) + \
                      np.bincount(EW[:, 1], weights=f[EW[:, 0], j], minlength=nW)
        f = 0.5 * f + 0.5 * s / np.maximum(deg, 1)[:, None]
    return f


def components(mask):
    lab = np.arange(nW)
    e = EW[mask[EW[:, 0]] & mask[EW[:, 1]]]
    while True:
        a, b = lab[e[:, 0]], lab[e[:, 1]]
        mn = np.minimum(a, b)
        new = lab.copy()
        np.minimum.at(new, a, mn)
        np.minimum.at(new, b, mn)
        while True:
            nxt = new[new]
            if (nxt == new).all():
                break
            new = nxt
        if (new == lab).all():
            return lab
        lab = new


# --belt-gate: BAN[j, v] = part j may not take vertex v (torso below / skirt above the belt line); also
# holds for the surface no camera saw, which gets its part by flooding
BAN = np.zeros((len(parts), nW), bool)
if belt_z is not None:
    for p, side in BELT_GATE.items():
        BAN[pidx[p]] = (PW[:, 2] < belt_z - BELT_MARGIN * h) if side == "above" else (PW[:, 2] > belt_z + BELT_MARGIN * h)


def flood(label):
    """Unlabelled (-1) vertices take the label of the nearest labelled one along the surface."""
    label = label.copy()
    while True:
        a, b = label[EW[:, 0]], label[EW[:, 1]]
        gb = (a >= 0) & (b < 0)
        ga = (b >= 0) & (a < 0)
        gb[gb] = ~BAN[a[gb], EW[gb, 1]]
        ga[ga] = ~BAN[b[ga], EW[ga, 0]]
        if not (ga.any() or gb.any()):
            return label
        label[EW[gb, 1]] = a[gb]
        label[EW[ga, 0]] = b[ga]


# votes only exist where a pixel landed: spread them a little before deciding
sv = smooth(votes, 8)
sv[BAN.T] = 0
best = sv.argmax(1)
label = np.where(sv.max(1) >= MIN_VOTE, best, -1)
log(f"voted: {100 * (label >= 0).mean():.1f}% of welded verts")
RESULTS["voted_pct_welded_verts"] = round(100 * float((label >= 0).mean()), 2)
for it in range(2):
    for j in range(len(parts)):
        sel = label == j
        if not sel.any():
            continue
        comp = components(sel)
        sizes = np.bincount(comp[sel], minlength=nW)
        small = sel & (sizes[comp] < MIN_ISLAND)
        label[small] = -1
    label = flood(label)
orphan = label < 0
if orphan.any():                                          # islands with no labelled neighbour at all
    label[orphan] = best[orphan]

final = label.copy()
names_final = list(parts)
for p in sorted(PAIRED):          # sorted: a set iterates in a different order every run
    j = pidx[p]
    names_final.append(p + "_r")
    final[(final == j) & (PW[:, 0] <= 0)] = len(names_final) - 1
    names_final[j] = p + "_l"
vlabel = final[wid]
# face label: the most common of its three vertices
fl = vlabel[F]
face = np.where(fl[:, 1] == fl[:, 2], fl[:, 1], fl[:, 0])

# face-level cleanup: a fragment of a part that is small next to that part's main piece and touches
# another part is confetti at a boundary -> it joins the neighbour it touches most
WF = wid[F]
ek = np.concatenate([np.sort(WF[:, [0, 1]], 1), np.sort(WF[:, [1, 2]], 1), np.sort(WF[:, [2, 0]], 1)])
ef = np.tile(np.arange(len(F)), 3)
key = ek[:, 0] * nW + ek[:, 1]
o = np.argsort(key, kind="stable")
key, ef = key[o], ef[o]
same = key[1:] == key[:-1]
FE = np.c_[ef[:-1][same], ef[1:][same]]                # face pairs sharing an edge


def face_components(lbl):
    e = FE[lbl[FE[:, 0]] == lbl[FE[:, 1]]]
    lab = np.arange(len(F))
    while True:
        a, b = lab[e[:, 0]], lab[e[:, 1]]
        mn = np.minimum(a, b)
        new = lab.copy()
        np.minimum.at(new, a, mn)
        np.minimum.at(new, b, mn)
        while True:
            nxt = new[new]
            if (nxt == new).all():
                break
            new = nxt
        if (new == lab).all():
            return lab
        lab = new


if CREASE_SNAP:
    # Step 7 (v2): part borders onto the creases where plates meet. Faces within SNAP_BAND x h of a
    # border are relabelled by a shortest-path flood from the faces outside that band (they keep their
    # part); stepping between two faces costs their centre distance x (1 + SNAP_K x crease), crease =
    # how sharply the surface folds there (0 flat .. 1 at SNAP_ANGLE or more; normals compared either
    # way up, TRELLIS normals are not reliably outward). Each side fills up to the fold, so the fronts
    # meet on it instead of where SAM's prompts happened to disagree.
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    nF = len(F)
    FN = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    FN /= np.maximum(np.linalg.norm(FN, axis=1, keepdims=True), 1e-20)
    cen = V[F].mean(1)
    ea, eb = FE[:, 0], FE[:, 1]
    step = np.linalg.norm(cen[ea] - cen[eb], axis=1) + 1e-9 * h
    crease = np.clip((1 - np.abs((FN[ea] * FN[eb]).sum(1))) / (1 - math.cos(math.radians(SNAP_ANGLE))), 0, 1)

    def graph(w):
        return coo_matrix((np.r_[w, w], (np.r_[ea, eb], np.r_[eb, ea])), shape=(nF, nF)).tocsr()
    border = np.zeros(nF, bool)
    cut = face[ea] != face[eb]
    border[ea[cut]] = border[eb[cut]] = True
    dist_b = dijkstra(graph(step), indices=np.nonzero(border)[0], min_only=True, limit=SNAP_BAND * h)
    band = np.isfinite(dist_b)
    _, _, src = dijkstra(graph(step * (1 + SNAP_K * crease)), indices=np.nonzero(~band)[0], min_only=True,
                         return_predecessors=True)
    reach = band & (src >= 0)
    snapped = face.copy()
    snapped[reach] = face[src[reach]]
    changed = int((snapped != face).sum())
    face = snapped
    log(f"crease snap: band {int(band.sum())} faces ({100 * band.mean():.1f}%), {changed} changed part; "
        f"{int((crease > 0.5).sum())} crease edges of {len(crease)}")
    RESULTS["crease_snap"] = {"band_faces": int(band.sum()), "changed_faces": changed}

for rnd in range(3):
    comp = face_components(face)
    size = np.bincount(comp, minlength=len(F))
    biggest = np.zeros(face.max() + 1, np.int64)
    np.maximum.at(biggest, face, size[comp])
    border = np.zeros(len(F), bool)
    diff = face[FE[:, 0]] != face[FE[:, 1]]
    touch = np.zeros(len(F), bool)
    touch[FE[diff, 0]] = True
    touch[FE[diff, 1]] = True
    comp_touch = np.zeros(len(F), bool)
    comp_touch[comp[touch]] = True
    small = (size[comp] < np.maximum(300, 0.05 * biggest[face])) & comp_touch[comp]
    log(f"cleanup round {rnd}: {int(small.sum())} faces in {len(np.unique(comp[small]))} fragments")
    if not small.any():
        break
    face = np.where(small, -1, face)
    while (face < 0).any():
        a, b = face[FE[:, 0]], face[FE[:, 1]]
        votes_f = np.zeros((len(F), int(face.max()) + 1))
        m1 = (a < 0) & (b >= 0)
        np.add.at(votes_f, (FE[m1, 0], b[m1]), 1)
        m2 = (b < 0) & (a >= 0)
        np.add.at(votes_f, (FE[m2, 1], a[m2]), 1)
        got = (face < 0) & (votes_f.sum(1) > 0)
        if not got.any():
            break
        face[got] = votes_f[got].argmax(1)
    face[face < 0] = 0

# small loose pieces (separate geometry, so they touch no other part) go to the part whose main
# piece is nearest in space: a strap fleck by the hip belongs to the skirt, not the arm above it
comp = face_components(face)
size = np.bincount(comp, minlength=len(F))
biggest = np.zeros(face.max() + 1, np.int64)
np.maximum.at(biggest, face, size[comp])
loose = size[comp] < 0.05 * biggest[face]
cent = V[F].mean(1)
main = np.nonzero(~loose)[0]
ft = kdtree.KDTree(len(main))
for i, fi in enumerate(main):
    ft.insert(cent[fi], i)
ft.balance()
moved = 0
for cid in np.unique(comp[loose]):
    fs = np.nonzero(comp == cid)[0]
    near = face[main[ft.find(cent[fs].mean(0))[1]]]
    if near != face[fs[0]]:
        moved += len(fs)
    face[fs] = near
log(f"loose pieces: {len(np.unique(comp[loose]))} pieces, {int(loose.sum())} faces, {moved} faces changed part")
used = sorted(set(face.tolist()))
remap = {old: new for new, old in enumerate(used)}
face = np.array([remap[x] for x in face], np.int32)
names_final = [names_final[o] for o in used]
counts = np.bincount(face, minlength=len(names_final))
np.save(os.path.join(OUT, "labels_face.npy"), face)
json.dump({"parts": names_final, "faces": counts.tolist()}, open(os.path.join(OUT, "parts.json"), "w"), indent=1)
log("PARTS " + ", ".join(f"{nm} {c}" for nm, c in zip(names_final, counts)))
RESULTS["faces_by_part"] = {nm: int(c) for nm, c in zip(names_final, counts)}

# --- part-coloured renders -------------------------------------------------------------------
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
           (170, 110, 40), (255, 250, 200), (128, 0, 0), (170, 255, 195), (128, 128, 0), (255, 215, 180)]
colattr = me.color_attributes.new("part", "BYTE_COLOR", "CORNER")
loop_face = np.repeat(np.arange(len(F)), 3)
rgb = np.array([PALETTE[i % len(PALETTE)] for i in range(len(names_final))], np.float32) / 255
lc = np.c_[rgb[face[loop_face]], np.ones(len(loop_face))]
colattr.data.foreach_set("color", lc.astype(np.float32).ravel())
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "VERTEX"
sc.render.resolution_x = sc.render.resolution_y = 900
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.2, 0.2, 0.22)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = 1.1 * h
centre = Vector(((V[:, 0].min() + V[:, 0].max()) / 2, (V[:, 1].min() + V[:, 1].max()) / 2, (V[:, 2].min() + V[:, 2].max()) / 2))


def shot(yaw, path, elev=10):
    a, e = math.radians(yaw), math.radians(elev)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = centre + d * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


views = [shot(y, os.path.join(OUT, f"parts_{y:03d}.png")) for y in (0, 90, 180, 270)]
sheet = Image.new("RGB", (900 * 4 + 260, 900), (30, 30, 34))
for i, im in enumerate(views):
    sheet.paste(im, (i * 900, 0))
d = ImageDraw.Draw(sheet)
for i, nm in enumerate(names_final):
    d.rectangle((3610, 20 + 30 * i, 3630, 40 + 30 * i), fill=PALETTE[i % len(PALETTE)])
    d.text((3640, 24 + 30 * i), f"{nm} ({counts[i]})", fill=(240, 240, 240))
sheet.save(os.path.join(OUT, "PARTS_SHEET.png"))

# --- one object per part, export -------------------------------------------------------------
parts_objs = []
for j, nm in enumerate(names_final):
    fj = F[face == j]
    uniq, inv = np.unique(fj, return_inverse=True)
    pm = bpy.data.meshes.new(nm)
    pm.from_pydata(V[uniq].tolist(), [], inv.reshape(-1, 3).tolist())
    pm.update()
    po = bpy.data.objects.new(nm, pm)
    sc.collection.objects.link(po)
    po.color = PALETTE[j % len(PALETTE)] + (255,)
    po.color = tuple(x / 255 for x in po.color)
    parts_objs.append(po)
mesh.hide_render = True
bpy.ops.object.select_all(action="DESELECT")
for o in parts_objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts_objs[0]
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "input_parts.glb"), use_selection=True, export_materials="NONE")
log("exported", len(parts_objs), "objects:", ", ".join(o.name for o in parts_objs))
sc.display.shading.color_type = "OBJECT"

# preview: pull each part away from the body centre (NOT completed: shells with holes)
body_c = np.array(centre)
for o in parts_objs:
    pc = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", pc)
    pc = pc.reshape(-1, 3) @ np.array(o.matrix_world)[:3, :3].T + np.array(o.matrix_world)[:3, 3]
    c = pc.mean(0)
    off = (c - body_c) * np.array([0.9, 0.0, 0.55])
    if o.name.startswith("head"):
        off = np.array([0, 0, 0.12 * h])
    o.location = Vector(off)
cam.data.ortho_scale = 1.6 * h
pv = [shot(y, os.path.join(OUT, f"split_preview_{y:03d}.png")) for y in (0, 35)]
sp = Image.new("RGB", (1800, 900))
sp.paste(pv[0], (0, 0)); sp.paste(pv[1], (900, 0))
sp.save(os.path.join(OUT, "split_preview.png"))
if DIAG_OUT:
    json.dump({"step": "5 label (SAM masks -> part per face)", "glb": meta["glb"], "out": WORK,
               "settings": {"cameras": len(meta["cams"]), "facing_power": FACING_POWER, "min_vote": MIN_VOTE,
                            "min_island_verts": MIN_ISLAND, "min_instance_score": MIN_INSTANCE,
                            "skip": sorted("/".join(s) for s in SKIP), "priority": PRIORITY,
                            "belt_gate": BELT_GATE if BELT_GATING else None,
                            "min_by_prompt": MIN_BY_PROMPT if BELT_GATING else None, "dirs": MAX_DIRS,
                            "crease_snap": {"band_h": SNAP_BAND, "k": SNAP_K, "angle_deg": SNAP_ANGLE}
                            if CREASE_SNAP else None,
                            "prompt_to_part": PROMPT_PART},
               "results": RESULTS}, open(DIAG_OUT, "w"), indent=1)
log("LABEL_OK")
