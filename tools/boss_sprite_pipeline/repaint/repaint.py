"""Repaint a TRELLIS character the way the demon's face was painted, over the whole body.
First used on the barb (2026-11-01); see PROCESS_repaint.md.

The demon: render the mesh's head from one camera -> gpt-image-2 repaints the render ->
project_paint.py splats the painted pixels back into the texture atlas texels that camera saw.
Here: 8 cameras round the body + 3 round the head, and the views are blended per texel.

    PY=tools/boss_sprite_pipeline/.venv-bpy/Scripts/python.exe   (run from the Boss repo)
    $PY tools/boss_sprite_pipeline/repaint/repaint.py views   <rigged.glb> <work_dir>
    $PY tools/boss_sprite_pipeline/repaint/repaint.py gen     <work_dir> <reference_picture.png> [view ...]
    $PY tools/boss_sprite_pipeline/repaint/repaint.py project <rigged.glb> <work_dir>

views    flat (unlit texture) + clay (shape) render per camera, cams.json
gen      front body view first; every other view also gets the front result as a colour anchor
project  per texel, the views that saw it blend with weight facing^4 (the most head-on view
         wins, edges blend); head close-ups override the body views on the head. Texels no
         camera saw get the old texture pushed through the old->new colour map fitted on the
         painted texels. Gutters padded, metallic 0, exported with the armature.
"""
import json
import math
import os
import sys
import time

LOOK_ARG = None                 # views ... --look <look.json>: another character/outfit (see looks/)
if "--look" in sys.argv:
    _i = sys.argv.index("--look")
    LOOK_ARG = os.path.abspath(sys.argv[_i + 1])
    del sys.argv[_i:_i + 2]
MODE = sys.argv[1]
BOSS = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
GREY = (128, 128, 128)
BODY_RES = (1024, 1536)
HEAD_RES = (1024, 1024)
PART_RES = (2880, 2880)    # gpt-image-2's largest: 8,294,400 px, edges divisible by 16
TEX = 4096                 # project: the atlas is upscaled to this before painting into it
BODY_ELEV = 25.0
HEAD_ELEV = 15.0
YAW_NAMES = {0: "front", 45: "front, three-quarter from his left side", 90: "his left side",
             135: "back, three-quarter from his left side", 180: "back",
             225: "back, three-quarter from his right side", 270: "his right side",
             315: "front, three-quarter from his right side"}


def log(*a):
    print(*a, flush=True)


def view_list():
    v = [{"name": f"body_{y:03d}", "kind": "body", "yaw": y, "elev": BODY_ELEV, "res": BODY_RES} for y in range(0, 360, 45)]
    v += [{"name": f"head_{n}", "kind": "head", "yaw": y, "elev": HEAD_ELEV, "res": HEAD_RES}
          for n, y in (("front", 0), ("left", 55), ("right", 305))]
    return v


def saved_views(work):
    path = os.path.join(work, "cams.json")
    return json.load(open(path))["views"] if os.path.isfile(path) else view_list()


# close-ups: (name, region, yaw, elev, what the camera shows, what to paint well). +X = his left.
PART_SHOTS = [
    ("face_front", "face", 0, 10, "his face from the front",
     "a hero face: clearly painted eyes and eyelids, a strong brow, a nose that reads as a nose with darker nostrils, "
     "lips, beard and moustache as clean bold locks"),
    ("face_left", "face", 50, 10, "his face, three-quarter from his left side", "the same hero face, ear and side of the beard"),
    ("face_right", "face", 310, 10, "his face, three-quarter from his right side", "the same hero face, ear and side of the beard"),
    ("head_back", "head", 180, 20, "the back of his head", "the hair pulled back into a top knot, bold readable locks"),
    ("hand_l_out", "hand_l", 90, 0, "his left hand, from outside (the back of the hand)", "every finger and knuckle separated, nails painted"),
    ("hand_l_front", "hand_l", 0, 10, "his left hand, from the front", "every finger and knuckle separated, nails painted"),
    ("hand_r_out", "hand_r", 270, 0, "his right hand, from outside (the back of the hand)", "every finger and knuckle separated, nails painted"),
    ("hand_r_front", "hand_r", 0, 10, "his right hand, from the front", "every finger and knuckle separated, nails painted"),
    ("foot_l_front", "foot_l", 0, 35, "his bare left foot, from the front and above", "every toe separated, toenails painted, ankle bones"),
    ("foot_l_out", "foot_l", 90, 15, "his bare left foot, from the outside", "every toe separated, toenails painted, darker sole edge"),
    ("foot_r_front", "foot_r", 0, 35, "his bare right foot, from the front and above", "every toe separated, toenails painted, ankle bones"),
    ("foot_r_out", "foot_r", 270, 15, "his bare right foot, from the outside", "every toe separated, toenails painted, darker sole edge"),
    ("chest_front", "chest", 0, 10, "his chest, shoulders and belly, from the front", "bold muscle shapes: pecs, abs, collarbones, shoulders"),
    ("back_upper", "chest", 180, 10, "his upper back and shoulders, from behind", "bold muscle shapes: shoulder blades, traps, spine"),
    ("arm_l_out", "arm_l", 90, 5, "his left arm, from the outside", "bold shoulder, biceps, triceps, forearm and elbow shapes"),
    ("arm_l_front", "arm_l", 0, 5, "his left arm, from the front", "bold shoulder, biceps, forearm and elbow shapes"),
    ("arm_r_out", "arm_r", 270, 5, "his right arm, from the outside", "bold shoulder, biceps, triceps, forearm and elbow shapes"),
    ("arm_r_front", "arm_r", 0, 5, "his right arm, from the front", "bold shoulder, biceps, forearm and elbow shapes"),
    ("leg_l_front", "leg_l", 0, 10, "his left leg (thigh, knee, shin), from the front", "bold thigh, knee and calf shapes"),
    ("leg_l_out", "leg_l", 90, 5, "his left leg, from the outside", "bold thigh, knee and calf shapes"),
    ("leg_r_front", "leg_r", 0, 10, "his right leg (thigh, knee, shin), from the front", "bold thigh, knee and calf shapes"),
    ("leg_r_out", "leg_r", 270, 5, "his right leg, from the outside", "bold thigh, knee and calf shapes"),
    ("legs_back", "legs", 180, 10, "the backs of both legs", "bold hamstring and calf shapes, backs of the knees"),
    ("pelvis_front", "pelvis", 0, 10, "his hips and leather loincloth, from the front", "the leather loincloth and belt: stitching, worn edges, buckle"),
    ("pelvis_back", "pelvis", 180, 10, "his hips and leather loincloth, from behind", "the leather loincloth and belt: stitching, worn edges"),
]


# What the prompts say about the character. Default: the bare barb (pass 1/2 wording, unchanged).
# A look file (looks/*.json, given to `views --look`, remembered in cams.json) overrides any key, can
# limit the views ("views": names) and re-word close-ups ("shots": {name: {"shows", "paint"}}).
# "part_res": close-up size in px (default PART_RES); "quality": gpt-image-2 quality (default high);
# "regions": {"arm": {"scale": 1.3, "shift_up": 0.04}} widens / raises a close-up frame (shift in heights).
DEFAULT_LOOK = {
    "subject": "barbarian hero",
    "design": "warm tanned skin, dark brown hair tied in a top knot, full dark brown beard, brown leather loincloth "
              "on a leather belt, bare feet",
    "match_part": "skin tone, hair, beard and leather colours",
    "match_body": "skin tone, hair and beard colour, leather colour and painting style",
    "body_paint": "Paint it in the hand-painted style of image 3: painterly skin with colour variation (warmer on the "
                  "cheeks, shoulders, elbows, knees and knuckles, cooler and darker in the creases between muscles), clear "
                  "muscle definition, individual hair and beard locks, readable fingers and toes, crisp eyes, nose and "
                  "mouth where visible.",
    "part_variation": "with painterly colour variation (warmer on the high points, cooler and darker in the creases)",
    "safety": "He is a non-sexual, family-friendly game character wearing a leather loincloth. ",
    "finish_part": "Matte and evenly lit: no cast shadows, no directional light, no shiny or oily highlights.",
    "finish_body": "Keep it evenly lit: no cast shadows, no directional light, no shiny highlights painted in.",
}
# gpt-image-2 Standard, USD per 1M tokens (developers.openai.com/api/docs/pricing, read 2026-11-02)
PRICE = {"text_in": 5.0, "image_in": 8.0, "image_out": 30.0}


def usd(usage):
    if not usage:
        return 0.0
    i, o = usage.get("input_tokens_details", {}), usage.get("output_tokens_details", {})
    return (i.get("text_tokens", 0) * PRICE["text_in"] + i.get("image_tokens", 0) * PRICE["image_in"]
            + o.get("image_tokens", 0) * PRICE["image_out"] + o.get("text_tokens", 0) * PRICE["text_in"]) / 1e6


def load_look(path):
    look = dict(DEFAULT_LOOK)
    if path:
        look.update(json.load(open(path, encoding="utf-8")))
    return look


# ============================================================================ blender side
if MODE in ("views", "project"):
    import bpy
    import numpy as np
    from mathutils import Vector
    from PIL import Image, ImageDraw

    def load(glb, upscale=False):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=glb)
        body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not body]:
            bpy.data.objects.remove(o, do_unlink=True)
        nt = body.data.materials[0].node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        # matte: no metal, full roughness (the shine in the first pose tests was the render's specular,
        # but a glossy material would shine in the sprite renders too)
        for name, value in (("Metallic", 0.0), ("Roughness", 1.0)):
            for l in list(bsdf.inputs[name].links):
                nt.links.remove(l)
            bsdf.inputs[name].default_value = value
        img = bsdf.inputs["Base Color"].links[0].from_node.image
        W, H = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)
        # TRELLIS's bake leaves ~5% of texels unwritten (rgb 0, alpha 0) in thin lines INSIDE
        # the charts as well as in the gutters: the dark speckle all over the barb. Fill every
        # unwritten texel from its written neighbours.
        written = (px[..., 3] > 0) | (px[..., :3].max(2) > 0)
        px[..., :3] = grow(px[..., :3], written, 24)
        px[..., 3] = 1.0
        img.pixels[:] = px.ravel()
        img.update()
        log(f"atlas holes filled: {100 * (~written).mean():.1f}% unwritten")
        if upscale and W < TEX:                # room for the close-ups' detail (UVs are unchanged)
            img.scale(TEX, TEX)
            W, H = img.size
        chart = chart_mask(body, W, H)
        log(f"atlas {W}x{H}; charts {100 * chart.mean():.1f}%")
        return body, bsdf, img, chart

    def chart_mask(body, W, H):
        """Texels inside any UV polygon; everything else is gutter (black in TRELLIS atlases,
        which bleeds into the render as dark speckles at every chart edge)."""
        me = body.data
        uv = np.empty(len(me.loops) * 2, np.float32)
        me.uv_layers.active.data.foreach_get("uv", uv)
        px_uv = uv.reshape(-1, 2) * np.array([W, H])
        ls = np.empty(len(me.polygons), np.int64)
        me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(len(me.polygons), np.int64)
        me.polygons.foreach_get("loop_total", lt)
        im = Image.new("L", (W, H), 0)
        dr = ImageDraw.Draw(im)
        for s, n in zip(ls, lt):
            dr.polygon([(float(x), float(H - y)) for x, y in px_uv[s:s + n]], fill=255)
        return np.flipud(np.asarray(im) > 0)          # bottom-up like bpy pixels

    def grow(col, mask, rings):
        """Colour outside mask grows in from inside, one texel ring per step."""
        col = col.copy()
        mask = mask.copy()
        for _ in range(rings):
            s = np.zeros_like(col)
            c = np.zeros(mask.shape)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    s += np.roll(np.roll(col * mask[..., None], dy, 0), dx, 1)
                    c += np.roll(np.roll(mask, dy, 0), dx, 1)
            fill = (~mask) & (c > 0)
            col[fill] = s[fill] / c[fill][:, None]
            mask |= fill
        return col

    def world_verts(o):
        co = np.empty(len(o.data.vertices) * 3, np.float32)
        o.data.vertices.foreach_get("co", co)
        m = np.array(o.matrix_world)
        return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]

    def frames(P):
        h = float(P[:, 2].max() - P[:, 2].min())
        c = (P.min(0) + P.max(0)) / 2
        head = P[P[:, 2] > P[:, 2].max() - 0.15 * h]
        hc = (head.min(0) + head.max(0)) / 2
        hc[2] = P[:, 2].max() - 0.07 * h
        return {"body": (c.tolist(), 1.08 * h), "head": (hc.tolist(), 0.19 * h)}, h

    def part_regions(P, h, fr, roles):
        """Centre and frame size of each close-up region, from the armature's joints."""
        arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
        M = arm.matrix_world

        def head(b):
            return np.array(M @ arm.data.bones[b].head_local)

        def tail(b):
            return np.array(M @ arm.data.bones[b].tail_local)

        hc, _ = fr["head"]
        reg = {"face": (hc, 0.13 * h), "head": (hc, 0.19 * h)}
        for s in ("l", "r"):
            a, g = roles[f"arm_{s}"], roles[f"leg_{s}"]
            hand = head(a["hand"]) + 1.1 * (tail(a["hand"]) - head(a["hand"]))   # the bone stops at the knuckles
            reg[f"hand_{s}"] = (hand.tolist(), 0.19 * h)
            foot = (head(g["ankle"]) + tail(g["foot"])) / 2
            reg[f"foot_{s}"] = (foot.tolist(), 0.16 * h)
            p0, p1 = head(a["elbow"]), tail(a["wrist"])
            reg[f"arm_{s}"] = (((p0 + p1) / 2).tolist(), 1.25 * float(np.linalg.norm(p1 - p0)))
            p0, p1 = head(g["hip"]), tail(g["knee"])
            reg[f"leg_{s}"] = (((p0 + p1) / 2).tolist(), 1.15 * float(np.linalg.norm(p1 - p0)))
        c = roles["chest"]
        reg["chest"] = (((head(c) + tail(c)) / 2).tolist(), 0.36 * h)
        reg["pelvis"] = (head(roles["root"]).tolist(), 0.30 * h)
        kl, kr = head(roles["leg_l"]["knee"]), head(roles["leg_r"]["knee"])
        reg["legs"] = (((kl + kr) / 2).tolist(), 0.55 * h)
        return reg

    def set_cam(sc, cam, v, fr):
        centre, ortho = (v["centre"], v["ortho"]) if "centre" in v else fr[v["kind"]]
        a, e = math.radians(v["yaw"]), math.radians(v["elev"])
        d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        cam.location = Vector(centre) + d * 3.0
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho
        sc.render.resolution_x, sc.render.resolution_y = v["res"]
        bpy.context.view_layer.update()

    def new_cam(sc):
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        sc.collection.objects.link(cam)
        sc.camera = cam
        return cam

    def eevee(sc, samples, png=True):
        sc.render.engine = "BLENDER_EEVEE_NEXT"
        sc.eevee.taa_render_samples = samples
        sc.render.film_transparent = True
        sc.view_settings.view_transform = "Standard"
        sc.view_settings.look = "None"
        if png:
            sc.render.filter_size = 1.5
            sc.render.image_settings.file_format = "PNG"
            sc.render.image_settings.color_depth = "8"
            sc.render.image_settings.color_mode = "RGBA"

    def emission_material(name, build):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        build(nt, out)
        return mat

    def with_material(obj, mat, fn):
        saved = [s.material for s in obj.material_slots]
        for s in obj.material_slots:
            s.material = mat
        try:
            return fn()
        finally:
            for s, m in zip(obj.material_slots, saved):
                s.material = m

    def lights(sc):
        for name, loc, energy in (("key", (-2, -3, 3), 2.5), ("fill", (3, -3, 1), 1.0), ("rim", (0, 3, 2), 1.5)):
            L = bpy.data.lights.new(name, "SUN")
            L.energy = energy
            o = bpy.data.objects.new(name, L)
            sc.collection.objects.link(o)
            o.location = loc
            o.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        w = bpy.data.worlds.new("w")
        sc.world = w
        w.use_nodes = True
        w.node_tree.nodes["Background"].inputs[0].default_value = (0.25, 0.25, 0.25, 1)

    def render(sc, path):
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)

    def render_uv_id(sc, obj, cam, path):
        """(u, v, |facing|, coverage) of the original UV map, 32-bit EXR, no AA."""
        fwd = cam.matrix_world.to_3x3() @ Vector((0, 0, -1))

        def build(nt, out):
            em = nt.nodes.new("ShaderNodeEmission")
            uv = nt.nodes.new("ShaderNodeUVMap")
            uv.uv_map = obj.data.uv_layers.active.name
            sep = nt.nodes.new("ShaderNodeSeparateXYZ")
            geo = nt.nodes.new("ShaderNodeNewGeometry")
            dot = nt.nodes.new("ShaderNodeVectorMath")
            dot.operation = "DOT_PRODUCT"
            dot.inputs[1].default_value = (-fwd.x, -fwd.y, -fwd.z)
            ab = nt.nodes.new("ShaderNodeMath")
            ab.operation = "ABSOLUTE"        # TRELLIS winding is inconsistent; only visible surface is in the image
            comb = nt.nodes.new("ShaderNodeCombineXYZ")
            nt.links.new(uv.outputs[0], sep.inputs[0])
            nt.links.new(geo.outputs["Normal"], dot.inputs[0])
            nt.links.new(dot.outputs["Value"], ab.inputs[0])
            nt.links.new(sep.outputs[0], comb.inputs[0])
            nt.links.new(sep.outputs[1], comb.inputs[1])
            nt.links.new(ab.outputs[0], comb.inputs[2])
            nt.links.new(comb.outputs[0], em.inputs[0])
            nt.links.new(em.outputs[0], out.inputs[0])

        mat = emission_material("uvid", build)
        eevee(sc, 1, png=False)
        sc.render.filter_size = 0.0
        sc.render.image_settings.file_format = "OPEN_EXR"
        sc.render.image_settings.color_depth = "32"
        sc.render.image_settings.color_mode = "RGBA"
        sc.render.image_settings.exr_codec = "ZIP"     # lossless; 2880^2 float EXRs are 133 MB uncompressed
        with_material(obj, mat, lambda: render(sc, path))
        img = bpy.data.images.load(path)
        img.colorspace_settings.name = "Non-Color"
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)   # bottom-up rows
        bpy.data.images.remove(img)
        return px

# ---------------------------------------------------------------------------- views
if MODE == "views":
    GLB, WORK = os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3])
    os.makedirs(WORK, exist_ok=True)
    body, bsdf, img, chart = load(GLB)
    sc = bpy.context.scene
    fr, h = frames(world_verts(body))
    cam = new_cam(sc)
    def build_flat(nt, out):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img
        em = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(t.outputs[0], em.inputs[0])
        nt.links.new(em.outputs[0], out.inputs[0])

    flat = emission_material("flat", build_flat)
    clay = bpy.data.materials.new("clay")
    clay.use_nodes = True
    cb = clay.node_tree.nodes["Principled BSDF"]
    cb.inputs["Base Color"].default_value = (0.3, 0.3, 0.3, 1)
    cb.inputs["Roughness"].default_value = 0.8
    lights(sc)
    views = view_list()
    look = load_look(LOOK_ARG)
    if len(sys.argv) > 4:                      # roles.json given: add the close-ups (PART_SHOTS)
        reg = part_regions(world_verts(body), h, fr, json.load(open(sys.argv[4])))
        for key, adj in look.get("regions", {}).items():
            for r in [r for r in reg if r == key or r.startswith(key + "_")]:
                c, o = reg[r]
                reg[r] = ([c[0], c[1], c[2] + adj.get("shift_up", 0) * h], o * adj.get("scale", 1))
        pres = tuple(look.get("part_res", PART_RES))
        for name, region, yaw, elev, shows, paint in PART_SHOTS:
            centre, ortho = reg[region]
            sh = look.get("shots", {}).get(name, {})
            views.append({"name": name, "kind": "part", "yaw": yaw, "elev": elev, "res": pres,
                          "centre": list(centre), "ortho": ortho, "shows": sh.get("shows", shows),
                          "paint": sh.get("paint", paint)})
    if "views" in look:
        views = [v for v in views if v["name"] in look["views"]]
    for v in views:
        if all(os.path.isfile(os.path.join(WORK, v["name"] + s)) for s in ("_flat.png", "_clay.png")):
            continue                           # keep renders a painting was already made from
        set_cam(sc, cam, v, fr)
        eevee(sc, 16)
        sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.0
        with_material(body, flat, lambda: render(sc, os.path.join(WORK, v["name"] + "_flat.png")))
        sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
        eevee(sc, 32)
        with_material(body, clay, lambda: render(sc, os.path.join(WORK, v["name"] + "_clay.png")))
        log("view", v["name"])
    json.dump({"frames": fr, "height": h, "views": views, "look": LOOK_ARG}, open(os.path.join(WORK, "cams.json"), "w"), indent=1)
    log("VIEWS_OK")

# ---------------------------------------------------------------------------- gen
if MODE == "gen":
    import concurrent.futures as cf
    import winreg

    import numpy as np
    from PIL import Image

    sys.path.insert(0, BOSS)
    from tools.painted_map_pipeline.openai_api import edit_image  # noqa: E402

    WORK, REF = os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3])
    only = set(sys.argv[4:])
    if not os.environ.get("OPENAI_API_KEY"):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            os.environ["OPENAI_API_KEY"] = winreg.QueryValueEx(k, "OPENAI_API_KEY")[0]
    all_views = saved_views(WORK)
    _cams = os.path.join(WORK, "cams.json")
    L = load_look(json.load(open(_cams)).get("look") if os.path.isfile(_cams) else None)
    costs = []

    def has_painting(name):
        acc = os.path.join(WORK, "gen", name, "ACCEPTED.txt")
        return os.path.isfile(acc) and os.path.isfile(os.path.join(open(acc).read().strip(), "output.png"))
    # selection: view names, "parts" (all close-ups), "missing" (every view with no finished painting yet)
    views = [v for v in all_views if not only or v["name"] in only or ("parts" in only and v["kind"] == "part")
             or ("missing" in only and not has_painting(v["name"]))]
    log(f"gen: {len(views)} views: {' '.join(v['name'] for v in views)}")

    def part_prompt(v):
        return (f"Produce the final colour texture for this {L['subject']} for a stylised fantasy action RPG. He is "
                "rendered as a small game sprite, so it must read strongly at a glance: hand-painted texture style, bold "
                "readable shapes, punchy colour, strong value contrast, clean confident edges - not photoreal, no pores or "
                f"fine noise. The camera shows a close-up of {v['shows']}. "
                "Image 1 is the current flat, unlit colour render of the 3D model from this camera; its colours are wrong "
                "and its detail is blurry. Image 2 is the same model from the same camera as plain grey clay with neutral "
                "lighting, so the true shape of every muscle, finger, toe and feature is visible. Image 3 is the original "
                f"character art: copy its design and colours - {L['design']}. Image 4 is the already-approved "
                f"painting of his whole body from the nearest angle: match its {L['match_part']} "
                f"exactly so this close-up joins it seamlessly. Paint {v['paint']}, {L['part_variation']}. "
                "This is a texture, not a new picture: the geometry "
                "is fixed. Every feature stays at exactly the same position, size and outline as in image 1, the view and "
                f"framing are identical and the silhouette must not change. {L['safety']}{L['finish_part']} "
                "Keep the plain grey background untouched.")

    def nearest_body_painting(v):
        bodies = [b for b in all_views if b["kind"] == "body" and os.path.isfile(accepted(b["name"]))]
        b = min(bodies, key=lambda b: min(abs(b["yaw"] - v["yaw"]) % 360, 360 - abs(b["yaw"] - v["yaw"]) % 360))
        return os.path.join(open(accepted(b["name"])).read().strip(), "output.png")

    def prompt_for(v, anchor):
        if v["kind"] == "part":
            return part_prompt(v).encode("ascii", "ignore").decode("ascii")
        where = YAW_NAMES[v["yaw"]] if v["kind"] == "body" else {"head_front": "face, from the front",
                "head_left": "head, three-quarter from his left side", "head_right": "head, three-quarter from his right side"}[v["name"]]
        crop = "the whole body" if v["kind"] == "body" else "a close-up of the head"
        p = (f"Produce the final colour texture for this {L['subject']} for a stylised fantasy action RPG. "
             f"The camera shows {crop}, looking at his {where}, from slightly above. "
             "Image 1 is the current flat, unlit colour render of the 3D model from this camera; its colours "
             "are wrong and its detail is blurry. Image 2 is the same model from the same camera as plain grey "
             "clay with neutral lighting, so the true shape of every muscle, finger, toe and feature is visible. "
             f"Image 3 is the original character art: copy its design and colours - {L['design']}. ")
        if anchor:
            p += (f"Image 4 is the already-approved painted front view of this same model: match its {L['match_body']} "
                  "exactly, so the views join seamlessly. ")
        p += (f"{L['body_paint']} This is a texture, not a new picture: the geometry is fixed. Every feature stays "
              "at exactly the same position, size and outline as in image 1, the view and framing are identical and "
              f"the silhouette must not change. {L['finish_body']} Keep the plain grey background untouched.")
        return p.encode("ascii", "ignore").decode("ascii")

    def grey_bg(src, dst):
        rgba = Image.open(src).convert("RGBA")
        bg = Image.new("RGBA", rgba.size, GREY + (255,))
        bg.alpha_composite(rgba)
        bg.convert("RGB").save(dst)

    def run(v, anchor):
        d = os.path.join(WORK, "gen", v["name"])
        n = 1 + len([x for x in os.listdir(d) if x.startswith("attempt_")]) if os.path.isdir(d) else 1
        a = os.path.join(d, f"attempt_{n}")
        os.makedirs(a)
        grey_bg(os.path.join(WORK, v["name"] + "_flat.png"), os.path.join(a, "input.png"))
        grey_bg(os.path.join(WORK, v["name"] + "_clay.png"), os.path.join(a, "clay.png"))
        Image.open(REF).convert("RGB").save(os.path.join(a, "ref.png"))
        imgs = [os.path.join(a, x) for x in ("input.png", "clay.png", "ref.png")]
        if anchor:
            imgs.append(anchor)
        p = prompt_for(v, anchor)
        open(os.path.join(a, "prompt.txt"), "w").write(p + "\n")
        w, h = v["res"]
        t = time.time()
        info = edit_image(prompt=p, input_images=[__import__("pathlib").Path(x) for x in imgs], mask=None,
                          output_path=__import__("pathlib").Path(os.path.join(a, "output.png")), width=w, height=h,
                          config={"quality": L.get("quality", "high"), "config_source": "barb_paint"})
        alpha = np.asarray(Image.open(os.path.join(WORK, v["name"] + "_flat.png")).convert("RGBA"))[..., 3] > 8
        rgb = np.asarray(Image.open(os.path.join(a, "output.png")).convert("RGB")).astype(int)
        ng = np.abs(rgb - np.array(GREY)).max(2) > 18
        iou = float((ng & alpha).sum() / max((ng | alpha).sum(), 1))
        cost = usd(info.get("usage"))
        costs.append(cost)
        json.dump({"iou": iou, "usage": info.get("usage"), "usd": cost, "seconds": time.time() - t},
                  open(os.path.join(a, "check.json"), "w"))
        log(f"GEN {v['name']} attempt_{n} iou {iou:.3f} {time.time() - t:.0f}s ${cost:.2f}")
        return a

    front = os.path.join(WORK, "gen", "body_000")
    accepted = lambda name: os.path.join(WORK, "gen", name, "ACCEPTED.txt")
    if any(v["name"] == "body_000" for v in views):
        a = run(next(v for v in views if v["name"] == "body_000"), None)
        open(accepted("body_000"), "w").write(a + "\n")
        views = [v for v in views if v["name"] != "body_000"]
    anchor = os.path.join(open(accepted("body_000")).read().strip(), "output.png")
    with cf.ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(run, v, nearest_body_painting(v) if v["kind"] == "part" else anchor): v for v in views}
        for f in cf.as_completed(futs):
            v = futs[f]
            try:
                done = f.result()                      # raises if the call failed: then write nothing
            except Exception as e:                     # one failed view must not lose the others
                log(f"GEN_FAIL {v['name']} {e}")
                continue
            open(accepted(v["name"]), "w").write(done + "\n")
    total = 0.0
    for root, _, files in os.walk(os.path.join(WORK, "gen")):
        if "check.json" in files:
            total += usd(json.load(open(os.path.join(root, "check.json"))).get("usage"))
    log(f"COST this run ${sum(costs):.2f} ({len(costs)} paintings); all paintings in {WORK}: ${total:.2f}")
    log("GEN_DONE")

# ---------------------------------------------------------------------------- project
if MODE == "project":
    GLB, WORK = os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3])
    OUT = os.path.join(WORK, "result")
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    body, bsdf, img, chart = load(GLB, upscale=True)
    sc = bpy.context.scene
    meta = json.load(open(os.path.join(WORK, "cams.json")))
    fr = {k: (tuple(v[0]), v[1]) for k, v in meta["frames"].items()}
    cam = new_cam(sc)
    W, H = img.size
    atlas = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)
    old = atlas[..., :3].copy()

    import cv2

    def align(paint, v):
        """gpt-image-2 redraws the figure a little larger/shifted than the mesh. Fit one affine warp
        (ECC on silhouette + shading, 720 px) of the painting onto the model's own renders and apply it.
        Returns (aligned RGB, ecc, scale); a dense optical flow was tried and smears the painting."""
        def on_grey(path):
            im = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32)
            a = im[..., 3:4] / 255.0
            return (im[..., :3] * a + 128 * (1 - a)).astype(np.uint8), a[..., 0]
        clay, alpha = on_grey(os.path.join(WORK, v["name"] + "_clay.png"))
        flat, _ = on_grey(os.path.join(WORK, v["name"] + "_flat.png"))
        Hh, Ww = clay.shape[:2]
        p = np.asarray(paint.resize((Ww, Hh), Image.LANCZOS))
        s = 720 / max(Hh, Ww)

        def feat(img, mask):
            g = cv2.cvtColor(cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
            return cv2.GaussianBlur(0.6 * mask + 0.4 * g.astype(np.float32) / 255, (0, 0), 3)
        small_p = cv2.resize(p, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        guide = feat(cv2.addWeighted(clay, 0.5, flat, 0.5, 0), (cv2.resize(alpha, None, fx=s, fy=s) > 0.5).astype(np.float32))
        target = feat(p, (np.abs(small_p.astype(int) - 128).max(2) > 14).astype(np.float32))
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            cc, warp = cv2.findTransformECC(guide, target, warp, cv2.MOTION_AFFINE,
                                            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), None, 5)
        except cv2.error:
            return None, 0.0, 0.0
        warp[:, 2] /= s
        scale = float(np.sqrt(abs(np.linalg.det(warp[:, :2]))))
        out = cv2.warpAffine(p, warp, (Ww, Hh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=GREY)
        return Image.fromarray(out), float(cc), scale

    PATCH = {"views": [], "dropped": []}

    def cached_uv_id(v, size):
        """The UV-id render only depends on the mesh and the camera: reuse it when both are unchanged
        (speed only; the same EXR either way). Keyed on the GLB's size/mtime and the camera settings."""
        exr = os.path.join(OUT, f"uvid_{v['name']}.exr")
        key = json.dumps({"glb": [os.path.getsize(GLB), os.path.getmtime(GLB)], "res": list(size),
                          "cam": [v.get("centre"), v.get("ortho"), v["kind"], v["yaw"], v["elev"]]}, sort_keys=True)
        if os.path.isfile(exr) and os.path.isfile(exr + ".key") and open(exr + ".key").read() == key:
            im = bpy.data.images.load(exr)
            im.colorspace_settings.name = "Non-Color"
            w, h = im.size
            px = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)
            bpy.data.images.remove(im)
            return px
        set_cam(sc, cam, dict(v, res=size), fr)
        px = render_uv_id(sc, body, cam, exr)
        open(exr + ".key", "w").write(key)
        return px

    def splat_layer(kind, ref=None, ref_ok=None):
        """ref (linear) / ref_ok: the layers already painted; each view is first tone-matched to them
        (per channel gain + offset on the texels both cover), so close-ups join without a seam."""
        acc = np.zeros((H, W, 3), np.float32)
        if kind == "part":                     # for the patch report: which close-up wins each texel
            PATCH["winner"] = np.full((H, W), -1, np.int16)
            PATCH["wmax"] = np.zeros((H, W), np.float32)
        wsum = np.zeros((H, W), np.float32)
        best = np.zeros((H, W), np.float32)
        for v in meta["views"]:
            if v["kind"] != kind:
                continue
            acc_file = os.path.join(WORK, "gen", v["name"], "ACCEPTED.txt")
            out_png = os.path.join(open(acc_file).read().strip(), "output.png") if os.path.isfile(acc_file) else ""
            if not os.path.isfile(out_png):
                log("no paint for", v["name"])
                continue
            paint, cc, scale = align(Image.open(out_png).convert("RGB"), v)
            if paint is None or cc < 0.95 or not 0.85 <= scale <= 1.18:
                log(f"DROP {v['name']}: will not align onto the mesh (ecc {cc:.3f}, scale {scale:.2f}) - a ghost source")
                PATCH["dropped"].append({"view": v["name"], "ecc": round(cc, 4), "scale": round(scale, 3)})
                continue
            set_cam(sc, cam, dict(v, res=paint.size), fr)
            idpx = cached_uv_id(v, paint.size)
            p_rgb = np.flipud(np.asarray(paint, dtype=np.float32) / 255.0)
            p_rgb = p_rgb ** 2.2                       # average in linear light; back to sRGB in splat_srgb
            alpha = np.flipud(np.asarray(Image.open(os.path.join(WORK, v["name"] + "_flat.png")).convert("RGBA"))[..., 3] / 255.0)
            u, vv, f, cov = idpx[..., 0], idpx[..., 1], idpx[..., 2], idpx[..., 3]
            # gpt-image-2 redraws the figure a little off the mesh (hands, feet): where the painting
            # shows the grey background, or the blended rim next to it, do not project it.
            bgm = np.abs(np.flipud(np.asarray(paint, dtype=np.int16)) - np.array(GREY)).max(2) <= 12
            for _ in range(3):
                bgm = bgm | np.roll(bgm, 1, 0) | np.roll(bgm, -1, 0) | np.roll(bgm, 1, 1) | np.roll(bgm, -1, 1)
            ok = (cov > 0.5) & (alpha > 0.5) & (f > 0.2) & ~bgm
            t = np.clip((f - 0.2) / 0.5, 0, 1)
            sm = t * t * (3 - 2 * t)
            wgt = (sm * f ** 12)[ok]                  # near winner-takes-all: overlapping views must not stack into ghosts
            xi = np.clip((u[ok] * W).astype(np.int64), 0, W - 1)
            yi = np.clip((vv[ok] * H).astype(np.int64), 0, H - 1)
            note = ""
            if ref is not None:
                both = ref_ok[yi, xi] & (sm[ok] > 0.5)
                if both.sum() > 2000:
                    # colour balance only: one gain per channel from the medians. A straight-line fit
                    # (gain + offset) flattened the close-ups to 30-50 % contrast: they never line up
                    # pixel-exactly with the body paint, and a fit on misaligned data comes out too flat.
                    src, dst = p_rgb[ok][both], ref[yi[both], xi[both]]
                    gains = np.clip(np.median(dst, 0) / np.maximum(np.median(src, 0), 1e-4), 0.7, 1.4)
                    p_rgb = np.clip(p_rgb * gains, 0, 1)
                    note = f"  colour gain {' '.join(f'{g:.2f}' for g in gains)} on {both.sum()} px"
            for c in range(3):
                np.add.at(acc[..., c], (yi, xi), p_rgb[..., c][ok] * wgt)
            np.add.at(wsum, (yi, xi), wgt)
            np.maximum.at(best, (yi, xi), sm[ok])
            if kind == "part":
                tmp = np.zeros((H, W), np.float32)
                np.maximum.at(tmp, (yi, xi), wgt)
                won = tmp > PATCH["wmax"]
                PATCH["winner"][won] = len(PATCH["views"])
                PATCH["wmax"][won] = tmp[won]
                PATCH["views"].append(dict(v, ecc=cc, scale=scale))
            log(f"splat {v['name']}  {ok.sum()} px  ecc {cc:.3f} scale {scale:.2f}  {time.time() - t0:.0f}s{note}")
        hit = wsum > 0
        col = np.zeros((H, W, 3), np.float32)
        col[hit] = acc[hit] / wsum[hit][:, None]
        return col, hit, best

    def fill_holes(col, hit, strength, rings):
        """Un-hit chart texels next to hit ones take the neighbour mean (screen pixels can be
        sparser than texels); each ring a little weaker."""
        for _ in range(rings):
            s = np.zeros_like(col); b = np.zeros_like(strength); c = np.zeros((H, W))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    hs = np.roll(np.roll(hit, dy, 0), dx, 1)
                    s += np.roll(np.roll(col * hit[..., None], dy, 0), dx, 1)
                    b += np.roll(np.roll(strength * hit, dy, 0), dx, 1)
                    c += hs
            fill = (~hit) & (c > 0) & chart
            col[fill] = s[fill] / c[fill][:, None]
            strength[fill] = b[fill] / c[fill] * 0.85
            hit = hit | fill
        return col, hit, strength

    # bpy float pixels of an 8-bit sRGB image hold the sRGB values; keep everything in that space
    def splat_srgb(kind, ref=None, ref_ok=None):
        col, hit, best = splat_layer(kind, None if ref is None else ref ** 2.2, ref_ok)
        col = np.where(hit[..., None], col ** (1 / 2.2), 0)
        return col, hit, best

    body_col, body_hit, body_best = splat_srgb("body")
    body_col, body_hit, body_best = fill_holes(body_col, body_hit, body_best, 4)
    head_col, head_hit, head_best = splat_srgb("head")
    head_col, head_hit, head_best = fill_holes(head_col, head_hit, head_best, 4)

    # unseen texels: old colour through an affine colour map fitted where paint landed head-on
    fit = body_hit & (body_best > 0.8) & chart
    X = np.c_[old[fit], np.ones(fit.sum())]
    M, *_ = np.linalg.lstsq(X, body_col[fit], rcond=None)
    remap = np.clip(np.c_[old.reshape(-1, 3), np.ones(H * W)] @ M, 0, 1).reshape(H, W, 3)
    log(f"colour map fitted on {fit.sum()} texels; painted {100 * (body_hit & chart).sum() / chart.sum():.1f}% of chart texels")

    b = np.clip(body_best, 0, 1)[..., None]
    new = remap * (1 - b) + body_col * b
    hb = np.clip(head_best * 1.5, 0, 1)[..., None]
    new = new * (1 - hb) + head_col * hb
    # close-ups last: tone-matched to everything painted so far, then they win where they look head-on
    if any(v["kind"] == "part" for v in meta["views"]):
        part_col, part_hit, part_best = splat_srgb("part", new, (body_hit | head_hit) & chart)
        part_col, part_hit, part_best = fill_holes(part_col, part_hit, part_best, 4)
        pb = np.clip(part_best * 1.5, 0, 1)[..., None]
        PATCH["before"] = new.copy()           # everything except the close-ups
        new = new * (1 - pb) + part_col * pb
        PATCH["blend"] = pb[..., 0]
        log(f"close-ups cover {100 * (part_hit & chart).sum() / chart.sum():.1f}% of chart texels")
    new[~chart] = 0
    new = grow(new, chart, 16)
    final = atlas.copy()
    final[..., :3] = new
    Image.fromarray((np.clip(np.flipud(old), 0, 1) * 255).astype(np.uint8)).save(os.path.join(OUT, "atlas_before.png"))
    Image.fromarray((np.clip(np.flipud(new), 0, 1) * 255).astype(np.uint8)).save(os.path.join(OUT, "atlas_after.png"))

    # before / after, neutral light, the same cameras for both
    lights(sc)
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    SHOTS = [{"kind": "body", "yaw": 0, "elev": 15}, {"kind": "body", "yaw": 45, "elev": 15},
             {"kind": "body", "yaw": 90, "elev": 15}, {"kind": "body", "yaw": 180, "elev": 15},
             {"kind": "head", "yaw": 0, "elev": 10}, {"kind": "head", "yaw": 45, "elev": 10}]
    SHOTS += [dict(v) for v in meta["views"] if v["name"] in ("face_front", "hand_l_out", "foot_l_front", "chest_front")]

    def shots(tag):
        eevee(sc, 32)
        out = []
        for i, v in enumerate(SHOTS):
            set_cam(sc, cam, dict(v, res=(768, 768)), fr)
            p = os.path.join(OUT, f"{tag}_{i}_{v.get('name', v['kind'])}_{v['yaw']}.png")
            render(sc, p)
            out.append(p)
        return out

    before = shots("before")
    img.pixels[:] = final.ravel()
    img.update()
    after = shots("after")
    sheet = Image.new("RGB", (768 * len(SHOTS), 768 * 2 + 40), (40, 40, 44))
    d = ImageDraw.Draw(sheet)
    for i, (pb, pa) in enumerate(zip(before, after)):
        for r, p in enumerate((pb, pa)):
            im = Image.open(p).convert("RGBA")
            bg = Image.new("RGBA", im.size, (70, 70, 76, 255))
            bg.alpha_composite(im)
            sheet.paste(bg.convert("RGB"), (i * 768, 20 + r * 788))
    d.text((8, 4), "BEFORE: TRELLIS colour", fill=(235, 235, 235))
    d.text((8, 790), "AFTER: painted views projected", fill=(235, 235, 235))
    try:
        sheet.save(os.path.join(OUT, "BEFORE_AFTER.png"))
    except OSError as e:                       # open in a viewer on Windows: keep going, the model matters more
        log(f"BEFORE_AFTER not saved: {e}")

    img.pack()
    bpy.ops.object.select_all(action="DESELECT")
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    for o in (body, arm):
        if o:
            o.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, os.path.splitext(os.path.basename(GLB))[0] + "_painted.glb"),
                              use_selection=True)
    # ---- patch report (after the export: a report failure must never cost the model): per close-up, the model from its camera without it / with it / where it painted
    def patch_report():
        if PATCH["views"]:
            pdir = os.path.join(OUT, "patches")
            os.makedirs(pdir, exist_ok=True)
            R = 640

            def tex_state(rgb):
                st = atlas.copy()
                st[..., :3] = grow(np.where(chart[..., None], rgb, 0), chart, 4)
                img.pixels[:] = st.ravel()
                img.update()

            def cam_shots(tag):
                eevee(sc, 16)
                for v in PATCH["views"]:
                    set_cam(sc, cam, dict(v, res=(R, R)), fr)
                    render(sc, os.path.join(pdir, f"_{v['name']}_{tag}.png"))

            tex_state(PATCH["before"]); cam_shots("before")
            tex_state(new); cam_shots("after")
            bc, bo = fr["body"]                    # zoomed out, same direction, the close-up's frame drawn on
            for v in PATCH["views"]:
                set_cam(sc, cam, {"kind": "body", "yaw": v["yaw"], "elev": v["elev"], "res": (R, R)}, fr)
                ctx = os.path.join(pdir, f"_{v['name']}_context.png")
                render(sc, ctx)
                M3 = cam.matrix_world.to_3x3()
                right, up = M3 @ Vector((1, 0, 0)), M3 @ Vector((0, 1, 0))
                off = Vector(v["centre"]) - Vector(bc)
                cx, cy = R / 2 + off.dot(right) / bo * R, R / 2 - off.dot(up) / bo * R
                half = v["ortho"] / bo * R / 2
                im = Image.open(ctx).convert("RGBA")
                bg = Image.new("RGBA", im.size, (70, 70, 76, 255)); bg.alpha_composite(im)
                ImageDraw.Draw(bg).rectangle((cx - half, cy - half, cx + half, cy + half), outline=(255, 40, 160, 255), width=4)
                bg.convert("RGB").save(ctx)
            stats = []
            for i, v in enumerate(PATCH["views"]):
                mine = (PATCH["winner"] == i) & (PATCH["blend"] > 0.3) & chart
                share = 100 * mine.sum() / chart.sum()
                tint = np.where(mine[..., None], new * 0.45 + np.array([1.0, 0.15, 0.6]) * 0.55, new * 0.6)
                tex_state(tint)
                set_cam(sc, cam, dict(v, res=(R, R)), fr)
                render(sc, os.path.join(pdir, f"_{v['name']}_where.png"))
                sheet = Image.new("RGB", (4 * R, R + 26), (40, 40, 44))
                d = ImageDraw.Draw(sheet)
                for k, tag in enumerate(("context", "before", "after", "where")):
                    im = Image.open(os.path.join(pdir, f"_{v['name']}_{tag}.png")).convert("RGBA")
                    bg = Image.new("RGBA", im.size, (70, 70, 76, 255)); bg.alpha_composite(im)
                    sheet.paste(bg.convert("RGB"), (k * R, 26))
                d.text((6, 6), f"{v['name']}: where the camera looks (box) | without this patch | with it | where it painted (pink): "
                               f"{share:.2f}% of the texture   (align ecc {v['ecc']:.3f}, scale {v['scale']:.2f})", fill=(255, 255, 255))
                sheet.save(os.path.join(pdir, f"{v['name']}.png"))
                stats.append({"view": v["name"], "share_pct": round(share, 3), "ecc": round(v["ecc"], 4), "scale": round(v["scale"], 3)})
                log(f"patch {v['name']}: {share:.2f}% of the texture")
            stats.sort(key=lambda r: -r["share_pct"])
            json.dump({"patches": stats, "dropped": PATCH["dropped"]}, open(os.path.join(pdir, "patches.json"), "w"), indent=1)
            T = 420                                # index: every patch's "with it" shot, biggest first
            cols = 5
            idx = Image.new("RGB", (cols * T, ((len(stats) + cols - 1) // cols) * (T + 22)), (40, 40, 44))
            d = ImageDraw.Draw(idx)
            for k, r in enumerate(stats):
                im = Image.open(os.path.join(pdir, f"{r['view']}.png")).convert("RGB")
                im = im.crop((2 * R, 26, 3 * R, 26 + R)).resize((T, T))
                y, x = divmod(k, cols)
                idx.paste(im, (x * T, y * (T + 22) + 22))
                d.text((x * T + 6, y * (T + 22) + 4), f"{r['view']}  {r['share_pct']:.2f}%", fill=(255, 255, 255))
            idx.save(os.path.join(pdir, "PATCHES_INDEX.png"))
            img.pixels[:] = final.ravel()          # back to the real texture for the export
            img.update()

    try:
        patch_report()
    except Exception as e:                 # e.g. a report image open in a viewer on Windows
        log(f"PATCH_REPORT_FAIL {e}")
    log(f"PROJECT_OK {time.time() - t0:.0f}s -> {OUT}")
