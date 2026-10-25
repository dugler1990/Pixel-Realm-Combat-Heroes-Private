"""The floor pass: trace the room the model actually painted, at accept.

The plan pass asks for a room and the render pass paints one, and the two never agree to
the pixel -- the model insets its floor, thickens its walls, moves an edge. Every number
the engine needs (where you can walk, where the roof lifts, where "inside" begins) has to
come from the painting, not from the request, or the room you see and the room you are
in are two rooms.

So the accepted render is traced. The tracer is one function, `trace_floor`, and it takes
a PAINTING: three flat colours over the render saying what each pixel is. Where that
painting comes from is a separate question with two answers -- `draw_floor` asks the model
for it (one edit call), or a person paints it by hand and passes the file at the gate --
and a third producer can be dropped in without the tracer, the gate or the emitter
noticing. The paid call is a painting to look at, not a truth: the gate shows the trace
over the render it traced, and refuses to write a floor that does not reach the door.

Three colours, not the plan pass's two, because the render repaints the building's
outside face and that face must never show in play (the map's own face does). The model
already knows all three from the render prompt: magenta floor, green walls, blue "the
building's solid mass".
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..building_interiors import _mask_image, _run_edit
from ..image_client import make_image_client
from . import checks as layout_checks
from .plan import Plan, control_image, geometry_masks, overlay, plan_size, trace_plan_from_mask
from .prompt import assemble, rules_block
from .trace import CLASS_NAMES, FLOOR_RGB, OUTER_RGB, SOLID_RGB, partition_with_reject, save_image

Image.MAX_IMAGE_PIXELS = None

# What each colour means in a floor painting. `outer` is the building's outside face --
# the class that must never end up in the roof hole.
FLOOR_PALETTE = {"floor": FLOOR_RGB, "wall": SOLID_RGB, "outer": OUTER_RGB}


def floor_block(spec):
    return [
        "Repaint the masked region of image 1 -- a finished interior seen from above, its",
        "roof lifted off -- as a THREE-COLOUR TRACE of what is painted there.",
        f"  {CLASS_NAMES['floor'].upper()} exactly where the picture shows walkable floor: "
        f"paving, sand, the passage in from the doorway.",
        f"  {CLASS_NAMES['solid'].upper()} over the room's walls and anything standing in the "
        f"room -- stone that belongs to the inside.",
        f"  {CLASS_NAMES['outer'].upper()} over the building's outside face -- the "
        f"{spec.object_prompt or 'building'} itself, seen from outside. Not part of the room.",
        "",
        "THE HARD PARTS -- WHERE A TRACE USUALLY GOES WRONG",
        f"  A narrow strip of floor between two walls is a CORRIDOR. Paint it "
        f"{CLASS_NAMES['floor'].upper()} the whole way along, unbroken, however thin. Never "
        f"close a corridor with {CLASS_NAMES['solid'].upper()}.",
        "  The corridor that leads in from the doorway is floor all the way to the doorway "
        "itself.",
        f"  Walls are seen slightly from the side. Their top and their visible face are "
        f"{CLASS_NAMES['solid'].upper()}; the floor is {CLASS_NAMES['floor'].upper()} right up "
        f"to the line where the wall meets the ground.",
        f"  IMAGE 2 is the floor plan this room was painted from: its "
        f"{CLASS_NAMES['floor'].upper()} is where the floor was meant to be. Where the picture "
        f"is hard to read -- a thin corridor, floor half-hidden by a wall -- use it to decide. "
        f"Where the picture clearly shows something else, trace the picture.",
        "",
        "Do not design anything. Trace what is there: follow the picture's edges to the pixel.",
        "Flat colour, hard edges, no texture, no shading. Every pixel in the mask is one of",
        "the three colours.",
    ]


def floor_prompt(spec) -> str:
    return assemble(floor_block(spec), rules_block(spec))


def trace_floor(painting: Image.Image, spec) -> Plan:
    """A checked Plan from a three-colour painting over the render. No API, no spend.

    Walkable floor is kept only inside the requested chamber minus the door -- the region
    the floor was ever allowed in -- so a stroke of magenta over the door frame or out on
    the shell does not become somewhere you can walk. Walls are kept anywhere in the
    silhouette: they are the room picture, and the emitter puts them in the roof hole
    with the floor. Everything else in the silhouette is the outside face.
    """
    if painting.size != tuple(spec.size):
        painting = painting.resize(tuple(spec.size), Image.NEAREST)
    silhouette, chamber, editable = geometry_masks(spec)
    partition = partition_with_reject(np.asarray(painting.convert("RGB")), silhouette,
                                      palette=FLOOR_PALETTE)
    floor = partition.masks["floor"] & editable
    wall = partition.masks["wall"] & silhouette & ~floor
    classes = {
        "floor": floor,
        "wall": wall,
        "outer": silhouette & ~floor & ~wall,
        "solid": np.zeros_like(floor),
    }
    return trace_plan_from_mask(floor, spec, silhouette, chamber, editable,
                                unpainted=partition.unpainted_fraction, classes=classes)


def draw_floor(plan, config, work: Path, source: Path, force: bool = False) -> Image.Image:
    """The model's floor painting of `source`, at canvas size. One edit call, or none.

    Reused from disk when `floor_raw.png` was drawn from this same source (the sidecar
    says which) and `force` is not set: the trace is free, the draw is what costs, and
    accept is run more than once per building.
    """
    spec = plan.spec
    work.mkdir(parents=True, exist_ok=True)
    raw_path, meta_path = work / "floor_raw.png", work / "floor_meta.json"
    if raw_path.exists() and meta_path.exists() and not force:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        if Path(str(meta.get("source", ""))).resolve() == Path(source).resolve():
            print(f"  floor: reusing {raw_path.name} (traced from {Path(source).name}) -- [r] to redraw")
            return Image.open(raw_path).convert("RGB").resize(tuple(spec.size), Image.NEAREST)

    silhouette, _chamber, _editable = geometry_masks(spec)
    render = Image.open(source).convert("RGBA")
    if render.size != tuple(spec.size):
        raise ValueError(f"{source} is {render.size}, the building is {tuple(spec.size)}")
    prompt = floor_prompt(spec)
    (work / "floor_prompt.txt").write_text(prompt, encoding="utf-8")

    # The plan pass's size, for the plan pass's reason: the trace needs edges to a tile,
    # not to a block, and the 8.3 MP cap buys nothing here.
    small = plan_size(spec.size)
    small_render = render.resize(small, Image.LANCZOS)
    small_mask = np.asarray(_mask_image(silhouette).resize(small, Image.NEAREST)) > 0
    # The plan the render was painted from rides along as image 2, so a corridor that is
    # thin or half-hidden at this angle is read the way it was meant, not missed.
    plan_path = save_image(control_image(plan), work / "floor_plan.png")
    result = _run_edit(make_image_client(config), config, prompt, small_render, small_mask,
                       work, "floor", extra_images=[plan_path])
    shape = layout_checks.shape_checks(result, _mask_image(small_mask))
    print(layout_checks.format_report({"checks": list(shape)}, "floor"))
    meta_path.write_text(json.dumps({"source": str(source)}, indent=2), encoding="utf-8")
    return result.convert("RGB").resize(tuple(spec.size), Image.NEAREST)


def floor_overlay(plan, source: Path, out_path: Path) -> Path:
    """The trace tinted over the render it traced -- floor, walls, outside face -- so the
    judgement at the gate is "does this match the picture", not "does this look like a
    plan". Everything blue will be the map in play; everything else, the painting."""
    return save_image(overlay(plan, Image.open(source).convert("RGBA")), out_path)
