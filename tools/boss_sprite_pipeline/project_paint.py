"""Project a painted view back onto the mesh's texture atlas, then render a turntable.

Quick-and-dirty test-run version. No AI, no viewport: the camera that made the render is
re-created, the mesh is rendered once more as a UV-id image (each pixel = which atlas texel
is visible there, plus how much it faces the camera), and the painted pixels are splatted into
those texels. Only surface the camera actually saw gets paint; grazing angles fade back to the
original texture. Occlusion is handled by construction (hidden surface is not in the id image).

    .venv-bpy/Scripts/python.exe tools/boss_sprite_pipeline/project_paint.py \
        --stem gpt2_front_sculpt --elev 15 \
        --paint generated/.../face_elev15/attempt_2/output_tonematched.png \
        --alpha generated/bosses/demon/head_views/gpt2_front_sculpt/head_elev15_flat_2048.png \
        --out generated/bosses/demon/projected/gpt2_front_sculpt_face

Camera constants match head_ref_elev.py (ortho 0.26, head centre (0,-0.12,0.245), R=3).
Writes: atlas_before.png, atlas_after.png, mesh_painted.glb, turntable_*.png, head_*.png.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image

SCRATCH = r"C:\Users\Douglas\AppData\Local\Temp\claude\c--Users-Douglas-Pixel-Realm-Combat-Heroes-Private\727a2a76-8444-4d4a-ae4a-f96abface8e5\scratchpad"
sys.path.insert(0, SCRATCH)
from polish_padded import no_metal, pad  # noqa: E402  (atlas gutter padding + metallic 0, as used for every preview)

VARIANTS = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants"
HEAD_CENTRE = Vector((0.0, -0.12, 0.245))   # blender coords, as head_ref_elev.py
ORTHO_HEAD = 0.26
R = 3.0


def log(*a):
    print(*a, flush=True)


def load_mesh(stem: str):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(VARIANTS, stem, "mesh.glb"))
    obj = [o for o in bpy.data.objects if o.type == "MESH"][0]
    pad(obj)
    no_metal(obj)
    return obj


def head_camera(sc, elev_deg: float, res: int):
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = ORTHO_HEAD
    e = math.radians(elev_deg)
    cam.location = (HEAD_CENTRE.x, HEAD_CENTRE.y - R * math.cos(e), HEAD_CENTRE.z + R * math.sin(e))
    cam.rotation_euler = (math.radians(90) - e, 0, 0)
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.film_transparent = True
    return cam


def render_uv_id(sc, obj, cam, path: str):
    """Emission = (u, v, facing) of the ORIGINAL uv map, 32-bit EXR, no AA, no colour management."""
    bpy.context.view_layer.update()
    fwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))
    mat = bpy.data.materials.new("uvid")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = obj.data.uv_layers.active.name
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (-fwd.x, -fwd.y, -fwd.z)
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(uv.outputs[0], sep.inputs[0])
    nt.links.new(geo.outputs["Normal"], dot.inputs[0])
    nt.links.new(sep.outputs[0], comb.inputs[0])
    nt.links.new(sep.outputs[1], comb.inputs[1])
    nt.links.new(dot.outputs["Value"], comb.inputs[2])
    nt.links.new(comb.outputs[0], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])
    saved = [s.material for s in obj.material_slots]
    for s in obj.material_slots:
        s.material = mat
    sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.eevee.taa_render_samples = 1
    sc.render.filter_size = 0.0
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.image_settings.exr_codec = "NONE"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    for s, m in zip(obj.material_slots, saved):
        s.material = m
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)   # bottom-up rows
    bpy.data.images.remove(img)
    return px


def splat(idpx: np.ndarray, paint_rgb: np.ndarray, paint_alpha: np.ndarray, atlas: np.ndarray,
          face_lo=0.15, face_hi=0.55, dilate=6):
    """Accumulate painted pixels into atlas texels named by the id image. Returns (new_atlas, blend)."""
    H, W = atlas.shape[:2]
    u, v, facing, cover = idpx[..., 0], idpx[..., 1], idpx[..., 2], idpx[..., 3]
    ok = (cover > 0.5) & (paint_alpha > 0.5) & (facing > face_lo)
    # weight: smoothstep on facing, so grazing pixels barely count
    t = np.clip((facing - face_lo) / (face_hi - face_lo), 0, 1)
    wgt = (t * t * (3 - 2 * t))[ok]
    xi = np.clip((u[ok] * W).astype(np.int64), 0, W - 1)
    yi = np.clip((v[ok] * H).astype(np.int64), 0, H - 1)
    acc = np.zeros((H, W, 3), np.float64)
    wsum = np.zeros((H, W), np.float64)
    for c in range(3):
        np.add.at(acc[..., c], (yi, xi), paint_rgb[..., c][ok] * wgt)
    np.add.at(wsum, (yi, xi), wgt)
    hit = wsum > 0
    new = atlas.copy()
    new[hit] = acc[hit] / wsum[hit][:, None]
    blend = np.zeros((H, W), np.float32)
    # blend strength = mean facing weight of the pixels that landed here
    cnt = np.zeros((H, W), np.float64)
    np.add.at(cnt, (yi, xi), 1.0)
    blend[hit] = np.clip(wsum[hit] / cnt[hit], 0, 1)
    # fill un-hit texels inside the painted region from hit neighbours (limited radius)
    for _ in range(dilate):
        s = np.zeros_like(new); b = np.zeros_like(blend); c = np.zeros((H, W), np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                hs = np.roll(np.roll(hit, dy, 0), dx, 1)
                s += np.roll(np.roll(new * hit[..., None], dy, 0), dx, 1)
                b += np.roll(np.roll(blend * hit, dy, 0), dx, 1)
                c += hs
        fill = (~hit) & (c > 0)
        new[fill] = s[fill] / c[fill][:, None]
        blend[fill] = b[fill] / c[fill] * 0.85      # each ring a little weaker
        hit = hit | fill
    return new, blend


def atlas_of(obj):
    img = obj.material_slots[0].material.node_tree.nodes["Image Texture"].image
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, -1)
    return img, px


def neutral_lights(sc, target: Vector):
    for name, loc, energy in (("key", (-2, -3, 3), 6.0), ("fill", (3, -3, 1), 3.0), ("rim", (0, 3, 2), 3.0)):
        L = bpy.data.lights.new(name, "SUN"); L.energy = energy; L.color = (1, 1, 1)
        o = bpy.data.objects.new(name, L); sc.collection.objects.link(o); o.location = loc
        o.rotation_euler = (target - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.5, 0.5, 0.5, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0


def add_ao(obj, strength=0.45):
    for slot in obj.material_slots:
        nt = slot.material.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        src = bsdf.inputs["Base Color"].links[0].from_socket
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion"); ao.samples = 16; ao.inputs["Distance"].default_value = 0.05
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs[0].default_value = strength
        nt.links.new(src, mix.inputs[6]); nt.links.new(ao.outputs["Color"], mix.inputs[7])
        nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])


def render_set(sc, cam, out_dir: str, tag: str, head_elev: float):
    sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.eevee.taa_render_samples = 32
    sc.render.filter_size = 1.5
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    # head close-ups: the paint camera, front, and +/-45 around the head
    sc.render.resolution_x = sc.render.resolution_y = 1024
    cam.data.ortho_scale = ORTHO_HEAD
    for name, yaw, elev in (("paintcam", 0, head_elev), ("front", 0, 0), ("left45", -45, 0), ("right45", 45, 0)):
        a, e = math.radians(yaw), math.radians(elev)
        cam.location = (HEAD_CENTRE.x + R * math.sin(a) * math.cos(e), HEAD_CENTRE.y - R * math.cos(a) * math.cos(e), HEAD_CENTRE.z + R * math.sin(e))
        cam.rotation_euler = (math.radians(90) - e, 0, a)
        sc.render.filepath = os.path.join(out_dir, f"head_{name}_{tag}.png"); bpy.ops.render.render(write_still=True)
    # full-body 8 directions at game scale
    sc.render.resolution_x = sc.render.resolution_y = 700
    cam.data.ortho_scale = 1.1
    for k in range(8):
        a = math.radians(45 * k)
        cam.location = (R * math.sin(a), -R * math.cos(a), 0.0); cam.rotation_euler = (math.radians(90), 0, a)
        sc.render.filepath = os.path.join(out_dir, f"turntable_{k}_{45*k:03d}_{tag}.png"); bpy.ops.render.render(write_still=True)
    log("rendered", tag)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", required=True)
    ap.add_argument("--elev", type=float, default=15.0)
    ap.add_argument("--paint", required=True, help="painted RGB image from the head camera")
    ap.add_argument("--alpha", required=True, help="the flat render that was painted (its alpha = subject)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)          # bpy resolves relative render paths to the drive root
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    obj = load_mesh(args.stem)
    sc = bpy.context.scene
    paint = Image.open(args.paint).convert("RGB")
    res = paint.width
    cam = head_camera(sc, args.elev, res)

    idpx = render_uv_id(sc, obj, cam, os.path.join(args.out, "uv_id.exr"))
    log("uv-id rendered", idpx.shape, "coverage %.1f%%" % (100 * (idpx[..., 3] > 0.5).mean()), "%.0fs" % (time.time() - t0))

    paint_rgb = np.flipud(np.asarray(paint, dtype=np.float32) / 255.0)            # bottom-up like bpy
    paint_alpha = np.flipud(np.asarray(Image.open(args.alpha).convert("RGBA"))[..., 3] / 255.0)
    img, atlas = atlas_of(obj)
    Image.fromarray((np.clip(np.flipud(atlas[..., :3]), 0, 1) * 255).astype(np.uint8)).save(os.path.join(args.out, "atlas_before.png"))

    new, blend = splat(idpx, paint_rgb, paint_alpha, atlas[..., :3])
    final = atlas.copy()
    final[..., :3] = atlas[..., :3] * (1 - blend[..., None]) + new * blend[..., None]
    log("painted texels %.1f%% of atlas" % (100 * (blend > 0.01).mean()), "%.0fs" % (time.time() - t0))
    Image.fromarray((np.clip(np.flipud(final[..., :3]), 0, 1) * 255).astype(np.uint8)).save(os.path.join(args.out, "atlas_after.png"))
    Image.fromarray((np.flipud(blend) * 255).astype(np.uint8)).save(os.path.join(args.out, "atlas_blend.png"))

    # renders BEFORE (original padded texture) then AFTER (painted), same lights
    neutral_lights(sc, Vector((0, 0, 0)))
    add_ao(obj, 0.45)
    render_set(sc, cam, args.out, "before", args.elev)
    img.pixels[:] = final.ravel(); img.update()
    render_set(sc, cam, args.out, "after", args.elev)

    # export the painted mesh (texture packed from memory)
    img.pack()
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=os.path.join(args.out, "mesh_painted.glb"), use_selection=True)
    log("DONE %.0fs -> %s" % (time.time() - t0, args.out))


if __name__ == "__main__":
    main()
