"""Regroup cut armour pieces into game slots, splitting limbs at the joints by the skeleton.

    .venv-bpy/Scripts/python.exe armour_slots.py <body_rigged.glb> <roles.json> <shells_parts.glb> <out_dir>

The cut (explode_label.py) says what is armour and roughly which kind. Where a limb's plates divide
is a joint, and the skeleton knows joints exactly while SAM's masks are fuzzy there. So each face of a
limb piece takes the side of the joint whose bones weigh most on the body skin nearest to it:

    slot        from cut pieces           split by                          rides
    chest       torso                     -                                 chest
    belt        belt (+ skirt)            -                                 hips (root)
    shoulder_*  pauldron, arm             collarbone + upper arm side       upper arm (+ collarbone)
    gauntlet_*  arm, gauntlet             forearm + hand side               forearm, hand
    pants_*     leg, boot                 thigh side of the knee            thigh
    boot_*      leg, boot                 shin + foot + toes side           shin, foot, toes
    loincloth   loincloth                 -                                 hips, up to 50 % thighs at the hem
    (head)      head                      dropped: not armour; the helmet slot needs a helmet model
    (body)      body                      dropped: what is left of a body a piece was cut from

Then loose bits farther than STRAY_GAP from the rest of their slot piece are dropped (stray cut bits).
Writes <out_dir>/slots_parts.glb (one mesh per slot piece, paint kept) and slots.json.
"""
import json
import os
import sys

import bpy
import bmesh
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

BODY, ROLES, SHELLS, OUT = (os.path.abspath(a) for a in sys.argv[1:5])
os.makedirs(OUT, exist_ok=True)
STRAY_GAP = 0.01        # x suit height: a bit this far from the rest of its piece is dropped
K = 4                   # nearest body vertices per face


def log(*a):
    print("[slots]", *a, flush=True)


def verts(o):
    V = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", V)
    return V.reshape(-1, 3).astype(np.float64)


def faces(o):
    T = np.empty(len(o.data.polygons) * 3, np.int64)
    o.data.polygons.foreach_get("vertices", T)        # imported glTF: all triangles
    return T.reshape(-1, 3)


def bake(objs):
    for o in objs:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world.identity()


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.data.objects if o not in before]


bpy.ops.wm.read_factory_settings(use_empty=True)
roles = json.load(open(ROLES))

# --- body: rest skin positions and bone weights ---------------------------------------------------
body_objs = import_glb(BODY)
body = max((o for o in body_objs if o.type == "MESH" and len(o.vertex_groups)), key=lambda o: len(o.data.vertices))
bake([body])
B = verts(body)
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
tree_body = cKDTree(B)
for o in body_objs:
    bpy.data.objects.remove(o, do_unlink=True)


def col(bone):
    return gnames.index(bone)


# --- shells -----------------------------------------------------------------------------------------
shell_objs = import_glb(SHELLS)
parts = {o.name.split(".")[0]: o for o in shell_objs if o.type == "MESH"}
for o in shell_objs:
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
bake(parts.values())
H = float(np.ptp(np.concatenate([verts(o) for o in parts.values()])[:, 2]))
log("pieces", sorted(parts), "suit height", round(H, 4))


def face_weights(o):
    V, T = verts(o), faces(o)
    d, idx = tree_body.query(V[T].mean(1), k=K)
    inv = 1.0 / np.maximum(d, 1e-9)
    return (W[idx] * inv[:, :, None]).sum(1) / inv.sum(1, keepdims=True)


def side_of(name):
    return name[-1] if name[-2:] in ("_l", "_r") else None


label = {}           # part name -> per-face slot name (None = dropped)
for name, o in parts.items():
    base, s = (name[:-2], side_of(name)) if side_of(name) else (name, None)
    n = len(o.data.polygons)
    if base == "torso":
        label[name] = np.full(n, "chest", object)
    elif base in ("belt", "skirt"):
        label[name] = np.full(n, "belt", object)
    elif base == "loincloth":
        label[name] = np.full(n, "loincloth", object)
    elif base == "body":                                            # a cut outfit's leftover: not a slot
        label[name] = np.full(n, None, object)
    elif base == "head":
        label[name] = np.full(n, None, object)
    elif base == "pauldron":
        label[name] = np.full(n, f"shoulder_{s}", object)
    elif base in ("arm", "gauntlet"):
        a = roles[f"arm_{s}"]
        Wf = face_weights(o)
        up = Wf[:, col(a["shoulder"])] + Wf[:, col(a["elbow"])]
        lo = Wf[:, col(a["wrist"])] + Wf[:, col(a["hand"])]
        label[name] = np.where(up > lo, f"shoulder_{s}", f"gauntlet_{s}").astype(object)
    elif base in ("leg", "boot"):
        g = roles[f"leg_{s}"]
        Wf = face_weights(o)
        up = Wf[:, col(g["hip"])]                                   # the boot is the knee down
        lo = Wf[:, col(g["knee"])] + Wf[:, col(g["ankle"])] + Wf[:, col(g["foot"])]
        label[name] = np.where(up > lo, f"pants_{s}", f"boot_{s}").astype(object)
    else:
        raise SystemExit(f"no slot rule for piece {name!r}")
    u, c = np.unique(label[name].astype(str), return_counts=True)
    log(f"{name}: " + ", ".join(f"{k} {v}" for k, v in zip(u, c)))


# --- build one mesh per slot piece ------------------------------------------------------------------
def extract(o, keep):
    """A copy of o with only the faces where keep is True."""
    c = o.copy()
    c.data = o.data.copy()
    bpy.context.scene.collection.objects.link(c)
    bm = bmesh.new()
    bm.from_mesh(c.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep[f.index]], context="FACES")
    bm.to_mesh(c.data)
    bm.free()
    return c


slot_names = sorted({v for a in label.values() for v in a if v is not None})
report = {}
for slot in slot_names:
    pieces = [extract(parts[n], label[n] == slot) for n in parts if (label[n] == slot).any()]
    bpy.ops.object.select_all(action="DESELECT")
    for p in pieces:
        p.select_set(True)
    bpy.context.view_layer.objects.active = pieces[0]
    if len(pieces) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = o.data.name = slot
    # loose bits: weld coincident verts, islands, keep those within STRAY_GAP of the kept set
    V, T = verts(o), faces(o)
    _, weld = np.unique(np.round(V / (1e-4 * H)).astype(np.int64), axis=0, return_inverse=True)
    weld = weld.ravel()
    Tw = weld[T]
    nv = int(weld.max()) + 1
    r = np.concatenate([Tw[:, 0], Tw[:, 1]])
    c = np.concatenate([Tw[:, 1], Tw[:, 2]])
    _, lab = connected_components(coo_matrix((np.ones(len(r)), (r, c)), shape=(nv, nv)), directed=False)
    flab = lab[Tw[:, 0]]
    sizes = np.bincount(flab)
    isl = [i for i in np.argsort(-sizes) if sizes[i] > 0]
    kept = {isl[0]}
    pts = {i: V[T[flab == i].ravel()] for i in isl}
    changed = True
    while changed:
        changed = False
        tree = cKDTree(np.concatenate([pts[i] for i in kept]))
        for i in isl:
            if i not in kept and tree.query(pts[i], k=1)[0].min() < STRAY_GAP * H:
                kept.add(i)
                changed = True
    keep = np.isin(flab, list(kept))
    dropped = int((~keep).sum())
    if dropped:
        clean = extract(o, keep)
        bpy.data.objects.remove(o, do_unlink=True)
        o = clean
        o.name = o.data.name = slot
    report[slot] = dict(faces=len(o.data.polygons), from_pieces=sorted(n for n in parts if (label[n] == slot).any()),
                        islands=len(isl), islands_dropped=len(isl) - len(kept),
                        faces_dropped_pct=round(100 * dropped / max(len(T), 1), 2))
    log(slot, report[slot])

for n, o in parts.items():
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="SELECT")
glb = os.path.join(OUT, "slots_parts.glb")
bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True)
report["_settings"] = dict(body=BODY, shells=SHELLS, stray_gap_pct_h=STRAY_GAP * 100, k_nearest=K,
                           dropped=["head"])
json.dump(report, open(os.path.join(OUT, "slots.json"), "w"), indent=1)
log("SLOTS_OK", glb)
