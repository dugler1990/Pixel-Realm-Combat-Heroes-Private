"""Render TRELLIS models front / side / back for the pick gate (outfit.py trellis; the web page shows the sheet).

    <bpy python> tools/boss_sprite_pipeline/gpu_box/trellis_sheet.py <trellis dir> <tiles dir> <model> [<model> ...]

Each <trellis dir>/<model>_from_front.glb: Workbench, texture colours, studio light, orthographic, 512 x 768, from
the front (yaw 0), his left side (90) and behind (180), framed on the model's height. Writes
<tiles dir>/<model>_<yaw>.png and prints TILES_OK. outfit.py lays the tiles out as TRELLIS_SHEET.png.
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

YAWS = (0, 90, 180)


def render_model(glb: Path, tiles: Path, name: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.render.resolution_x, scene.render.resolution_y = 512, 768
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in scene.objects if o.type == "MESH"]
    pts = np.concatenate([np.array([o.matrix_world @ v.co for v in o.data.vertices]) for o in meshes])
    lo, hi = pts.min(0), pts.max(0)
    c, h = (lo + hi) / 2, float((hi - lo)[2])
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = h * 1.1
    scene.camera = cam
    for yaw in YAWS:
        a = math.radians(yaw)
        d = Vector((math.sin(a), -math.cos(a), 0))          # the model faces -y: yaw 0 = in front
        cam.location = Vector(c) + d * h * 3
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(tiles / f"{name}_{yaw}.png")
        bpy.ops.render.render(write_still=True)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    trellis, tiles, models = Path(argv[0]), Path(argv[1]), argv[2:]
    tiles.mkdir(parents=True, exist_ok=True)
    for m in models:
        render_model(trellis / f"{m}_from_front.glb", tiles, m)
    print("TILES_OK", " ".join(models))


if __name__ == "__main__":
    main()
