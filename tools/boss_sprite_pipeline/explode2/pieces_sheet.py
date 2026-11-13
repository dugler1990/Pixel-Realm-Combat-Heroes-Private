"""Each armour piece alone, painted, front-3/4 and back-3/4, with facts beside it. Blender venv.

    .venv-bpy/Scripts/python.exe pieces_sheet.py <parts.glb> <out.png> [--completed completed.json] [--slots]

<parts.glb>: explode_merge.py's shells_parts.glb (cut pieces) or armour_slots.py's slots_parts.glb (--slots).
Facts per piece: what it covers, the bones it rides, size (% of the whole suit's height), triangles,
open edges (from explode_show.py's completed.json, cut pieces only), loose bits (islands after welding
coincident vertices; "visible" = at least 0.5 % of the piece's faces), texture size. Also <out>.json.
"""
import json, math, os, sys
import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

ARGS = sys.argv[1:]
SLOTS = "--slots" in ARGS
DONE_JSON = None
if "--completed" in ARGS:
    i = ARGS.index("--completed"); DONE_JSON = os.path.abspath(ARGS[i + 1]); del ARGS[i:i + 2]
ARGS = [a for a in ARGS if a != "--slots"]
GLB, OUT = (os.path.abspath(a) for a in ARGS[:2])
TMP = os.path.splitext(OUT)[0] + "_tmp"
os.makedirs(TMP, exist_ok=True)
TILE = 300

if SLOTS:     # armour_slots.py
    RIDES = {"chest": "chest bone, 100 % (rigid)", "belt": "hips (root), 100 % (rigid)",
             "shoulder": "collarbone or upper arm (each vertex one)", "gauntlet": "forearm or hand (each vertex one)",
             "pants": "thigh or shin (each vertex one)", "boot": "foot or toes (each vertex one)"}
    COVERS = {"chest": "chest, belly, back, collar", "belt": "belt + hip plates",
              "shoulder": "pauldron + upper arm, down to the elbow", "gauntlet": "elbow down: forearm + hand",
              "pants": "thigh + knee + shin, down to the ankle", "boot": "ankle down"}
else:         # explode_label.py cut pieces
    RIDES = {"torso": "chest bone, 100 % (rigid)", "belt": "hips (root), 100 % (rigid)",
             "pauldron": "75 % upper arm, 25 % collarbone", "arm": "upper arm or forearm (each vertex one)",
             "gauntlet": "forearm or hand (each vertex one)", "leg": "thigh or shin (each vertex one)",
             "boot": "ankle or toes (each vertex one)", "head": "head 100 % (not armour: drop)"}
    COVERS = {"torso": "chest, belly, lower back, shoulders", "belt": "hips, waist",
              "pauldron": "shoulder, top of upper arm", "arm": "upper arm + forearm", "gauntlet": "wrist + hand",
              "leg": "thigh + knee + shin", "boot": "foot", "head": "his head (face + bun)"}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
parts = {}
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    o.data.transform(o.matrix_world); o.parent = None; o.matrix_world.identity()
    parts[o.name.split(".")[0]] = o
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
done = json.load(open(DONE_JSON)) if DONE_JSON else {}


def verts(o):
    V = np.empty(len(o.data.vertices) * 3, np.float32); o.data.vertices.foreach_get("co", V)
    return V.reshape(-1, 3).astype(np.float64)


ALL = np.concatenate([verts(o) for o in parts.values()])
H = float(np.ptp(ALL[:, 2]))


def islands(o):
    """Loose pieces after welding coincident verts: count, and the share of faces outside the largest."""
    V = verts(o)
    key = np.round(V / (1e-4 * H)).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    T = np.empty(len(o.data.polygons) * 3, np.int64); o.data.polygons.foreach_get("vertices", T)
    T = weld.ravel()[T].reshape(-1, 3)
    n = int(weld.max()) + 1
    r = np.concatenate([T[:, 0], T[:, 1]]); c = np.concatenate([T[:, 1], T[:, 2]])
    k, lab = connected_components(coo_matrix((np.ones(len(r)), (r, c)), shape=(n, n)), directed=False)
    fl = lab[T[:, 0]]
    cnt = np.bincount(fl)
    big = cnt.argmax()
    # bits big enough to see (>0.5 % of the piece's faces)
    visible = int((cnt >= 0.005 * len(T)).sum())
    return int((cnt > 0).sum()), visible, 1 - cnt[big] / len(T)


def tex_size(o):
    for s in o.material_slots:
        if s.material and s.material.use_nodes:
            for nd in s.material.node_tree.nodes:
                if nd.type == "TEX_IMAGE" and nd.image:
                    return tuple(nd.image.size)
    return None


sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "TEXTURE"
sc.display.shading.show_specular_highlight = False
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new("w") if sc.world is None else sc.world
sc.display.shading.background_type = "VIEWPORT" if hasattr(sc.display.shading, "background_type") else None
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.type = "ORTHO"; sc.camera = cam
sc.render.resolution_x = sc.render.resolution_y = TILE


def shot(o, yaw, path, elev=12):
    for p in parts.values():
        p.hide_render = p is not o
    P = verts(o); lo, hi = P.min(0), P.max(0)
    c = Vector(((lo + hi) / 2).tolist())
    a, e = math.radians(yaw), math.radians(elev)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    span = float(np.ptp(P, 0).max())
    cam.location = c + d * (3 * span + 1)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = 1.15 * span; cam.data.clip_end = 1000
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


order = (["chest", "belt", "shoulder_l", "shoulder_r", "gauntlet_l", "gauntlet_r", "pants_l", "pants_r", "boot_l", "boot_r"]
         if SLOTS else ["torso", "belt", "pauldron_l", "pauldron_r", "arm_l", "arm_r", "gauntlet_l", "gauntlet_r",
                        "leg_l", "leg_r", "boot_l", "boot_r", "head"])
order = [n for n in order if n in parts] + sorted(set(parts) - set(order))
per_row, INFO = 2, 400
cell_w = 2 * TILE + INFO
rows = math.ceil(len(order) / per_row)
sheet = Image.new("RGB", (per_row * cell_w, rows * TILE + 40), (34, 34, 38))
dr = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("arial.ttf", 15); bold = ImageFont.truetype("arialbd.ttf", 19)
except OSError:
    font = bold = ImageFont.load_default()
dr.text((8, 10), f"{os.path.basename(GLB)}, painted. Sizes in % of the whole suit's height. "
                 f"Left: front 3/4, right: back 3/4. 'He' = the wearer: _l is his left.", fill=(220, 220, 220), font=font)
facts = {}
for j, n in enumerate(order):
    o = parts[n]
    r, k = divmod(j, per_row)
    x0, y0 = k * cell_w, 40 + r * TILE
    sheet.paste(shot(o, 35, os.path.join(TMP, f"{n}_f.png")), (x0, y0))
    sheet.paste(shot(o, 215, os.path.join(TMP, f"{n}_b.png")), (x0 + TILE, y0))
    P = verts(o)
    size = np.ptp(P, 0) / H * 100
    total, vis, stray = islands(o)
    base = n[:-2] if n[-2:] in ("_l", "_r") else n
    d = done.get(n, {})
    f = dict(tris=len(o.data.polygons), size_pct=[round(float(v)) for v in size], loose_bits=total,
             visible_bits=vis, stray_faces_pct=round(stray * 100, 1), open_edges=d.get("shell_open_edges"),
             texture=tex_size(o), rides=RIDES.get(base), covers=COVERS.get(base))
    facts[n] = f
    tx, ty = x0 + 2 * TILE + 10, y0 + 10
    dr.text((tx, ty), n, fill=(255, 220, 120), font=bold); ty += 28
    lines = [f"covers: {f['covers']}",
             f"rides: {f['rides']}",
             f"size: {f['size_pct'][0]} wide x {f['size_pct'][1]} deep x {f['size_pct'][2]} tall",
             f"triangles: {f['tris']:,}",
             f"open edges: {f['open_edges'] if f['open_edges'] is not None else '-'}",
             f"loose bits: {vis} visible ({total} total),",
             f"  {f['stray_faces_pct']} % of faces off the main piece",
             f"texture: {f['texture'][0]} px" if f['texture'] else "texture: none"]
    for ln in lines:
        dr.text((tx, ty), ln, fill=(225, 225, 225), font=font); ty += 21
sheet.save(OUT)
json.dump(facts, open(os.path.splitext(OUT)[0] + ".json", "w"), indent=1)
print("PIECES_OK", OUT, flush=True)
