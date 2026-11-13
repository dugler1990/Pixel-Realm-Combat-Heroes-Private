"""Inventory icons for worn pieces: each slot pack's blend at rest, textured, 3/4 front, transparent background.

    <bpy python> tools/boss_sprite_pipeline/explode2/piece_icons.py <packs dir> <out dir> <slot> [<slot> ...]

<packs dir>/<slot>.blend (explode2/slot_packs.py) -> <out dir>/<slot>.png, 256 x 256, the piece filling ~88 %.
Workbench, texture colours, studio light; the armature set to its rest pose. Prints ICONS_OK.
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

SIZE, FILL, YAW = 256, 0.88, 30.0


def icon(blend: Path, out: Path) -> None:
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    scene = bpy.context.scene
    for o in scene.objects:
        if o.type == "ARMATURE":
            o.data.pose_position = "REST"
    bpy.context.view_layer.update()
    meshes = [o for o in scene.objects if o.type == "MESH" and not o.hide_render]
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in meshes:
        ev = o.evaluated_get(deps)
        m = ev.to_mesh()
        pts.append(np.array([ev.matrix_world @ v.co for v in m.vertices]))
        ev.to_mesh_clear()
    pts = np.concatenate(pts)
    lo, hi = pts.min(0), pts.max(0)
    c = (lo + hi) / 2
    a = math.radians(YAW)
    d = Vector((math.sin(a), -math.cos(a), 0.25)).normalized()      # in front (-y), a little to his left, above
    cam = bpy.data.objects.new("icon_cam", bpy.data.cameras.new("icon_cam"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    rot = (-d).to_track_quat("-Z", "Y")
    # the box's extent across the view, so the piece fills the square
    right, up = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0))
    rel = pts - c
    w = float(np.ptp(rel @ np.array(right)))
    h = float(np.ptp(rel @ np.array(up)))
    cam.data.ortho_scale = max(w, h) / FILL
    cam.location = Vector(c) + d * float(np.ptp(pts, 0).max()) * 4
    cam.rotation_euler = rot.to_euler()
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    packs, out, slots = Path(argv[0]), Path(argv[1]), argv[2:]
    out.mkdir(parents=True, exist_ok=True)
    for s in slots:
        icon(packs / f"{s}.blend", out / f"{s}.png")
    print("ICONS_OK", " ".join(slots))


if __name__ == "__main__":
    main()
