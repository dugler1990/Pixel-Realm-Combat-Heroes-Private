"""Find the holes in each piece, fill the small ones, show where they were.

    .venv-bpy/Scripts/python.exe hole_check.py <parts.glb> <out_dir> [--parts torso,belt] [--hole-max 0.06]
                                               [--fix <fixed_parts.glb>] [--diag <file>]

A piece's openings are its boundary edges (edges with one face), after welding the vertices the UV
seams split. Each connected run of boundary edges is one opening; its length decides what it is:
  hole     perimeter < --hole-max x figure height (default 6 %): a gap in the surface
  opening  longer: the piece's real openings (neck, arm holes, waist, sleeve ends) - kept
--fix fills every hole (bmesh holes_fill), gives the new faces the UV of the surface around them, and
writes all parts to <fixed_parts.glb> (same materials).
--clean (with --fix, step 9): first tidy the rims - delete loose islands under ISLAND_MIN of the piece's
faces, strip rim spikes (faces with 2+ open edges, EAR_PASSES times), smooth the rim line (RIM_SMOOTH
passes of the rim vertices towards their neighbours) - then fill what holes are left. HOLES_<part>.png per part: before (holes red,
openings blue) and after, from front, back, left and right. Numbers per part to holes.json / --diag.
"""
import json
import os
import sys

import bpy
import bmesh  # noqa: E402  (only importable once bpy is)
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "explode"))
from explode_common import world_verts  # noqa: E402

argv = sys.argv[1:]
CLEAN = "--clean" in argv
argv = [a for a in argv if a != "--clean"]
ISLAND_MIN, EAR_PASSES, RIM_SMOOTH = 0.01, 3, 4
opt = {}
for f in ("--parts", "--hole-max", "--fix", "--diag"):
    if f in argv:
        i = argv.index(f)
        opt[f] = argv[i + 1]
        del argv[i:i + 2]
PARTS_GLB, OUT = os.path.abspath(argv[0]), os.path.abspath(argv[1])
ONLY = set(opt["--parts"].split(",")) if "--parts" in opt else None
HOLE_MAX = float(opt.get("--hole-max", 0.06))
FIX = os.path.abspath(opt["--fix"]) if "--fix" in opt else None
DIAG_OUT = os.path.abspath(opt["--diag"]) if "--diag" in opt else None
os.makedirs(OUT, exist_ok=True)


def log(*a):
    print(*a, flush=True)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=PARTS_GLB)
parts = [o for o in bpy.data.objects if o.type == "MESH"]
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
h = float(np.ptp(np.concatenate([world_verts(o) for o in parts])[:, 2]))
sc = bpy.context.scene


def openings(bm):
    """[(edges, perimeter)] per connected run of boundary edges."""
    bnd = [e for e in bm.edges if e.is_boundary]
    parent = {}

    def find(v):
        while parent.setdefault(v, v) != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v
    for e in bnd:
        a, b = find(e.verts[0].index), find(e.verts[1].index)
        if a != b:
            parent[a] = b
    groups = {}
    for e in bnd:
        groups.setdefault(find(e.verts[0].index), []).append(e)
    return [(es, sum(e.calc_length() for e in es)) for es in groups.values()]


def markers(name, points, colour, size):
    """Small octahedra at points: boundary edges made visible in a Workbench render."""
    P = np.asarray(points, np.float32)
    if len(P) > 30000:
        P = P[np.linspace(0, len(P) - 1, 30000).astype(int)]
    oct_v = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float32) * size
    oct_f = np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]])
    V = (P[:, None, :] + oct_v[None]).reshape(-1, 3)
    F = (oct_f[None] + 6 * np.arange(len(P))[:, None, None]).reshape(-1, 3)
    me = bpy.data.meshes.new(name)
    me.from_pydata(V.tolist(), [], F.tolist())
    me.update()
    o = bpy.data.objects.new(name, me)
    sc.collection.objects.link(o)
    o.color = colour
    return o


sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "TEXTURE"
sc.display.shading.show_specular_highlight = False
sc.render.resolution_x = sc.render.resolution_y = 380
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.3, 0.3, 0.32)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
VIEWS = {"front": (0, -1, 0.15), "back": (0, 1, 0.15), "left": (1, 0, 0.15), "right": (-1, 0, 0.15)}
RED, BLUE = (1, 0.05, 0.05, 1), (0.1, 0.4, 1, 1)


def render_set(objs, P, tag, part):
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o not in objs
    for o in objs:          # markers carry a flat colour; the piece keeps its texture
        if o.name.startswith("mk_"):
            o.data.materials.clear()
            m = bpy.data.materials.new(o.name)
            m.diffuse_color = o.color
            o.data.materials.append(m)
    c = Vector(((P.min(0) + P.max(0)) / 2).tolist())
    size = float(np.ptp(P, 0).max())
    cam.data.ortho_scale = size * 1.2
    tiles = []
    for v, d in VIEWS.items():
        d = Vector(d).normalized()
        cam.location = c + d * size * 3
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(OUT, f"_{part}_{tag}_{v}.png")
        bpy.ops.render.render(write_still=True)
        tiles.append(Image.open(sc.render.filepath).convert("RGB"))
    return tiles


report = {}
try:
    font = ImageFont.truetype("arial.ttf", 18)
except OSError:
    font = ImageFont.load_default()
for o in sorted(parts, key=lambda o: o.name):
    name = o.name.split(".")[0]
    if ONLY is not None and name not in ONLY:
        continue
    o.data.transform(o.matrix_world)
    o.matrix_world.identity()
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5 * h)   # weld UV-seam splits; UVs are per loop
    bm.verts.ensure_lookup_table()
    ops = openings(bm)
    holes = [(es, p) for es, p in ops if p < HOLE_MAX * h]
    real = [(es, p) for es, p in ops if p >= HOLE_MAX * h]
    hole_pts = [(e.verts[0].co + e.verts[1].co) / 2 for es, _ in holes for e in es]
    open_pts = [(e.verts[0].co + e.verts[1].co) / 2 for es, _ in real for e in es]
    rec = {"holes": len(holes), "hole_perimeter_pct_h": round(100 * sum(p for _, p in holes) / h, 2),
           "openings": len(real), "opening_perimeters_pct_h": sorted(round(100 * p / h, 1) for _, p in real)[::-1][:8]}
    P = np.array([v.co[:] for v in bm.verts])
    before_obj = o.copy()
    before_obj.data = o.data.copy()
    sc.collection.objects.link(before_obj)
    mks = [markers(f"mk_h_{name}", [p[:] for p in hole_pts], RED, 0.0025 * h)] if hole_pts else []
    mks += [markers(f"mk_o_{name}", [p[:] for p in open_pts], BLUE, 0.0025 * h)] if open_pts else []
    before = render_set([before_obj] + mks, P, "before", name)
    for m in mks:
        bpy.data.objects.remove(m, do_unlink=True)
    after = None
    if FIX and CLEAN:
        n0 = len(bm.faces)
        # 1. loose islands (flecks, torn flaps) under ISLAND_MIN of the piece
        bm.faces.index_update()
        bm.faces.ensure_lookup_table()
        seen, small = set(), []
        for f in bm.faces:
            if f.index in seen:
                continue
            stack, comp = [f], []
            seen.add(f.index)
            while stack:
                g = stack.pop()
                comp.append(g)
                for e in g.edges:
                    for g2 in e.link_faces:
                        if g2.index not in seen:
                            seen.add(g2.index)
                            stack.append(g2)
            if len(comp) < ISLAND_MIN * n0:
                small += comp
        bmesh.ops.delete(bm, geom=small, context="FACES")
        # 2. rim spikes: faces hanging on by one edge
        ears = 0
        for _ in range(EAR_PASSES):
            spikes = [f for f in bm.faces if sum(e.is_boundary for e in f.edges) >= 2]
            if not spikes:
                break
            ears += len(spikes)
            bmesh.ops.delete(bm, geom=spikes, context="FACES")
        # 3. smooth the rim line
        for _ in range(RIM_SMOOTH):
            rim = [v for v in bm.verts if v.is_boundary]
            bmesh.ops.smooth_vert(bm, verts=rim, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        rec.update({"clean_islands_faces": len(small), "clean_spike_faces": ears})
        holes = [(es, p) for es, p in openings(bm) if p < HOLE_MAX * h]
    if FIX and holes:
        uv = bm.loops.layers.uv.active
        old = set(bm.faces)
        bmesh.ops.holes_fill(bm, edges=[e for es, _ in holes for e in es], sides=0)
        new = [f for f in bm.faces if f not in old]
        for f in new:                       # each new corner takes the UV the vertex has on the old surface
            for lp in f.loops:
                src = next((l2 for l2 in lp.vert.link_loops if l2.face in old), None)
                if src is not None and uv is not None:
                    lp[uv].uv = src[uv].uv
        bmesh.ops.recalc_face_normals(bm, faces=new)
        bm.to_mesh(o.data)
        o.data.update()
        ops2 = openings(bm)
        left = [(es, p) for es, p in ops2 if p < HOLE_MAX * h]
        rec.update({"filled_faces": len(new), "holes_after": len(left)})
        left_pts = [(e.verts[0].co + e.verts[1].co) / 2 for es, _ in left for e in es]
        mks = [markers(f"mk_h2_{name}", [p[:] for p in left_pts], RED, 0.0025 * h)] if left_pts else []
        after = render_set([o] + mks, P, "after", name)
        for m in mks:
            bpy.data.objects.remove(m, do_unlink=True)
    else:
        bm.to_mesh(o.data)
        o.data.update()
    bm.free()
    bpy.data.objects.remove(before_obj, do_unlink=True)
    report[name] = rec
    log(f"{name:12s} holes {rec['holes']:4d} (perimeter {rec['hole_perimeter_pct_h']:.1f}% h), "
        f"openings {rec['openings']} {rec['opening_perimeters_pct_h']}"
        + (f"; cleaned {rec['clean_islands_faces']} island + {rec['clean_spike_faces']} spike faces"
           if "clean_spike_faces" in rec else "")
        + (f"; filled {rec['filled_faces']} faces, holes left {rec['holes_after']}" if "holes_after" in rec else ""))
    rows = [("before: red = hole, blue = real opening", before)] + ([("after filling", after)] if after else [])
    T = 380
    sheet = Image.new("RGB", (T * 4, (T + 26) * len(rows)), (25, 25, 28))
    d = ImageDraw.Draw(sheet)
    for r, (lab, tiles) in enumerate(rows):
        d.text((6, r * (T + 26) + 4), f"{name} - {lab}", fill=(235, 235, 235), font=font)
        for c, t in enumerate(tiles):
            sheet.paste(t, (c * T, r * (T + 26) + 26))
    sheet.save(os.path.join(OUT, f"HOLES_{name}.png"))

json.dump(report, open(os.path.join(OUT, "holes.json"), "w"), indent=1)
if FIX:
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.export_scene.gltf(filepath=FIX, use_selection=True)
    log("exported", FIX)
if DIAG_OUT:
    json.dump({"step": "9 holes (find, fill the small ones)", "glb": PARTS_GLB, "out": FIX or OUT,
               "settings": {"hole_max_perimeter_h": HOLE_MAX, "parts": sorted(ONLY) if ONLY else "all",
                     "clean": {"island_min": ISLAND_MIN, "ear_passes": EAR_PASSES, "rim_smooth": RIM_SMOOTH}
                     if CLEAN else None},
               "results": {k: {kk: vv for kk, vv in v.items() if not isinstance(vv, list)} for k, v in report.items()}},
              open(DIAG_OUT, "w"), indent=1)
log("HOLES_OK")
