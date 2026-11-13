"""What does HoloPart buy? Each piece alone, cut shell vs shell + HoloPart infill: how much do you see through it?

    .venv-bpy/Scripts/python.exe holo_value.py <out_dir> <label>=<shells_parts.glb>,<merged_parts.glb>[,<holopart_output.glb>] [...] [--diag <file>]

The optional third file is HoloPart's own output (parts named geometry_<i>, matched to the shells by
bounding-box centre): what HoloPart made, before explode_merge keeps only part of it.

Every part is rendered alone from 6 directions (front, back, left, right, above, below), front faces
white and back faces red: a red pixel is the inside of the piece seen through a hole or an open end
(what you would see of an inventory item, or of a piece worn without its neighbours). Per part and
label: see-through % (red / all piece pixels, mean over the 6 views) for the shell and the merged piece,
and how much HoloPart removed. Writes <out_dir>/HOLO_VALUE.md, holo_value.json and HOLO_VALUE.png
(per part, the shell and merged piece from the view where the shell shows most red).
"""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode"))
from explode_common import match_by_centre  # noqa: E402

argv = sys.argv[1:]
# --recalc: make every piece's face normals consistent (outward) before rendering. A red pixel can be a
# hole or a face that points inward (TRELLIS normals are not reliably outward); with --recalc only holes
# and real openings stay red.
RECALC = "--recalc" in argv
argv = [a for a in argv if a != "--recalc"]
DIAG_OUT = None
if "--diag" in argv:
    i = argv.index("--diag")
    DIAG_OUT = os.path.abspath(argv[i + 1])
    del argv[i:i + 2]
OUT = os.path.abspath(argv[0])
SETS = [(a.split("=", 1)[0], [os.path.abspath(p) for p in a.split("=", 1)[1].split(",")]) for a in argv[1:]]
os.makedirs(OUT, exist_ok=True)
RES = 256
DIRS = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (1, 0, 0), "right": (-1, 0, 0), "above": (0, 0.01, 1),
        "below": (0, 0.01, -1)}

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.eevee.taa_render_samples = 1
sc.render.filter_size = 0.0
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.film_transparent = True
sc.view_settings.view_transform = "Standard"
mat = bpy.data.materials.new("frontback")
mat.use_nodes = True
mat.use_backface_culling = False
nt = mat.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
o_ = nt.nodes.new("ShaderNodeOutputMaterial")
mix = nt.nodes.new("ShaderNodeMixShader")
geo = nt.nodes.new("ShaderNodeNewGeometry")
ef, eb = nt.nodes.new("ShaderNodeEmission"), nt.nodes.new("ShaderNodeEmission")
ef.inputs[0].default_value = (1, 1, 1, 1)
eb.inputs[0].default_value = (1, 0, 0, 1)
nt.links.new(geo.outputs["Backfacing"], mix.inputs[0])
nt.links.new(ef.outputs[0], mix.inputs[1])
nt.links.new(eb.outputs[0], mix.inputs[2])
nt.links.new(mix.outputs[0], o_.inputs[0])
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = {}
    for o in [o for o in bpy.data.objects if o not in before]:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
            continue
        o.data.materials.clear()
        o.data.materials.append(mat)
        o.hide_render = True
        if RECALC:
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            bm.to_mesh(o.data)
            bm.free()
            o.data.update()
        objs[o.name.split(".")[0]] = o
    return objs


def shoot(o, d, path):
    P = np.array([o.matrix_world @ v.co for v in o.data.vertices])
    c = Vector(((P.min(0) + P.max(0)) / 2).tolist())
    size = float(np.ptp(P, 0).max())
    d = Vector(d).normalized()
    cam.location = c + d * size * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = size * 1.15
    cam.data.clip_end = size * 10
    o.hide_render = False
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    o.hide_render = True
    px = np.asarray(Image.open(path).convert("RGBA")).astype(int)
    on = px[..., 3] > 128
    red = on & (px[..., 0] > 128) & (px[..., 1] < 100)
    return 100.0 * red.sum() / max(on.sum(), 1)


KIND_NAMES = {"shell": "cut piece", "merged": "+ HoloPart infill (merge)", "raw": "HoloPart output"}
res = {}
tmp = os.path.join(OUT, "_frames")
os.makedirs(tmp, exist_ok=True)
for label, files in SETS:
    kinds = {"shell": load(files[0]), "merged": load(files[1])}
    if len(files) > 2:
        kinds["raw"] = match_by_centre(load(files[2]), kinds["shell"])
    res[label] = {}
    for part in sorted(kinds["shell"]):
        row = {}
        for kind, objs in kinds.items():
            if part not in objs:
                continue
            row[kind] = {v: round(shoot(objs[part], d, os.path.join(tmp, f"{label}_{part}_{kind}_{v}.png")), 2)
                         for v, d in DIRS.items()}
        res[label][part] = row
        print(f"{label:10s} {part:12s} see-through " + "  ".join(
            f"{k} {np.mean(list(row[k].values())):5.1f}%" for k in row), flush=True)
    for objs in kinds.values():
        for o in set(objs.values()):
            bpy.data.objects.remove(o, do_unlink=True)

labels = [lb for lb, _ in SETS]
KINDS = [k for k in KIND_NAMES if any(k in r for lb in labels for r in res[lb].values())]
lines = ["# HoloPart value: see-through % of each piece alone (red = inside seen through a hole / open end)", "",
         "Mean over 6 views (front, back, left, right, above, below). Lower is better.", ""]
lines.append("| part | " + " | ".join(f"{lb} {KIND_NAMES[k]}" for lb in labels for k in KINDS) + " |")
lines.append("|---|" + "---|" * (len(KINDS) * len(labels)))
parts = sorted({p for lb in labels for p in res[lb]})
summary = {}
for p in parts:
    cells = []
    for lb in labels:
        row = res[lb].get(p, {})
        cells += [f"{np.mean(list(row[k].values())):.1f}" if k in row else "" for k in KINDS]
    lines.append(f"| {p} | " + " | ".join(cells) + " |")
for lb in labels:
    summary[lb] = {k: round(float(np.mean([np.mean(list(r[k].values())) for r in res[lb].values() if k in r])), 2)
                   for k in KINDS if any(k in r for r in res[lb].values())}
lines += ["", "| set (mean over parts) | " + " | ".join(KIND_NAMES[k] for k in KINDS) + " |",
          "|---|" + "---|" * len(KINDS)]
lines += [f"| {lb} | " + " | ".join(f"{v[k]:.1f}%" if k in v else "" for k in KINDS) + " |" for lb, v in summary.items()]
open(os.path.join(OUT, "HOLO_VALUE.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
json.dump(res, open(os.path.join(OUT, "holo_value.json"), "w"), indent=1)

# sheet: per part and set, shell vs merged from the view where the shell shows the most red
try:
    font = ImageFont.truetype("arial.ttf", 14)
except OSError:
    font = ImageFont.load_default()
T, nk = 200, len(KINDS)
sheet = Image.new("RGB", (T * nk * len(labels), (T + 20) * len(parts) + 20), (40, 40, 44))
d = ImageDraw.Draw(sheet)
for c, lb in enumerate(labels):
    d.text((c * nk * T + 6, 2), f"{lb}: " + " | ".join(KIND_NAMES[k] for k in KINDS), fill=(235, 235, 235), font=font)
for r, p in enumerate(parts):
    for c, lb in enumerate(labels):
        row = res[lb].get(p)
        if not row:
            continue
        v = max(row["shell"], key=row["shell"].get)
        for k, kind in enumerate(KINDS):
            f = os.path.join(tmp, f"{lb}_{p}_{kind}_{v}.png")
            if kind in row and os.path.isfile(f):
                im = Image.open(f).convert("RGBA").resize((T, T))
                bg = Image.new("RGBA", (T, T), (90, 90, 96, 255))
                bg.alpha_composite(im)
                sheet.paste(bg.convert("RGB"), ((nk * c + k) * T, 20 + r * (T + 20) + 20))
        d.text((nk * c * T + 6, 20 + r * (T + 20) + 2),
               f"{p} ({v}): " + " -> ".join(f"{row[k][v]:.1f}%" for k in KINDS if k in row),
               fill=(235, 235, 235), font=font)
sheet.save(os.path.join(OUT, "HOLO_VALUE.png"))
if DIAG_OUT:
    json.dump({"step": "8 HoloPart value (see-through % of each piece alone)", "out": OUT,
               "settings": {"views": list(DIRS), "res_px": RES, "sets": dict(SETS)}, "results": summary},
              open(DIAG_OUT, "w"), indent=1)
print("HOLO_VALUE_OK", os.path.join(OUT, "HOLO_VALUE.md"))
