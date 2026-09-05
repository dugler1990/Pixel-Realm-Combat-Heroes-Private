"""Loop B: paint the stonework, with the plan as a control image.

What this replaces is the tile pass -- bands of the canvas handed back to an edit model with
a 74%-open mask and the instruction to keep the layout already there. There is no lever in
the API that enforces that, and it did not hold: the shipped asset has two unrelated floor
plans meeting at row 1536 with black voids where the bands failed to meet. Deleted rather
than tuned.

The layout is no longer something the render pass can get wrong, because it is no longer
something the render pass decides. It is shown the traced plan and asked to paint it.

Registration is unchanged and deliberately not routed through the world_levels renderers:
warp fits its return to a polygon and frame sends a crop, and either destroys the 1:1
alignment that a measured cross-correlation of 0.040 says cannot be recovered afterwards.
The exterior is the input image, everything outside the editable region is written back from
it, and `check_border` asserts byte equality rather than hoping for it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..building_interiors import (
    _mask_image,
    _run_edit,
    check_border,
    cut_alpha,
    layout_size,
    paste_back,
)
from ..image_client import make_image_client
from .plan import control_image, geometry_masks
from .prompt import assemble
from .trace import CLASS_NAMES

Image.MAX_IMAGE_PIXELS = None


def style_block(spec):
    return [
        "Repaint the masked region as finished game art, matching the building it is inside.",
        "",
        f"The image is a {spec.object_prompt or 'building'} seen from above with its roof "
        f"lifted off. Everything outside the mask is finished art: continue its stonework "
        f"inward with no jump in block size, colour, course spacing or perspective.",
    ]


def control_block(spec):
    """What the second image is and how literally to take it."""
    return [
        "IMAGE 2 IS THE FLOOR PLAN. FOLLOW IT EXACTLY.",
        f"  {CLASS_NAMES['floor'].upper()} areas are FLOOR: flat walkable ground, paved or "
        f"sand-drifted. Nothing standing on it that a person could not walk past.",
        f"  {CLASS_NAMES['solid'].upper()} bands are WALLS: stone courses seen from above, "
        f"with a visible top face and a clear edge either side.",
        "  DARK GREY is the solid mass of the building: plain unbroken courses of massive",
        "  blocks. Most of the picture is this, and that is correct.",
        "",
        "Do not move a wall, do not open a new gap, do not close one that is drawn, do not",
        "add a room. Where the plan says floor there is floor, to the pixel.",
    ]


def lighting_block(spec):
    return [
        "LIGHTING AND FINISH",
        "  Even lighting throughout. No torch glow, light pools, directional light, vignette",
        "  or cast shadows -- the engine lights this and will light it twice otherwise.",
        "  Interior stone slightly cooler and darker than the sunlit exterior, never black.",
        "  No text, labels, grid lines, watermarks, UI, characters, creatures or loot.",
    ]


def render_prompt(spec) -> str:
    return assemble(style_block(spec), control_block(spec), lighting_block(spec))


def render_interior(plan, config, work: Path, draws: int = 1) -> list:
    """Paint the stonework over the plan. Returns composited candidates, gated.

    Each draw is registered and border-checked before it is kept, so a draw that drifted at
    the rim fails on the pass that produced it rather than becoming a renderer workaround
    three modules downstream.
    """
    spec = plan.spec
    silhouette, _chamber, editable = geometry_masks(spec)
    keep = silhouette & ~editable
    roof = Image.open(spec.roof_image).convert("RGBA")

    work.mkdir(parents=True, exist_ok=True)
    control_path = work / "control.png"
    control_image(plan).save(control_path)

    prompt = render_prompt(spec)
    (work / "render_prompt.txt").write_text(prompt, encoding="utf-8")
    client = make_image_client(config)

    # A 3600x3140 building is 11.3 MP against an 8.3 MP cap, so the call runs at the largest
    # legal uniform downscale and the return is scaled back up -- about 17% here. That is
    # what the tile pass existed to avoid, and it cost two unrelated floor plans stapled
    # together to avoid it. A soft 17% is the cheaper mistake, and `paste_back` writes the
    # exterior back at full resolution regardless, so only the chamber ever carries it.
    generate_size = layout_size(spec.size)
    small_roof = roof.resize(generate_size, Image.LANCZOS)
    small_mask = np.asarray(_mask_image(editable).resize(generate_size, Image.NEAREST)) > 0

    out = []
    for index in range(1, draws + 1):
        tag = "render" if draws == 1 else f"render_draw{index}"
        # The exterior is the input image and the plan rides along as context. Never a
        # previous interior: the roof is the immutable substrate, and feeding a render back
        # in would let the chamber's own history leak into the next one.
        result = _run_edit(client, config, prompt, small_roof, small_mask, work, tag,
                           extra_images=[control_path])
        candidate = paste_back(result, roof, editable)
        check_border(candidate, roof, keep)
        path = work / f"{tag}_composited.png"
        candidate.save(path)
        out.append(path)
        print(f"  {tag}: border check passed -> {path}")
    return out


def accept(plan, composited: Path) -> Path:
    """Cut the silhouette and write the interior asset the engine loads."""
    spec = plan.spec
    silhouette, _chamber, _editable = geometry_masks(spec)
    interior = cut_alpha(Image.open(composited).convert("RGBA"), silhouette)
    interior.save(spec.interior_image)
    return Path(spec.interior_image)
