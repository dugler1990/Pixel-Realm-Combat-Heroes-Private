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
The exterior is the input image, everything outside the paintable region is written back from
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
from . import checks as layout_checks
from .plan import control_image, door_mask, geometry_masks
from .prompt import CORRIDOR_PLAYERS, assemble, with_criticism
from .trace import CLASS_NAMES, save_image

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
    """What the second image is and how literally to take it.

    Every colour in the control image is named here, including the two that are not painted
    by the model. They were left out, and what the prompt said instead -- "DARK GREY is the
    solid mass ... most of the picture is this" -- described 0.22% of an image that was 45.5%
    black and 27.5% blue. Naming all four is the difference between a plan the model can
    follow and a description it has to reconcile.
    """
    # The thin floor strips came back as lines of wall on render after render: a narrow
    # stroke of colour reads as a wall on a plan, so the prompt says what it is.
    corridor = getattr(spec, "corridor_players", None) or CORRIDOR_PLAYERS
    return [
        "IMAGE 2 IS THE FLOOR PLAN. FOLLOW IT EXACTLY. It is the same size as image 1 and",
        "lines up with it pixel for pixel: whatever a colour covers there is what you paint here.",
        f"  {CLASS_NAMES['floor'].upper()} areas are FLOOR: flat walkable ground, paved or "
        f"sand-drifted. Nothing standing on it that a person could not walk past.",
        f"  THIN {CLASS_NAMES['floor'].upper()} STRIPS ARE CORRIDORS, NOT WALLS: open floor "
        f"{corridor[0]:g} to {corridor[1]:g} people wide that a person walks along, so paint "
        f"them as floor between stone, never as a wall, a ridge or a line of blocks.",
        f"  {CLASS_NAMES['solid'].upper()} bands are WALLS BETWEEN ROOMS: stone courses seen "
        f"from above, with a visible top face and a clear edge either side.",
        f"  {CLASS_NAMES['outer'].upper()} is the building's SOLID MASS, seen from above: its "
        f"outer wall, and any unexcavated stone inside it. Plain unbroken courses of massive "
        f"blocks, lying flat like the rest of the plan. Do not stand it up, do not draw it in "
        f"perspective, do not give it a far side. Most of what you paint is this.",
        f"  {CLASS_NAMES['outside'].upper()} is OUTSIDE THE BUILDING and is not yours. It is "
        f"already finished art in image 1. Do not paint there and do not extend anything into "
        f"it.",
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


def restore_doorway(candidate, roof, spec):
    """The composite with the exterior written back over the painted door.

    The model paints the whole silhouette, its own dark opening included. In play that
    region is never the model's: the door polygon is kept out of the chamber (no hole
    there) and its exterior pixels are drawn over the player as a canopy. The composite is
    what the gate looks at, so it shows the same thing the game will -- the map's door.
    """
    region = door_mask(spec)
    if not region.any():
        return candidate
    out = np.asarray(candidate).copy()
    out[region] = np.asarray(roof)[region]
    return Image.fromarray(out, mode="RGBA")


def paint_region(spec):
    """(silhouette, paintable, keep): what the model may paint, and what must not change.

    The paintable region is the SILHOUETTE, not the chamber. The prompt has always told the
    model that blue -- the building's own mass out to its outline -- is "most of what you
    paint", while the mask handed it only the chamber; it painted the walls it was asked
    for, out to the outline, and `paste_back` cut a third of them off at the chamber edge.
    That was the mangled seam. The mask now says what the prompt says.

    Not the plan's `editable` (chamber minus door): that is where FLOOR may be. This is
    where PAINT may be, and it is a different, larger region -- the two share a shape only
    by accident and must not share a name.
    """
    silhouette, _chamber, _editable = geometry_masks(spec)
    return silhouette, silhouette.copy(), ~silhouette


def fill_unpainted(candidate, fallback, region, black_at: int = 12):
    """Where the model left `region` black, show `fallback` instead of a hole."""
    cand = np.asarray(candidate).copy()
    unpainted = region & (cand[..., :3].sum(axis=2) <= 3 * black_at)
    cand[unpainted] = np.asarray(fallback)[unpainted]
    return Image.fromarray(cand, mode="RGBA")


def render_interior(plan, config, work: Path, draws: int = 1, criticism: str = "",
                    attach=()) -> list:
    """Paint the stonework over the plan. Returns composited candidates, gated.

    Each draw is registered and border-checked before it is kept, so a draw that drifted at
    the rim fails on the pass that produced it rather than becoming a renderer workaround
    three modules downstream.

    Also shape-checked, which it was not. `check_border` only ever looked at the rim OUTSIDE
    the chamber, where the roof is written back verbatim and nothing can differ -- so it
    passed on every draw while the model was leaving thousands of pixels of the chamber black
    and `paste_back` was writing them in. The shape numbers are printed per draw and the
    error is written beside it as `<tag>_shape.png`.
    """
    spec = plan.spec
    silhouette, paintable, keep = paint_region(spec)
    roof = Image.open(spec.roof_image).convert("RGBA")

    work.mkdir(parents=True, exist_ok=True)
    # Through `save_image`, not `.save`, for the reason its docstring gives: these are all
    # opened in a viewer the moment they appear, and on Windows a viewer holding the previous
    # copy makes the same filename unwritable. That crashed a run between the paid API call
    # and the composite being written -- the draw was bought and then thrown away.
    control_path = save_image(control_image(plan), work / "control.png")

    # Image 1 is the exterior and image 2 is the control plan, so an attachment is image 3.
    prompt = with_criticism(render_prompt(spec), criticism, attach, first_index=3)
    (work / "render_prompt.txt").write_text(prompt, encoding="utf-8")
    client = make_image_client(config)

    # A 3600x3140 building is 11.3 MP against an 8.3 MP cap, so the call runs at the largest
    # legal uniform downscale and the return is scaled back up -- about 17% here. That is
    # what the tile pass existed to avoid, and it cost two unrelated floor plans stapled
    # together to avoid it. A soft 17% is the cheaper mistake, and `paste_back` writes the
    # exterior back at full resolution regardless, so only the chamber ever carries it.
    generate_size = layout_size(spec.size)
    small_roof = roof.resize(generate_size, Image.LANCZOS)
    small_mask = np.asarray(_mask_image(paintable).resize(generate_size, Image.NEAREST)) > 0
    sent_mask = _mask_image(small_mask)

    out = []
    for index in range(1, draws + 1):
        tag = "render" if draws == 1 else f"render_draw{index}"
        # The exterior is the input image and the plan rides along as context. Never a
        # previous interior: the roof is the immutable substrate, and feeding a render back
        # in would let the chamber's own history leak into the next one.
        result = _run_edit(client, config, prompt, small_roof, small_mask, work, tag,
                           extra_images=[control_path] + list(attach))
        # Before the paste, on the raw return, against the mask that was sent. Afterwards
        # there is nothing left to measure: the composite is our own paste and always fits.
        shape, filled = layout_checks.shape_checks(
            result, sent_mask, missing_threshold=layout_checks.RENDER_MISSING_THRESHOLD)
        shape_path = save_image(
            layout_checks.shape_overlay(
                result, sent_mask, missing_threshold=layout_checks.RENDER_MISSING_THRESHOLD),
            work / f"{tag}_shape.png")

        candidate = paste_back(result, roof, paintable)
        candidate = restore_doorway(fill_unpainted(candidate, roof, paintable), roof, spec)
        check_border(candidate, roof, keep)
        path = save_image(candidate, work / f"{tag}_composited.png")
        out.append(path)
        print(layout_checks.format_report({"checks": [shape, filled]}, tag))
        print(f"  {tag}: border check passed -> {path}")
        print(f"  {tag}: shape error marked -> {shape_path}")
    return out


# Room px round the scale figure put back from the bare room after a draw: the resize to
# the generation size and back blurs his edge into the pixels next to him.
FIGURE_PAD = 4


def scale_figure(plan) -> tuple:
    """(sprite, box): the character a decoration is sized to, and where he stands in the room.

    `spec.scale_character` (default the barbarian, `player_size.CHARACTER`), facing down, at
    his size in the game on this canvas. `spec.scale_at` is where his feet go, in canvas px;
    unset, he stands on the floor as far from any wall as it gets, in the open where the
    model sees him whole.
    """
    import cv2

    from .player_size import CHARACTER, REPO

    spec = plan.spec
    character = spec.scale_character or CHARACTER
    frames = sorted((REPO / "Graphics" / character).glob("down/*.png"))
    if not frames:
        raise ValueError(f"no walk frames for scale_character {character!r} under "
                         f"{REPO / 'Graphics' / character / 'down'}")
    with Image.open(frames[0]) as source:
        sprite = source.convert("RGBA")
    if sprite.getbbox():
        sprite = sprite.crop(sprite.getbbox())
    scale = spec.world_scale or 1.0
    if abs(scale - 1.0) > 1e-9:
        sprite = sprite.resize((max(1, round(sprite.width / scale)),
                                max(1, round(sprite.height / scale))), Image.NEAREST)
    if spec.scale_at:
        x, y = int(spec.scale_at[0]), int(spec.scale_at[1])
    else:
        floor = (plan.classes["floor"] & ~door_mask(spec)).astype(np.uint8)
        distance = cv2.distanceTransform(floor, cv2.DIST_L2, 5)
        y, x = (int(v) for v in np.unravel_index(int(np.argmax(distance)), distance.shape))
    left, top = x - sprite.width // 2, y - sprite.height
    return sprite, (left, top, left + sprite.width, top + sprite.height)


# Px round the floor a decoration may still touch: the anti-aliased edge of what stands on it.
DECOR_EDGE = 8
# How tall the tallest thing added is, in scale figures: the prompt's "a statue is one to two
# of him tall".
DECOR_FIGURES_TALL = 2


def decor_region(plan) -> np.ndarray:
    """Where decorating may change the room: the floor, and the space a statue on it fills.

    Everything added stands on the floor, and seen from above at three-quarters it rises UP
    the picture from where it stands -- over the wall behind it, never out sideways. So the
    floor, plus up to two figures' height above any floor pixel, plus a thin edge. The rest
    of the outline -- blue, the solid mass round the rooms -- is not somewhere anything is
    added, and on a plan of small rooms in a big building it is most of the outline.
    """
    import cv2

    floor = plan.classes["floor"].astype(np.uint8)
    sprite, _box = scale_figure(plan)
    rise = DECOR_FIGURES_TALL * sprite.height
    # Anchored at the top: a pixel is in when floor lies within `rise` px BELOW it.
    up = cv2.dilate(floor, np.ones((rise + 1, 1), np.uint8), anchor=(0, 0))
    edge = cv2.dilate(floor, np.ones((2 * DECOR_EDGE + 1, 2 * DECOR_EDGE + 1), np.uint8))
    return (up | edge) > 0


def augment_block(spec, additions: str, decorate: bool = False):
    """What an augment pass may and may not do. The whole instruction is 'keep it'."""
    if decorate:
        where = [
            "IMAGE 2 IS THE FLOOR PLAN, pixel-aligned with image 1. Everything you add stands",
            f"  on {CLASS_NAMES['floor'].upper()} (the floor), or against a wall right at the "
            f"floor's edge. {CLASS_NAMES['outer'].upper()} and {CLASS_NAMES['solid'].upper()} "
            "are solid",
            "  stone outside the rooms: nothing goes on them. Never block a corridor or a",
            "  doorway; leave a clear walking path everywhere there was one.",
        ]
    else:
        where = [
            "IMAGE 2 IS THE FLOOR PLAN, pixel-aligned with image 1. Anything you add must stand on",
            f"  {CLASS_NAMES['floor'].upper()} (floor) or on the face of a "
            f"{CLASS_NAMES['solid'].upper()} / {CLASS_NAMES['outer'].upper()} wall band.",
            "  Never block a corridor or a doorway; leave a clear walking path everywhere there",
            "  was one. Nothing goes on BLACK -- that is outside the building and is not yours.",
        ]
    return [
        "IMAGE 1 IS A FINISHED INTERIOR. KEEP IT. Every wall, floor tile, block, colour, edge",
        "and shadow in the masked region is already correct and stays exactly where it is.",
        "",
        "ADD ONLY THE FOLLOWING, drawn on top of what is already there:",
        f"  {additions.strip()}",
        "",
        "Nothing else changes. Do not repaint, restyle, recolour, move, remove or tidy anything",
        "that is not part of what was asked for. If you are unsure whether a pixel should",
        "change, it should not. The result must be image 1 plus the additions and nothing more.",
        "",
    ] + where + ([
        "",
        "SCALE: the figure standing in the room in image 1 is a person. Leave him as he is,",
        "draw nothing over him, and size everything you add to him: a statue is one to two",
        "of him tall, a table or brazier reaches his waist, an urn his knee.",
    ] if decorate else [])


def augment_prompt(spec, additions: str, decorate: bool = False) -> str:
    return assemble(augment_block(spec, additions, decorate), lighting_block(spec))


# Per-pixel RGB distance (summed over channels) above which an augment is said to have
# changed a pixel. 30 rides over resampling and PNG noise; a retextured floor is hundreds.
DRIFT_THRESHOLD = 30

DRIFT_NOTE = (
    "IMAGE {n} IS THE ROOM YOU WERE GIVEN, with every pixel you changed marked in RED. "
    "Only the additions were allowed to change. Everything else that is red is a mistake: "
    "you repainted floor, walls or stone that were already finished."
)
DRIFT_DIRECTIVE = (
    "Reproduce image 1 exactly everywhere that is not one of the additions -- the same "
    "tiles, the same courses, the same colours, pixel for pixel -- and draw the additions on "
    "top of it. {fraction:.0%} of the room changed last time; only the additions should. "
    "This takes precedence over any earlier instruction it contradicts."
)


def drift_mask(candidate, base, paintable, threshold: int = DRIFT_THRESHOLD) -> np.ndarray:
    """Where an augment differs from its base, inside the paintable region."""
    a = np.asarray(candidate.convert("RGB")).astype(int)
    b = np.asarray(base.convert("RGB")).astype(int)
    return (np.abs(a - b).sum(axis=2) > threshold) & paintable


def drift_overlay(base, changed) -> Image.Image:
    """The base with the changed pixels tinted red. Same idea as the shape overlay: the
    model is shown its own miss on the picture it should have reproduced, not told about it."""
    out = np.asarray(base.convert("RGB")).astype(float)
    tint = np.zeros_like(out)
    tint[..., 0] = 255
    out[changed] = out[changed] * 0.35 + tint[changed] * 0.65
    return Image.fromarray(out.astype(np.uint8), mode="RGB")


def drift_texts(fraction: float, image_index: int) -> tuple:
    return DRIFT_NOTE.format(n=image_index), DRIFT_DIRECTIVE.format(fraction=fraction)


def augment_interior(plan, config, work: Path, base: Path, additions: str,
                     draws: int = 1, criticism: str = "", attach=(), decorate: bool = False) -> list:
    """Add to a render you already like, keeping the rest of it. Returns composited candidates.

    The additive retry: `render_interior` always paints from the exterior, on purpose, so a
    draw can never inherit the last one's mistakes -- but that also means "the same room with
    statues in it" was impossible, because every draw was a new room. This starts from `base`
    instead, with the same mask and the same registration, so what comes back is that room
    with things added to it and the exterior byte-identical (`check_border` still asserts it).

    What it cannot promise is that the model touched *only* the additions; an edit model
    repaints the masked region and is asked to reproduce it. Each draw prints how much of the
    room changed so a drift is seen at the gate rather than discovered in the game.

    `criticism` / `attach` are the `r1` channel, same as the render pass: the shape-error
    overlay of the last augment rides along as image 3 so the model is shown where it missed
    the mask. Where it leaves the mask unpainted, the base shows through rather than black --
    for an addition, "nothing here" means "what was here", never a hole.

    `decorate` (step 1 of furnishing): the scale character (`scale_figure`) stands in the room
    that is sent, so what is added is sized to a person, and his box is put back from the base
    afterwards -- he is in the call, never in the result. And the mask sent is `decor_region`,
    the floor and the wall at its edge; whatever comes back outside it is the base again.
    """
    spec = plan.spec
    silhouette, paintable, keep = paint_region(spec)
    region = decor_region(plan) & paintable if decorate else paintable
    roof = Image.open(spec.roof_image).convert("RGBA")
    base_image = Image.open(base).convert("RGBA")
    if base_image.size != roof.size:
        raise ValueError(f"{base} is {base_image.size}, the building is {roof.size}")

    work.mkdir(parents=True, exist_ok=True)
    control_path = save_image(control_image(plan), work / "control.png")
    # Image 1 is the base, image 2 the plan, so an attachment is image 3.
    prompt = with_criticism(augment_prompt(spec, additions, decorate), criticism, attach,
                            first_index=3)
    (work / "augment_prompt.txt").write_text(prompt, encoding="utf-8")
    client = make_image_client(config)

    # Same downscale as the render pass, so the two are drawn on identically distorted canvases.
    generate_size = layout_size(spec.size)
    sent = base_image
    if decorate:
        sprite, box = scale_figure(plan)
        sent = base_image.copy()
        sent.paste(sprite, box[:2], sprite)
        box = (max(0, box[0] - FIGURE_PAD), max(0, box[1] - FIGURE_PAD),
               min(sent.width, box[2] + FIGURE_PAD), min(sent.height, box[3] + FIGURE_PAD))
    small_base = sent.resize(generate_size, Image.LANCZOS)
    sent_mask = _mask_image(
        np.asarray(_mask_image(paintable).resize(generate_size, Image.NEAREST)) > 0)
    small_mask = np.asarray(_mask_image(region).resize(generate_size, Image.NEAREST)) > 0

    out = []
    for index in range(1, draws + 1):
        tag = "augment" if draws == 1 else f"augment_draw{index}"
        # Image 1 is the room as it is, image 2 the plan. Never the exterior: the exterior
        # is what `paste_back` restores around it, and it must not be what gets repainted.
        result = _run_edit(client, config, prompt, small_base, small_mask, work, tag,
                           extra_images=[control_path] + list(attach))
        shape, filled = layout_checks.shape_checks(
            result, sent_mask, missing_threshold=layout_checks.RENDER_MISSING_THRESHOLD)
        save_image(layout_checks.shape_overlay(
            result, sent_mask, missing_threshold=layout_checks.RENDER_MISSING_THRESHOLD),
            work / f"{tag}_shape.png")

        candidate = paste_back(result, roof, paintable)
        if decorate:
            pixels = np.asarray(candidate.convert("RGBA")).copy()
            outside = paintable & ~region
            pixels[outside] = np.asarray(base_image)[outside]
            candidate = Image.fromarray(pixels, mode="RGBA")
        # Unpainted (black) inside the mask is "no change", so the base fills it. The shape
        # check above still scored the raw return, so the miss is reported, not hidden.
        candidate = restore_doorway(fill_unpainted(candidate, base_image, region), roof, spec)
        if decorate:
            candidate.paste(base_image.crop(box), box[:2])
        check_border(candidate, roof, keep)
        path = save_image(candidate, work / f"{tag}_composited.png")
        out.append(path)
        # What this was made from, so a retry in a later session re-augments the same base
        # with the same request rather than falling back to a fresh render from the roof.
        import json

        (work / f"{tag}_meta.json").write_text(
            json.dumps({"base": str(base), "additions": additions}, indent=2), encoding="utf-8")

        # How much of the room the model touched. The additions should be a small fraction;
        # a large one means it re-imagined the room around them. Written out as an overlay
        # beside the shape error, so `r2` at the gate can show it back.
        changed = drift_mask(candidate, base_image, paintable)
        fraction = changed.sum() / max(1, paintable.sum())
        save_image(drift_overlay(base_image, changed), work / f"{tag}_drift.png")
        (work / f"{tag}_drift.txt").write_text(f"{fraction:.4f}\n", encoding="utf-8")
        print(layout_checks.format_report({"checks": [shape, filled]}, tag))
        print(f"  {tag}: {fraction:.0%} of the room changed from the base"
              + ("  -- most of it was repainted, not added to" if fraction > 0.5 else ""))
        print(f"  {tag}: border check passed -> {path}")
    return out


def accept(plan, composited: Path) -> Path:
    """Cut the silhouette and write the interior asset the engine loads."""
    spec = plan.spec
    silhouette, _chamber, _editable = geometry_masks(spec)
    interior = cut_alpha(Image.open(composited).convert("RGBA"), silhouette)
    interior.save(spec.interior_image)
    return Path(spec.interior_image)
