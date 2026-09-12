"""Stage 4: render an animated model to N-direction sprite frames.

Runs under ``.venv-bpy`` (Blender as a Python module), never under the project
venv. ``pipeline.py`` spawns it as a subprocess:

    .venv-bpy/bin/python render_frames.py <boss_config.json> <workdir>

Reads ``<workdir>/<source>`` (.glb/.gltf/.fbx/.blend), writes
``<workdir>/frames/<action>/<dir>/NNNN.png`` plus ``frames/manifest.json``.

Framing is identical for every action and direction: one orthographic camera,
one ``ortho_scale`` covering the union of all sampled poses, model spun on a
turntable empty about the vertical axis through its pivot. The pivot therefore
projects to the same pixel in every frame — that pixel is the manifest anchor
the engine plants on the hitbox.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

# Turntable yaw steps of +360/N (CCW seen from above), starting with the model
# facing the camera. Camera sits on -Y looking +Y, so +X is screen-right:
# +90° spins the model's front toward +X → it faces screen-right → "e".
DIRECTION_KEYS = {
    8: ["s", "se", "e", "ne", "n", "nw", "w", "sw"],
    16: ["s", "sse", "se", "ese", "e", "ene", "ne", "nne",
         "n", "nnw", "nw", "wnw", "w", "wsw", "sw", "ssw"],
}

DEFAULTS = {
    "forward_axis": "-Y",
    "directions": 8,
    "camera": {"elevation_deg": 45.0, "margin": 1.10},
    "light": {"elevation_deg": 50.0, "azimuth_deg": -35.0, "energy": 3.0, "ambient": 0.35},
    "render": {
        "engine": "CYCLES", "device": "CPU", "samples": 32, "denoise": True,
        "resolution": 256, "shading": "raw", "ground_shadow": True,
    },
}


def log(*parts):
    print("[render_frames]", *parts, flush=True)


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------- load

def load_source(path: Path) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    suffix = path.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
    elif suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise SystemExit(f"unsupported source {path}")


def collect_action_bindings() -> dict[str, list[tuple[bpy.types.ID, bpy.types.Action]]]:
    """Map action name → [(datablock, action)] from whatever the importer left bound.

    The glTF importer parks each animation on an NLA track (or as the active
    action) of every datablock it touches — armature *and* shape-key blocks
    share a clip name. We remember those pairings, then unbind everything so a
    stale track never bleeds into a render, and rebind per action as we go.
    """
    bindings: dict[str, list] = {}

    def visit(block):
        ad = getattr(block, "animation_data", None)
        if ad is None:
            return
        seen = set()
        if ad.action is not None:
            seen.add(ad.action)
        for track in ad.nla_tracks:
            for strip in track.strips:
                if strip.action is not None:
                    seen.add(strip.action)
        for action in seen:
            bindings.setdefault(action.name, []).append((block, action))
        for track in list(ad.nla_tracks):
            ad.nla_tracks.remove(track)
        ad.action = None

    for obj in bpy.data.objects:
        visit(obj)
        data = getattr(obj, "data", None)
        if data is not None and getattr(data, "shape_keys", None) is not None:
            visit(data.shape_keys)
    return bindings


def bind_action(pairs) -> tuple[float, float]:
    start, end = math.inf, -math.inf
    for block, action in pairs:
        block.animation_data.action = action
        # Blender 4.4+ slotted actions: pick the slot matching this block type
        if hasattr(action, "slots") and len(action.slots) and hasattr(block.animation_data, "action_slot"):
            for slot in action.slots:
                if slot.target_id_type == block.id_type:
                    block.animation_data.action_slot = slot
                    break
        f0, f1 = action.frame_range
        start, end = min(start, f0), max(end, f1)
    return start, end


def unbind_actions(pairs) -> None:
    for block, _ in pairs:
        block.animation_data.action = None


# ------------------------------------------------------------------------ geometry

def mesh_objects():
    return [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render]


def evaluated_points(depsgraph) -> np.ndarray:
    """World-space vertex positions of every render-visible mesh, as an (N, 3) array."""
    chunks = []
    for obj in mesh_objects():
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        n = len(mesh.vertices)
        if n:
            co = np.empty(n * 3, dtype=np.float64)
            mesh.vertices.foreach_get("co", co)
            co = co.reshape(n, 3)
            mat = np.array(ev.matrix_world, dtype=np.float64)
            chunks.append(co @ mat[:3, :3].T + mat[:3, 3])
        ev.to_mesh_clear()
    return np.concatenate(chunks) if chunks else np.zeros((0, 3))


def sample_frames(start: float, end: float, fps_src: float, fps_out: float) -> list[float]:
    """Source frame numbers for one loop of the clip, sampled at fps_out.

    Excludes the clip's final frame: loops end where they start, so sampling
    ``[0, duration)`` avoids a doubled frame at the seam.
    """
    duration = max((end - start) / fps_src, 1.0 / fps_out)
    count = max(1, int(round(duration * fps_out)))
    return [start + k * fps_src / fps_out for k in range(count)]


def set_frame(scene, f: float) -> None:
    whole = int(math.floor(f))
    scene.frame_set(whole, subframe=f - whole)


def sun_direction(light_cfg) -> np.ndarray:
    """World-space direction the key sun's rays travel (see build_lights)."""
    a = math.radians(90 - light_cfg["elevation_deg"])
    b = math.radians(light_cfg["azimuth_deg"])
    return np.array([-math.sin(b) * math.sin(a), math.cos(b) * math.sin(a), -math.cos(a)])


def measure_bounds(scene, action_plan, yaws: list[float], elevation_deg: float,
                   shadow_dir: np.ndarray | None) -> dict:
    """Exact screen extents over every sampled frame, every turntable yaw, plus shadows.

    The pivot is the union bbox centre (x/y) at the lowest z ever. For each yaw the
    frame's vertices are spun about the pivot axis (what the turntable will do),
    their ground-shadow points added when a shadow catcher is on, and both
    projected onto the camera's screen axes: x → world x, up → y·sinφ + z·cosφ.
    Returns half_x and the [sy_min, sy_max] range relative to the pivot, in world
    units — everything build_camera needs for a tight square frame whose anchor
    (the pivot) is the same pixel in every direction.
    """
    frames = []
    for name, (pairs, samples) in action_plan.items():
        bind_action(pairs)
        for f in samples:
            set_frame(scene, f)
            pts = evaluated_points(bpy.context.evaluated_depsgraph_get())
            if len(pts):
                frames.append(pts)
        unbind_actions(pairs)
    if not frames:
        raise SystemExit("no mesh vertices found")
    allpts = np.concatenate(frames)
    lo, hi = allpts.min(axis=0), allpts.max(axis=0)
    pivot = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    phi = math.radians(elevation_deg)
    up = np.array([0.0, math.sin(phi), math.cos(phi)])

    half_x, sy_min, sy_max = 0.0, math.inf, -math.inf
    for yaw in yaws:
        c, s_ = math.cos(yaw), math.sin(yaw)
        rot = np.array([[c, -s_, 0.0], [s_, c, 0.0], [0.0, 0.0, 1.0]])
        for pts in frames:
            q = (pts - np.array(pivot)) @ rot.T  # relative to pivot, spun
            if shadow_dir is not None:
                t = (-q[:, 2] / shadow_dir[2])[:, None]  # ground is z=0 here
                q = np.concatenate([q, q + t * shadow_dir])
            half_x = max(half_x, float(np.abs(q[:, 0]).max()))
            sy = q @ up
            sy_min, sy_max = min(sy_min, float(sy.min())), max(sy_max, float(sy.max()))
    return {"pivot": pivot, "height": float(hi[2] - lo[2]), "half_x": half_x,
            "sy_min": sy_min, "sy_max": sy_max}


def forward_yaw(forward_axis: str) -> float:
    """Yaw (radians) that turns the model's forward axis onto -Y (toward camera)."""
    axes = {"+X": (1, 0), "-X": (-1, 0), "+Y": (0, 1), "-Y": (0, -1)}
    fx, fy = axes[forward_axis.upper()]
    return math.atan2(-1, 0) - math.atan2(fy, fx)


def build_turntable(scene, pivot: Vector):
    empty = bpy.data.objects.new("turntable", None)
    scene.collection.objects.link(empty)
    empty.location = pivot
    bpy.context.view_layer.update()  # matrix_world is stale until the depsgraph runs
    for obj in list(bpy.data.objects):
        if obj is empty or obj.parent is not None or obj.type in {"CAMERA", "LIGHT"}:
            continue
        world = obj.matrix_world.copy()
        obj.parent = empty
        obj.matrix_parent_inverse = empty.matrix_world.inverted()
        obj.matrix_world = world
    return empty


# --------------------------------------------------------------------------- scene

def build_camera(scene, bounds, cam_cfg, resolution, target_height_px=None):
    """Orthographic camera framing every pose. Returns (camera, ortho side, resolution).

    ``target_height_px`` overrides ``resolution``: the frame is sized so the model's
    standing height covers that many pixels, whatever the shadow/pose allowance is.
    """
    phi = math.radians(cam_cfg["elevation_deg"])
    h = bounds["height"]
    side = cam_cfg["margin"] * max(2 * bounds["half_x"], bounds["sy_max"] - bounds["sy_min"])
    if target_height_px:
        resolution = int(math.ceil(target_height_px * side / max(h * math.cos(phi), 1e-6)))
        resolution += resolution % 2
    # look-at point on the pivot axis whose screen height is the centre of the extents
    centre_sy = (bounds["sy_min"] + bounds["sy_max"]) / 2
    target = bounds["pivot"] + Vector((0, 0, centre_sy / math.cos(phi)))
    dist = max(10.0 * side, 10.0)

    cam_data = bpy.data.cameras.new("sprite_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = side
    cam_data.clip_start = 0.01
    cam_data.clip_end = dist * 4
    cam = bpy.data.objects.new("sprite_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = target + Vector((0, -dist * math.cos(phi), dist * math.sin(phi)))
    cam.rotation_euler = (math.pi / 2 - phi, 0, 0)
    scene.camera = cam
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    bpy.context.view_layer.update()  # so world_to_camera_view sees the real camera matrix
    return cam, side, resolution


def build_lights(scene, light_cfg):
    sun_data = bpy.data.lights.new("key", "SUN")
    sun_data.energy = light_cfg["energy"]
    sun_data.angle = math.radians(3)
    sun = bpy.data.objects.new("key", sun_data)
    scene.collection.objects.link(sun)
    # Sun beam is local -Z. Tilt it by (90 - elevation) toward +Y (away from the
    # camera → front lighting), then yaw so it comes from the camera's left/right.
    sun.rotation_euler = (
        math.radians(90 - light_cfg["elevation_deg"]), 0, math.radians(light_cfg["azimuth_deg"])
    )
    world = bpy.data.worlds.new("sprite_world")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (1, 1, 1, 1)
        bg.inputs["Strength"].default_value = light_cfg["ambient"]


def build_shadow_catcher(scene, bounds, side):
    mesh = bpy.data.meshes.new("ground")
    size = side * 20
    mesh.from_pydata(
        [(-size, -size, 0), (size, -size, 0), (size, size, 0), (-size, size, 0)], [], [(0, 1, 2, 3)]
    )
    ground = bpy.data.objects.new("ground", mesh)
    scene.collection.objects.link(ground)
    ground.location = (bounds["pivot"].x, bounds["pivot"].y, bounds["pivot"].z)
    ground.is_shadow_catcher = True
    return ground


def apply_toon_shading(scene):
    """Cycles Toon BSDF per material (keeps the texture) + Freestyle outline.

    ShaderToRGB/colour-ramp toon setups are EEVEE-only; Cycles has a native Toon
    BSDF, so we swap each material's surface shader for one fed by the original
    shader's Base Color (linked texture or plain value).
    """
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        tree = mat.node_tree
        out = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if out is None or not out.inputs["Surface"].is_linked:
            continue
        shader = out.inputs["Surface"].links[0].from_node
        color_in = next((i for i in shader.inputs if i.name in ("Base Color", "Color")), None)
        toon = tree.nodes.new("ShaderNodeBsdfToon")
        toon.component = "DIFFUSE"
        toon.inputs["Size"].default_value = 0.6
        toon.inputs["Smooth"].default_value = 0.05
        if color_in is not None and color_in.is_linked:
            tree.links.new(color_in.links[0].from_socket, toon.inputs["Color"])
        elif color_in is not None:
            toon.inputs["Color"].default_value = color_in.default_value
        tree.links.new(toon.outputs["BSDF"], out.inputs["Surface"])
    scene.render.use_freestyle = True
    scene.render.line_thickness = 1.2
    linestyle = bpy.data.linestyles.get("outline") or bpy.data.linestyles.new("outline")
    linestyle.color = (0.05, 0.03, 0.02)
    linestyle.thickness = 1.5
    for vl in scene.view_layers:
        vl.use_freestyle = True
        linesets = vl.freestyle_settings.linesets
        if not linesets:
            linesets.new("outline")
        for lineset in linesets:
            if lineset.linestyle is None:  # the factory scene's default LineSet has none → Freestyle crashes
                lineset.linestyle = linestyle
            lineset.select_silhouette = True
            lineset.select_border = True
            lineset.select_crease = True


def configure_render(scene, render_cfg):
    scene.render.engine = render_cfg["engine"]
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    if render_cfg["engine"] == "CYCLES":
        scene.cycles.samples = render_cfg["samples"]
        scene.cycles.use_denoising = render_cfg["denoise"]
        scene.cycles.device = render_cfg["device"]
        if render_cfg["device"] == "GPU":
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = backend
                    prefs.get_devices()
                    break
                except TypeError:
                    continue
            for dev in prefs.devices:
                dev.use = True


# ---------------------------------------------------------------------------- main

def main(config_path: Path, workdir: Path, frames_dir: Path | None = None) -> None:
    cfg = deep_merge(DEFAULTS, json.loads(config_path.read_text(encoding="utf-8")))
    render_cfg, cam_cfg, light_cfg = cfg["render"], cfg["camera"], cfg["light"]
    directions = int(cfg["directions"])
    keys = DIRECTION_KEYS[directions]

    source = workdir / cfg["source"]
    load_source(source)
    scene = bpy.context.scene
    fps_src = scene.render.fps / scene.render.fps_base
    bindings = collect_action_bindings()
    log("source", source.name, "actions found:", sorted(bindings))

    action_plan = {}
    for name, spec in cfg["actions"].items():
        if spec.get("static"):
            action_plan[name] = ([], [float(scene.frame_current)])
            log(f"action {name}: static pose")
            continue
        src_name = spec.get("source", name)
        if src_name not in bindings:
            raise SystemExit(f"action {name!r}: source clip {src_name!r} not in {sorted(bindings)} "
                             "(use {\"static\": true} for an unanimated model)")
        pairs = bindings[src_name]
        start, end = bind_action(pairs)
        unbind_actions(pairs)
        frames = sample_frames(start, end, fps_src, float(spec.get("fps_out", 15)))
        action_plan[name] = (pairs, frames)
        log(f"action {name}: clip {src_name!r} frames {start:.0f}-{end:.0f} @ {fps_src:.0f}fps → {len(frames)} out @ {spec.get('fps_out', 15)}fps")

    yaw0 = forward_yaw(cfg["forward_axis"])
    yaws = [yaw0 + d * 2 * math.pi / directions for d in range(directions)]
    bounds = measure_bounds(scene, action_plan, yaws, cam_cfg["elevation_deg"],
                            sun_direction(light_cfg) if render_cfg["ground_shadow"] else None)
    log("bounds pivot", tuple(round(v, 3) for v in bounds["pivot"]), "height", round(bounds["height"], 3),
        "half_x", round(bounds["half_x"], 3), "sy", (round(bounds["sy_min"], 3), round(bounds["sy_max"], 3)))

    turntable = build_turntable(scene, bounds["pivot"])
    cam, side, res = build_camera(scene, bounds, cam_cfg, int(render_cfg["resolution"]),
                                  render_cfg.get("target_height_px"))
    log(f"frame {res}px, ortho side {side:.1f} units → model height ≈ "
        f"{bounds['height'] * math.cos(math.radians(cam_cfg['elevation_deg'])) / side * res:.0f}px")
    build_lights(scene, light_cfg)
    if render_cfg["ground_shadow"]:
        build_shadow_catcher(scene, bounds, side)
    if render_cfg["shading"] == "toon":
        apply_toon_shading(scene)
    configure_render(scene, render_cfg)

    u, v, _ = world_to_camera_view(scene, cam, bounds["pivot"])
    anchor = [round(u * res, 2), round((1 - v) * res, 2)]

    frames_dir = frames_dir or (workdir / "frames")
    manifest = {
        "name": cfg["name"],
        "version": 1,
        "source": cfg["source"],
        "resolution": res,
        "directions": keys,
        "anchor_px": anchor,
        "pixels_per_unit": res / side,
        "ortho_scale": side,
        "elevation_deg": cam_cfg["elevation_deg"],
        "height_units": bounds["height"],
        "shading": render_cfg["shading"],
        "actions": {},
    }

    total = sum(len(frames) for _, frames in action_plan.values()) * directions
    done, t0 = 0, time.time()
    for name, (pairs, frames) in action_plan.items():
        bind_action(pairs)
        manifest["actions"][name] = {
            "source": None if not pairs else cfg["actions"][name].get("source", name),
            "fps": float(cfg["actions"][name].get("fps_out", 15)),
            "frames": len(frames),
        }
        for d, key in enumerate(keys):
            turntable.rotation_euler = (0, 0, yaws[d])
            out_dir = frames_dir / name / key
            out_dir.mkdir(parents=True, exist_ok=True)
            for k, f in enumerate(frames):
                set_frame(scene, f)
                scene.render.filepath = str(out_dir / f"{k:04d}.png")
                bpy.ops.render.render(write_still=True)
                done += 1
            elapsed = time.time() - t0
            log(f"{name}/{key} done  {done}/{total}  {elapsed:.0f}s elapsed, ~{elapsed / done * (total - done):.0f}s left")
        unbind_actions(pairs)

    (frames_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("wrote", frames_dir / "manifest.json")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="render N-direction sprite frames (run under .venv-bpy)")
    ap.add_argument("config", type=Path)
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--frames-dir", type=Path, default=None, help="default <workdir>/frames")
    args = ap.parse_args()
    main(args.config.resolve(), args.workdir.resolve(), args.frames_dir.resolve() if args.frames_dir else None)
