"""Step 7: each part = its original shell (TRELLIS surface + paint) + HoloPart's surface only where
the shell has none.

    .venv-bpy/Scripts/python.exe explode_merge.py <work_dir> [completed.glb]

Without completed.glb: only shells_parts.glb (the textured shells, one object per part).

The shell is the part's faces of the original textured mesh (cams.json "glb" + labels_face.npy).
From the completed part a face is kept as infill when its centre is farther than KEEP_FROM_SHELL
(x height) from the shell, or when the nearest shell vertex lies on the shell's cut edge (the infill
then continues past the rim instead of leaving a crack). Infill faces take the colour of the shell
vertex nearest their centre (all three corners get its UV: flat colour, no smear across charts).

Writes merged_parts.glb and shells_parts.glb (one object per part, the original material) and MERGED.png (per part, from
the back-3/4 and below: shell vs merged, holes show red).
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector, kdtree
from PIL import Image, ImageDraw

from explode_common import fill_unwritten_texels, match_by_centre, world_verts

WORK = os.path.abspath(sys.argv[1])
DONE = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
KEEP_FROM_SHELL = 0.006
TILE = 300


def log(*a):
    print(*a, flush=True)


def tris(o):
    t = np.empty(len(o.data.polygons) * 3, np.int64)
    o.data.polygons.foreach_get("vertices", t)
    return t.reshape(-1, 3)


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
meta = json.load(open(os.path.join(WORK, "cams.json")))
names = json.load(open(os.path.join(WORK, "parts.json")))["parts"]
labels = np.load(os.path.join(WORK, "labels_face.npy"))
bpy.ops.import_scene.gltf(filepath=meta["glb"])
mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not mesh]:
    bpy.data.objects.remove(o, do_unlink=True)
mesh.data.transform(mesh.matrix_world)
mesh.parent = None
mesh.matrix_world.identity()
mat = mesh.data.materials[0]
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
for l in list(bsdf.inputs["Metallic"].links):
    mat.node_tree.links.remove(l)
bsdf.inputs["Metallic"].default_value = 0.0
img = bsdf.inputs["Base Color"].links[0].from_node.image
fill_unwritten_texels(img)
assert len(labels) == len(mesh.data.polygons), "labels_face.npy does not match the mesh"
h = float(np.ptp(world_verts(mesh)[:, 2]))

# shells: one slot per part (all the same material), then separate by slot
for _ in names[1:]:
    mesh.data.materials.append(mat)
mesh.data.polygons.foreach_set("material_index", labels.astype(np.int32))
mesh.data.attributes.new("part", "INT", "FACE").data.foreach_set("value", labels.astype(np.int32))
bpy.context.view_layer.objects.active = mesh
mesh.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="MATERIAL")
bpy.ops.object.mode_set(mode="OBJECT")
shells = {}
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    pid = np.empty(len(o.data.polygons), np.int32)   # separate drops unused slots: the index is lost
    o.data.attributes["part"].data.foreach_get("value", pid)
    o.name = o.data.name = names[int(pid[0])]
    o.data.polygons.foreach_set("material_index", np.zeros_like(pid))
    o.data.materials.clear()
    o.data.materials.append(mat)
    shells[o.name] = o
log("shells:", len(shells))
if DONE is None:
    for o in shells.values():
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(WORK, "shells_parts.glb"), use_selection=True)
    log("SHELLS_OK")
    sys.exit(0)

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=DONE)
done = {}
for o in [o for o in bpy.data.objects if o not in before and o.type == "MESH"]:
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world.identity()
    done[o.data.name.split(".")[0]] = o
for o in [o for o in bpy.data.objects if o not in before and o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
if not set(done) & set(shells):
    done = match_by_centre(done, shells, log)

stats = {}
for n in names:
    S, C = shells[n], done[n]
    VS, FS = world_verts(S), tris(S)
    # cut edge of the shell, on the position-welded graph (UV seams are not cuts)
    _, wid = np.unique(np.round(VS / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
    wid = wid.ravel()
    E = np.sort(wid[np.concatenate([FS[:, [0, 1]], FS[:, [1, 2]], FS[:, [2, 0]]])], axis=1)
    ue, cnt = np.unique(E, axis=0, return_counts=True)
    rim_w = np.zeros(wid.max() + 1, bool)
    rim_w[ue[cnt == 1].ravel()] = True
    rim = rim_w[wid]
    # per-vertex UV of the shell (TRELLIS splits vertices at seams: one UV per vertex)
    uv_l = np.empty(len(S.data.loops) * 2, np.float32)
    S.data.uv_layers.active.data.foreach_get("uv", uv_l)
    lv = np.empty(len(S.data.loops), np.int64)
    S.data.loops.foreach_get("vertex_index", lv)
    uv_v = np.zeros((len(VS), 2), np.float32)
    uv_v[lv] = uv_l.reshape(-1, 2)

    tree = kdtree.KDTree(len(VS))
    for i, p in enumerate(VS):
        tree.insert(p, i)
    tree.balance()
    VC, FC = world_verts(C), tris(C)
    cen = VC[FC].mean(1)
    near = np.empty(len(cen), np.int64)
    dist = np.empty(len(cen))
    for i, p in enumerate(cen):
        _, near[i], dist[i] = tree.find(p)
    keep = (dist > KEEP_FROM_SHELL * h) | rim[near]
    FK = FC[keep]
    uniq, inv = np.unique(FK, return_inverse=True)
    inf = bpy.data.meshes.new(n + "_infill")
    inf.from_pydata(VC[uniq].tolist(), [], inv.reshape(-1, 3).tolist())
    uvl = inf.uv_layers.new(name=S.data.uv_layers.active.name)
    uvl.data.foreach_set("uv", np.repeat(uv_v[near[keep]], 3, axis=0).ravel())
    inf.materials.append(mat)
    io = bpy.data.objects.new(n + "_infill", inf)
    sc.collection.objects.link(io)
    stats[n] = {"shell_faces": len(FS), "shell_rim_verts": int(rim.sum()), "infill_faces": int(keep.sum()),
                "completed_faces": len(FC)}
    log(f"{n:12s} shell {len(FS):7d} | infill {int(keep.sum()):6d} of {len(FC)} completed faces")
json.dump(stats, open(os.path.join(WORK, "merged.json"), "w"), indent=1)

# render: shell vs merged, back-3/4 and from below (where the cuts are); holes show the red world
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "TEXTURE"
sc.display.shading.show_backface_culling = True
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.8, 0.1, 0.1)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.clip_end = 1000
sc.render.resolution_x = sc.render.resolution_y = TILE
tmp = os.path.join(WORK, "merge_tmp")
os.makedirs(tmp, exist_ok=True)
infill = {n: bpy.data.objects[n + "_infill"] for n in names}


def shot(objs, yaw, elev, path):
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o not in objs
    P = np.concatenate([world_verts(o) for o in objs])
    c, s = Vector(((P.min(0) + P.max(0)) / 2).tolist()), float(np.ptp(P, 0).max())
    a, e = math.radians(yaw), math.radians(elev)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = c + d * (3 * s + 1)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = 1.15 * s
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


VIEWS = (("shell back", 215, 15, False), ("merged back", 215, 15, True),
         ("shell below", 35, -50, False), ("merged below", 35, -50, True))
per_row = 2
rows = math.ceil(len(names) / per_row)
sheet = Image.new("RGB", (TILE * 4 * per_row, rows * (TILE + 20) + 26), (30, 30, 34))
dr = ImageDraw.Draw(sheet)
for k in range(per_row):
    for i, (t, *_r) in enumerate(VIEWS):
        dr.text((k * 4 * TILE + i * TILE + 6, 6), t, fill=(220, 220, 220))
for j, n in enumerate(names):
    r, k = divmod(j, per_row)
    x0, y0 = k * 4 * TILE, 26 + r * (TILE + 20)
    for i, (t, yaw, elev, merged) in enumerate(VIEWS):
        objs = [shells[n], infill[n]] if merged else [shells[n]]
        sheet.paste(shot(objs, yaw, elev, os.path.join(tmp, f"{n}_{i}.png")), (x0 + i * TILE, y0))
    dr.text((x0 + 6, y0 + TILE + 3), f"{n}: infill {stats[n]['infill_faces']} faces", fill=(240, 240, 240))
sheet.save(os.path.join(WORK, "MERGED.png"))

# the textured shells alone (no infill), one object per part
bpy.ops.object.select_all(action="DESELECT")
for n in names:
    shells[n].select_set(True)
bpy.ops.export_scene.gltf(filepath=os.path.join(WORK, "shells_parts.glb"), use_selection=True)

# one object per part: shell + infill joined
for n in names:
    bpy.ops.object.select_all(action="DESELECT")
    shells[n].select_set(True)
    infill[n].select_set(True)
    bpy.context.view_layer.objects.active = shells[n]
    bpy.ops.object.join()
bpy.ops.object.select_all(action="DESELECT")
for n in names:
    shells[n].select_set(True)
bpy.ops.export_scene.gltf(filepath=os.path.join(WORK, "merged_parts.glb"), use_selection=True)
log("MERGE_OK")
