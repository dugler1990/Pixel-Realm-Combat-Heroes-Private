"""The plan pass: paint the floor plan flat, trace it, check it, rank the draws.

This is loop A. It is cheap not because flat colour is cheap -- a call costs the same
whatever it paints -- but because it runs at PLAN_EDGE rather than the 8.3 MP cap, and
because every check on the result is a mask operation costing nothing. A bad plan is found
and thrown away before a single stone is painted.

The sampler is unseeded: the same prompt and input give materially different plans run to
run. `--draws N` was already the right lever and already existed; what it lacked was any
reason to prefer one draw over another except an eye on a contact sheet. Now the checks
order the sheet and say why.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..building_interiors import (
    LAYOUT_MAX_PIXELS,
    BuildingInteriorError,
    _mask_image,
    _run_edit,
    build_masks,
    check_border,
    paste_back,
    snap_uniform,
)
from ..image_client import make_image_client
from ..world_levels.masks import rasterize_polygon
from . import checks as layout_checks
from .prompt import CORRIDOR_PLAYERS, ROOM_PLAYERS, plan_prompt, with_criticism
from .player_size import player_size
from .trace import (
    CLASS_COLOURS,
    OUTER_RGB,
    save_image,
    component_report,
    derive_art_classes,
    partition_with_reject,
    trace_boundaries,
)

Image.MAX_IMAGE_PIXELS = None

# Long edge of the plan pass. The trace needs boundaries resolved to roughly a tile, not to
# a block: at 1536 across a 3600 px building, one 150 px tile is still 64 px. Running it at
# the full 8.3 MP cap buys nothing the tracer can use and costs the same as stonework.
PLAN_EDGE = 1536
EDGE_MULTIPLE = 16
# The wall band and the collision quads both come from `spec.partition`, which is derived
# from the shell thickness `ask_model` measured off the building's own art. There is
# deliberately no constant here: one used to sit in this module and another in `emit`, both
# 160 px, neither aware of the measurement.


@dataclass
class Plan:
    """A traced, checked floor plan at canvas resolution."""

    spec: object
    floor: np.ndarray
    chamber: np.ndarray
    silhouette: np.ndarray
    classes: dict
    report: dict
    painted_path: Path = None
    composited_path: Path = None
    # The draw with its shape error marked, written whenever there was a mask to measure
    # against. What `r1` attaches, so the model is shown where it missed rather than told.
    shape_path: Path = None

    @property
    def passed(self) -> bool:
        return self.report["passed"]

    @property
    def failed(self) -> list:
        return self.report["failed"]

    def boundaries(self):
        """Floor boundaries in world px: what the emitter lays collision along."""
        from .trace import to_world

        return [(to_world(b.polygon, self.spec.origin), b.is_hole)
                for b in trace_boundaries(self.floor)]


def plan_size(size) -> tuple:
    """Downscale for the plan pass: long edge PLAN_EDGE, both edges divisible by 16.

    Snapped by the same helper the render pass uses, so the plan and the render are drawn on
    canvases that distort the building identically -- see `snap_uniform` for why nearest
    rather than floor.
    """
    scale = min(1.0, PLAN_EDGE / float(max(size)))
    return snap_uniform(size, scale, LAYOUT_MAX_PIXELS)


def door_mask(spec):
    """The painted door, as a mask at canvas resolution. Zeros when none is authored.

    One polygon, four readers: held out of the editable region here, written back over
    the render (`render.restore_doorway`), kept out of the chamber and the wall quads
    (`emit`), and -- on the map as `door_of` -- the overhead area the engine hides a body
    under. It is the frame painted on the exterior (lintel, jambs, opening), and it
    straddles the silhouette: a mask cutting through it would ask the model to reinvent
    half an arch, and it never does.
    """
    mask = np.zeros((spec.size[1], spec.size[0]), dtype=bool)
    for door in spec.doors:
        mask |= np.asarray(rasterize_polygon(spec.size, door)) > 0
    return mask


def geometry_masks(spec):
    """(silhouette, chamber, editable) at canvas resolution.

    The editable region is the authored chamber minus the door. Holding the whole door
    out keeps it byte-identical in both views, and it is what puts the room's edge behind
    the painted door: a floor can only start where the brush was allowed.
    """
    silhouette = np.asarray(rasterize_polygon(spec.size, spec.silhouette)) > 0
    chamber = np.asarray(rasterize_polygon(spec.size, spec.chamber)) > 0
    return silhouette, chamber, chamber & ~door_mask(spec)


def trace_plan(painted, spec, silhouette, chamber, editable, extra_checks=()) -> Plan:
    """Classify a plan painting and run every check on it. No API, no spend.

    `extra_checks` carries results that could not be computed from the canvas-local masks --
    the shape pair, which needs the raw return and the mask actually sent at generation
    resolution. They join the same report so there is one verdict and one ranking.
    """
    partition = partition_with_reject(np.asarray(painted.convert("RGB")), editable)
    return trace_plan_from_mask(partition.masks["floor"], spec, silhouette, chamber, editable,
                                unpainted=partition.unpainted_fraction,
                                extra_checks=extra_checks)


def control_image(plan) -> Image.Image:
    """The three-colour picture the render pass is told to paint.

    Wall is not painted by the model and not guessed at here: it is the floor dilated by the
    emitter's own thickness, so the band the render pass is shown is exactly the band the
    collision quads occupy.
    """
    canvas = np.zeros((plan.spec.size[1], plan.spec.size[0], 3), dtype=np.uint8)
    canvas[plan.classes["solid"]] = (90, 84, 78)
    canvas[plan.classes.get("outer", plan.classes["wall"] & False)] = OUTER_RGB
    canvas[plan.classes["wall"]] = CLASS_COLOURS["solid"]
    canvas[plan.classes["floor"]] = CLASS_COLOURS["floor"]
    return Image.fromarray(canvas, mode="RGB")


def _character(image: Image.Image, spec) -> Image.Image:
    """Paste the player at true scale: in the doorway, and again as a key in the corner.

    Every check on this plan is really a question about whether a person fits, and a number
    saying `radius_tiles 0.18` does not answer it the way a figure standing in the gap does.
    The sprite goes on unscaled -- `Player.scale_animation` is dead behind an unset attribute,
    so the frames are blitted at native size and that IS the player.
    """
    from .player_size import player_size

    measured = player_size(scale=spec.world_scale)
    if not measured.sprite:
        return image
    sprite_path = Path(__file__).resolve().parents[3] / measured.sprite
    if not sprite_path.exists():
        return image

    with Image.open(sprite_path) as source:
        sprite = source.convert("RGBA")
    # Trim to the opaque box so "true scale" means the character, not his empty frame.
    box = sprite.getbbox()
    if box:
        sprite = sprite.crop(box)
    # Into this level's painted px: the engine draws the art `world_scale` times bigger
    # than this canvas, so the man on it is that much smaller than his sprite.
    if sprite.size != (measured.width, measured.height):
        sprite = sprite.resize((measured.width, measured.height), Image.NEAREST)

    from PIL import ImageDraw

    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    def place(x, y, label=""):
        """The figure, plus a ring so it can be found on a 1000 px canvas.

        Unringed he is 53 px against a building twenty times that, and on the contact sheet
        half of it again -- present but invisible, which is no use as a scale reference.
        """
        canvas.paste(sprite, (int(x), int(y)), sprite)
        draw.rectangle([x - 3, y - 3, x + sprite.width + 2, y + sprite.height + 2],
                       outline=(255, 255, 0), width=3)
        if label:
            draw.text((x, y + sprite.height + 6), label, fill=(255, 255, 0))

    if spec.door_origin:
        place(spec.door_origin[0] - sprite.width / 2,
              spec.door_origin[1] - sprite.height / 2)
    place(14, canvas.height - sprite.height - 26, f"1 person = {sprite.width}px")

    # A bar one corridor wide, so the width being asked for is on the picture too rather than
    # only in the prompt.
    from .prompt import CORRIDOR_PLAYERS

    corridor = int((getattr(spec, "corridor_players", None) or CORRIDOR_PLAYERS)[0]
                   * sprite.width)
    top = canvas.height - 16
    draw.rectangle([14, top - 6, 14 + corridor, top], fill=(80, 220, 255))
    draw.text((18 + corridor, top - 8), f"corridor {corridor}px", fill=(80, 220, 255))
    return canvas.convert("RGB")


def overlay(plan, roof) -> Image.Image:
    """The plan laid over the exterior, for looking at. Floor tinted, walls outlined."""
    base = np.asarray(roof.convert("RGB")).astype(np.float32)
    outer = plan.classes.get("outer")
    tint = np.zeros_like(base)
    tint[plan.classes["floor"]] = CLASS_COLOURS["floor"]
    tint[plan.classes["wall"]] = CLASS_COLOURS["solid"]
    painted_classes = plan.classes["floor"] | plan.classes["wall"]
    if outer is not None:
        tint[outer] = OUTER_RGB
        painted_classes = painted_classes | outer
    mask = painted_classes[..., None]
    blended = np.where(mask, base * 0.45 + tint * 0.55, base)
    return _character(Image.fromarray(blended.astype(np.uint8), mode="RGB"), plan.spec)


def synthetic_plan(spec) -> Plan:
    """A procedural crypt, drawn from the spec's own door plane. No API key needed.

    The offline default, the way `region_proposer`'s `grid` provider is: it lets the emitter,
    the preview and the whole command surface run end to end -- at the real building's scale,
    against its real doorway -- without a model or a penny. It is deliberately plain, because
    its job is to prove the plumbing, not to be a good dungeon.
    """
    silhouette, chamber, editable = geometry_masks(spec)
    if not spec.door_origin:
        raise BuildingInteriorError(f"{spec.building} has no door plane to build a plan from")

    inward = np.asarray(spec.door_inward, dtype=float)
    tangent = np.asarray([-inward[1], inward[0]])
    origin = np.asarray(spec.door_origin, dtype=float)
    tile = spec.tile
    floor = np.zeros(chamber.shape, dtype=bool)

    def box(centre, along, across):
        """Rectangle in door-plane coordinates, rasterised into the floor."""
        half_a, half_c = along / 2.0, across / 2.0
        corners = [centre + inward * s * half_a + tangent * t * half_c
                   for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        polygon = tuple((float(p[0]), float(p[1])) for p in corners)
        return np.asarray(rasterize_polygon(spec.size, polygon)) > 0

    # Corridor straight in from the threshold, then a chamber at its end with a room either
    # side, each joined by a gap rather than opening along its whole flank.
    corridor_length = 7.0 * tile
    floor |= box(origin + inward * (corridor_length / 2.0), corridor_length, 1.6 * tile)
    far = origin + inward * (corridor_length + 2.0 * tile)
    floor |= box(far, 4.0 * tile, 5.0 * tile)
    for side in (-1, 1):
        centre = origin + inward * (corridor_length * 0.55) + tangent * side * 3.0 * tile
        floor |= box(centre, 3.5 * tile, 3.5 * tile)
        joint = origin + inward * (corridor_length * 0.55) + tangent * side * 1.4 * tile
        floor |= box(joint, 1.4 * tile, 1.6 * tile)

    floor &= editable
    return trace_plan_from_mask(floor, spec, silhouette, chamber, editable, unpainted=0.0)


def single_room_plan(spec) -> Plan:
    """One room: a clean floor, a clean ring of wall around it, the passage to the door.
    No model, no API, no wobble.

    A model asked for a single room paints a slightly-off polygon with wavy edges, and it is
    different every draw. There is nothing to decide, so nothing to ask: the chamber is the
    silhouette inset by the measured shell with the passage carved to the threshold, and the
    room is that, inset once more by a wall's thickness. Deterministic, identical every run.

    The floor is the whole chamber. Everything else inside the outline is the building's
    mass, which the render pass paints (`render.paint_region`): the model draws the walls
    where it thinks they go, and the paste keeps them wherever that is.

    A version of this inset the floor by a wall's thickness so the collision quads would
    land where the model tends to stop its floor. That is a guess against one render, and
    it costs 60 px of room all round; the room is the room, and if the painted floor edge
    and the collision disagree by a course, `r1` is the tool for it, not a smaller plan.
    """
    silhouette, chamber, editable = geometry_masks(spec)
    if not spec.door_origin:
        raise BuildingInteriorError(f"{spec.building} has no door plane to build a plan from")
    return trace_plan_from_mask(editable.copy(), spec, silhouette, chamber, editable, unpainted=0.0)


def trace_plan_from_mask(floor, spec, silhouette, chamber, editable=None, unpainted=0.0,
                         corridor_half_width=None, extra_checks=(), classes=None) -> Plan:
    """A checked Plan from a floor mask. The one place a Plan is built.

    `corridor_half_width` is what `room_count` erodes by to make corridors vanish and leave
    rooms. Unset, it is a whole tile, which is right for a painted dungeon and wrong for a
    plan that knows its own corridors: a one-room plan's only corridor is the passage, and
    eroding a diamond by a tile loses area far faster than a rectangle does -- the room was
    there, a 300 px disk sat inside it, and the check still called it no room at all. So a
    single-room spec erodes by half its door gap, whoever built the floor.

    `classes` are the art classes. Left unset they are derived from the floor
    (`derive_art_classes`: the wall band is a partition grown from the floor) -- a request,
    something to paint. Given, they are what a painting named: the floor pass traces the
    accepted render into floor / wall / outer and hands them in as they are.
    """
    from .runtime import building_geometry

    _player = player_size(scale=spec.world_scale)
    if corridor_half_width is None and spec.rooms == 1:
        corridor_half_width = (spec.door_gap or building_geometry().DEFAULT_DOOR_GAP) / 2.0
    geometry = layout_checks.PlanGeometry(
        floor=floor,
        chamber=chamber,
        silhouette=silhouette,
        editable=editable,
        door_origin=spec.door_origin or (0, 0),
        door_inward=spec.door_inward or (0, 1),
        unpainted_fraction=unpainted,
        tile=spec.tile,
        expected_rooms=spec.rooms,
        # The passability gate measures against the real character, not the tile. A frame is
        # scaled to a whole tile but the widest character on the roster is 127 px, so the
        # unfed default was demanding ~18% more clearance than anyone needs.
        player_half_width=_player.width / 2.0,
        corridor_half_width=corridor_half_width,
        player_width=_player.width,
        player_height=_player.height,
    )
    if classes is None:
        classes = derive_art_classes(floor, chamber, spec.partition,
                                     silhouette=silhouette, keep_clear=door_mask(spec))
    return Plan(
        spec=spec,
        floor=floor,
        chamber=chamber,
        silhouette=silhouette,
        classes=classes,
        report=layout_checks.run_checks(geometry, extra_checks),
    )


def preflight(spec) -> str:
    """Why this building cannot hold a plan, or "" when it can.

    Arithmetic, before any API call. The wall thickness already refuses rather than guess; a
    chamber that cannot fit a doorway and a corridor is the same kind of fact, and three draws
    that cannot pass cost three calls to discover it.
    """
    from .player_size import player_size
    from .prompt import CORRIDOR_PLAYERS

    from .prompt import MIN_CORRIDOR_PLAYERS

    if spec.door_origin and not spec.doors:
        return (f"no door polygon: draw `{spec.building}_door` with door_of={spec.building} "
                f"in Tiled around the painted frame (lintel, jambs, opening). It is what the "
                f"floor is held out of, what the render keeps, and what hides the player "
                f"walking in; without it there is nothing to start the room behind")
    player = player_size(scale=spec.world_scale)
    asked = (getattr(spec, "corridor_players", None) or CORRIDOR_PLAYERS)[0]
    if asked < MIN_CORRIDOR_PLAYERS:
        return (f"a corridor of {asked:.2f} people ({asked * player.width:.0f} px) is below "
                f"the {MIN_CORRIDOR_PLAYERS} minimum -- nothing that narrow is walkable")
    if spec.door_width and spec.door_width < MIN_CORRIDOR_PLAYERS * player.width:
        return (f"the doorway is {spec.door_width / player.width:.2f} people "
                f"({spec.door_width:.0f} px), below the {MIN_CORRIDOR_PLAYERS} minimum -- "
                f"widen it with [g] or the entrance cannot be walked through")
    corridor = asked * player.width
    across = min(spec.size)
    if across < corridor * 2:
        return (f"the chamber is {across} px across and a corridor is {corridor:.0f} px wide; "
                f"there is no floor plan that fits inside it")
    if spec.door_width and spec.door_width > max(spec.size) * 0.8:
        return (f"the doorway is {spec.door_width:.0f} px across a building only "
                f"{max(spec.size)} px wide; check the entrance was measured correctly")
    return ""


def scale_reference(image: Image.Image, spec, scale: float) -> Image.Image:
    """Draw a one-person ruler INTO the image the model is given.

    This is the fix for the thing the text could not do. The prompt said "a corridor is 1.5 to
    2.5 people wide" and gave the building as "19 x 15 people across", which is explicit and
    correct and still produced corridors half the width asked for -- because acting on it means
    deriving a pixel width from the frame, and the model draws what a floor plan looks like
    instead. A figure and a bar it can match against are not a sum.

    Drawn at the doorway, where the constraint matters, and repeated as a bar in the corner.
    Both sit inside the editable region so the model may paint over them; anything landing
    outside it is discarded by `paste_back` anyway, so `check_border` is unaffected either way.
    """
    from PIL import ImageDraw

    from .player_size import player_size

    measured = player_size(scale=spec.world_scale)
    if not measured.sprite:
        return image
    sprite_path = Path(__file__).resolve().parents[3] / measured.sprite
    if not sprite_path.exists():
        return image

    with Image.open(sprite_path) as source:
        sprite = source.convert("RGBA")
    box = sprite.getbbox()
    if box:
        sprite = sprite.crop(box)
    # `measured` is already in this level's painted px (world_scale applied); the plan pass
    # then runs downscaled, so the ruler shrinks with everything else in the frame.
    wide = max(4, int(round(measured.width * scale)))
    tall = max(4, int(round(measured.height * scale)))
    sprite = sprite.resize((wide, tall), Image.LANCZOS)

    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    if spec.door_origin:
        canvas.paste(sprite, (int(spec.door_origin[0] * scale - wide / 2),
                              int(spec.door_origin[1] * scale - tall / 2)), sprite)
    canvas.paste(sprite, (10, canvas.height - tall - 10), sprite)
    # The bar: exactly one person wide, beside the figure, since a rectangle is easier to
    # measure a corridor against than a silhouette with arms.
    draw.rectangle([10, canvas.height - 8, 10 + wide, canvas.height - 4],
                   fill=(255, 255, 255), outline=(0, 0, 0))
    return canvas.convert("RGBA")


def draw_plans(spec, config, work: Path, draws: int = 1, criticism: str = "",
               attach=()) -> list:
    """Paint `draws` plans, trace and check each. Returns them ranked, best first.

    `criticism` and `attach` are the retry channel, and they are the same channel
    `world_levels.job_builder._with_retry_context` opened: what was wrong goes on the end of
    the prompt, and the picture showing it rides along as a further image. `r1` in the plan
    gate fills both from the shape overlay; `r <why> @image` fills them by hand.
    """
    silhouette, chamber, editable = geometry_masks(spec)
    roof = Image.open(spec.roof_image).convert("RGBA")
    if roof.size != tuple(spec.size):
        raise BuildingInteriorError(
            f"exterior art is {roof.size[0]}x{roof.size[1]} but the footprint is "
            f"{spec.size[0]}x{spec.size[1]}; they are composited 1:1 and must agree")

    work.mkdir(parents=True, exist_ok=True)
    client = make_image_client(config)
    prompt = with_criticism(plan_prompt(spec), criticism, attach)
    (work / "plan_prompt.txt").write_text(prompt, encoding="utf-8")

    small = plan_size(spec.size)
    small_roof = roof.resize(small, Image.LANCZOS)
    small_roof = scale_reference(small_roof, spec, small[0] / float(spec.size[0]))
    small_roof.save(work / "plan_input.png")
    small_mask = np.asarray(_mask_image(editable).resize(small, Image.NEAREST)) > 0
    sent_mask = _mask_image(small_mask)
    keep = silhouette & ~editable

    plans = []
    for index in range(1, draws + 1):
        tag = f"plan_draw{index}"
        result = _run_edit(client, config, prompt, small_roof, small_mask, work, tag,
                           extra_images=list(attach))
        full = result.convert("RGBA").resize(tuple(spec.size), Image.NEAREST)
        # The registration gate still applies: a plan that drifted at the rim would emit
        # collision that does not line up with the building it is inside.
        composited = paste_back(full, roof, editable)
        check_border(composited, roof, keep)

        # Scored on the raw return against the mask that was actually sent, both at
        # generation resolution. Scoring `full` or `composited` would measure our own resize
        # and paste rather than whether the model drew where it was told.
        shape = layout_checks.shape_checks(result, sent_mask)
        plan = trace_plan(full, spec, silhouette, chamber, editable, extra_checks=shape)
        plan.painted_path = work / f"{tag}_raw.png"
        plan.composited_path = work / f"{tag}_overlay.png"
        plan.composited_path = save_image(overlay(plan, roof), plan.composited_path)
        plan.shape_path = save_image(layout_checks.shape_overlay(result, sent_mask),
                                     work / f"{tag}_shape.png")
        plans.append(plan)
        print(layout_checks.format_report(plan.report, tag))

    return sorted(plans, key=lambda p: layout_checks.score(p.report))


def ranked_sheet(plans, out_path: Path, width: int = 520) -> Path:
    """Contact sheet ordered by the checks, each draw labelled with why it ranked there."""
    from PIL import ImageDraw

    thumbs = []
    for plan in plans:
        thumb = Image.open(plan.composited_path).convert("RGB")
        thumb.thumbnail((width, width))
        thumbs.append(thumb)
    height = max(t.height for t in thumbs)
    sheet = Image.new(
        "RGB", (sum(t.width for t in thumbs) + 10 * (len(thumbs) - 1), height + 44), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    x = 0
    for rank, (plan, thumb) in enumerate(zip(plans, thumbs), start=1):
        sheet.paste(thumb, (x, 44))
        verdict = "PASS" if plan.passed else "fails: " + ", ".join(plan.failed)
        draw.text((x + 6, 6), f"#{rank}  {Path(plan.painted_path).stem}",
                  fill=(255, 220, 90))
        draw.text((x + 6, 24), verdict[:70],
                  fill=(120, 230, 140) if plan.passed else (240, 120, 110))
        x += thumb.width + 10
    return save_image(sheet, out_path)
