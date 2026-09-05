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
    BuildingInteriorError,
    _mask_image,
    _run_edit,
    build_masks,
    check_border,
    paste_back,
)
from ..image_client import make_image_client
from ..world_levels.masks import rasterize_polygon
from . import checks as layout_checks
from .prompt import plan_prompt
from .trace import (
    CLASS_COLOURS,
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
# Thickness of the wall band derived around the traced floor, and the segment length the
# emitter tiles it with. One number, so the control image's walls and the collision quads
# are the same band by construction.
WALL_THICKNESS = 160


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
    """Downscale for the plan pass: long edge PLAN_EDGE, both edges divisible by 16."""
    scale = min(1.0, PLAN_EDGE / float(max(size)))
    fit = lambda v: max(EDGE_MULTIPLE, int(v * scale) // EDGE_MULTIPLE * EDGE_MULTIPLE)  # noqa: E731
    return fit(size[0]), fit(size[1])


def geometry_masks(spec):
    """(silhouette, chamber, editable) at canvas resolution.

    The editable region is the authored chamber minus the door polygons. Holding the whole
    door out keeps it byte-identical in both views: a mask cutting through a straddling arch
    asks the model to reinvent half of it, and it never does.
    """
    silhouette = np.asarray(rasterize_polygon(spec.size, spec.silhouette)) > 0
    chamber = np.asarray(rasterize_polygon(spec.size, spec.chamber)) > 0
    editable = chamber.copy()
    for door in spec.doors:
        editable = editable & ~(np.asarray(rasterize_polygon(spec.size, door)) > 0)
    return silhouette, chamber, editable


def trace_plan(painted, spec, silhouette, chamber, editable) -> Plan:
    """Classify a plan painting and run every check on it. No API, no spend."""
    partition = partition_with_reject(np.asarray(painted.convert("RGB")), editable)
    floor = partition.masks["floor"]
    geometry = layout_checks.PlanGeometry(
        floor=floor,
        chamber=chamber,
        silhouette=silhouette,
        editable=editable,
        door_origin=spec.door_origin or (0, 0),
        door_inward=spec.door_inward or (0, 1),
        unpainted_fraction=partition.unpainted_fraction,
        tile=spec.tile,
        expected_rooms=spec.rooms,
    )
    return Plan(
        spec=spec,
        floor=floor,
        chamber=chamber,
        silhouette=silhouette,
        classes=derive_art_classes(floor, chamber, WALL_THICKNESS),
        report=layout_checks.run_checks(geometry),
    )


def control_image(plan) -> Image.Image:
    """The three-colour picture the render pass is told to paint.

    Wall is not painted by the model and not guessed at here: it is the floor dilated by the
    emitter's own thickness, so the band the render pass is shown is exactly the band the
    collision quads occupy.
    """
    canvas = np.zeros((plan.spec.size[1], plan.spec.size[0], 3), dtype=np.uint8)
    canvas[plan.classes["solid"]] = (90, 84, 78)
    canvas[plan.classes["wall"]] = CLASS_COLOURS["solid"]
    canvas[plan.classes["floor"]] = CLASS_COLOURS["floor"]
    return Image.fromarray(canvas, mode="RGB")


def overlay(plan, roof) -> Image.Image:
    """The plan laid over the exterior, for looking at. Floor tinted, walls outlined."""
    base = np.asarray(roof.convert("RGB")).astype(np.float32)
    tint = np.zeros_like(base)
    tint[plan.classes["floor"]] = CLASS_COLOURS["floor"]
    tint[plan.classes["wall"]] = CLASS_COLOURS["solid"]
    mask = (plan.classes["floor"] | plan.classes["wall"])[..., None]
    blended = np.where(mask, base * 0.45 + tint * 0.55, base)
    return Image.fromarray(blended.astype(np.uint8), mode="RGB")


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


def trace_plan_from_mask(floor, spec, silhouette, chamber, editable=None, unpainted=0.0) -> Plan:
    """Check a floor mask that did not come from a painting."""
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
    )
    return Plan(
        spec=spec,
        floor=floor,
        chamber=chamber,
        silhouette=silhouette,
        classes=derive_art_classes(floor, chamber, WALL_THICKNESS),
        report=layout_checks.run_checks(geometry),
    )


def draw_plans(spec, config, work: Path, draws: int = 1) -> list:
    """Paint `draws` plans, trace and check each. Returns them ranked, best first."""
    silhouette, chamber, editable = geometry_masks(spec)
    roof = Image.open(spec.roof_image).convert("RGBA")
    if roof.size != tuple(spec.size):
        raise BuildingInteriorError(
            f"exterior art is {roof.size[0]}x{roof.size[1]} but the footprint is "
            f"{spec.size[0]}x{spec.size[1]}; they are composited 1:1 and must agree")

    work.mkdir(parents=True, exist_ok=True)
    client = make_image_client(config)
    prompt = plan_prompt(spec)
    (work / "plan_prompt.txt").write_text(prompt, encoding="utf-8")

    small = plan_size(spec.size)
    small_roof = roof.resize(small, Image.LANCZOS)
    small_mask = np.asarray(_mask_image(editable).resize(small, Image.NEAREST)) > 0
    keep = silhouette & ~editable

    plans = []
    for index in range(1, draws + 1):
        tag = f"plan_draw{index}"
        result = _run_edit(client, config, prompt, small_roof, small_mask, work, tag)
        full = result.convert("RGBA").resize(tuple(spec.size), Image.NEAREST)
        # The registration gate still applies: a plan that drifted at the rim would emit
        # collision that does not line up with the building it is inside.
        composited = paste_back(full, roof, editable)
        check_border(composited, roof, keep)

        plan = trace_plan(full, spec, silhouette, chamber, editable)
        plan.painted_path = work / f"{tag}_raw.png"
        plan.composited_path = work / f"{tag}_overlay.png"
        overlay(plan, roof).save(plan.composited_path)
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
    sheet.save(out_path)
    return out_path
