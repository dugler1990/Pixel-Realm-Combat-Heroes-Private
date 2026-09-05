"""The plan pass prompt, as named blocks.

Following ``world_levels.renderers.prompt``: a prompt is a list of paragraphs, and whether
one applies is a line to read rather than three branches deep.

The prompt this replaces was ninety lines of metric instruction -- "at least 600 px", "250 px
wide", "If you are about to draw a second entrance, do not" -- aimed at a renderer that
cannot measure pixels. None of that survives here, for two reasons. The model is no longer
drawing stone, so there is nothing to describe; and every constraint those lines were trying
to buy is now a check on the trace, which either passes or does not and can say so.

What is left is: two flat colours, what each one means, and the scale, computed from the
building rather than typed.
"""

from __future__ import annotations

from .trace import CLASS_NAMES, FLOOR_RGB, SOLID_RGB

Block = list  # a list of lines, or None when it does not apply


def assemble(*blocks) -> str:
    lines = []
    for block in blocks:
        if block:
            lines.extend(block)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _rgb(colour) -> str:
    return "RGB(%d, %d, %d)" % colour


def task_block(spec) -> Block:
    return [
        "Repaint the masked region of this image as a FLAT COLOUR FLOOR PLAN.",
        "",
        "This is not a picture. It is a diagram: two solid colours, hard edges between them,",
        "no texture, no shading, no gradients, no outlines, no lighting. Think of a map key.",
        "Everything outside the mask is finished art and must be left exactly as it is.",
    ]


def classes_block(spec) -> Block:
    return [
        "THE TWO COLOURS, AND NOTHING ELSE",
        f"  {CLASS_NAMES['floor'].upper()} {_rgb(FLOOR_RGB)} -- FLOOR. Everywhere a person "
        f"can walk: corridors, rooms, the space behind the doorway.",
        f"  {CLASS_NAMES['solid'].upper()} {_rgb(SOLID_RGB)} -- SOLID. Everything else: the "
        f"mass of the building, and the walls between rooms.",
        "",
        "Use these two colours flat and unmixed. Do not blend them, do not shade them, do not",
        "draw a line between them -- where they meet is the wall face. Any pixel that is",
        "neither colour reads as unpainted and fails.",
    ]


def subject_block(spec) -> Block:
    """What the building is, and what goes inside it. The two interviewed answers."""
    if not spec.object_prompt and not spec.intent:
        return None
    lines = ["WHAT THIS BUILDING IS"]
    if spec.object_prompt:
        lines.append(f"  The image is a {spec.object_prompt}, seen from above with its roof "
                     f"lifted off.")
    if spec.intent:
        lines.append(f"  Inside it: {spec.intent}")
    lines.append("  Most of a solid building is solid. A plan that is mostly SOLID with floor")
    lines.append("  cut through it is correct; one that is mostly floor is not.")
    return lines


def threshold_block(spec) -> Block:
    """Where the entrance is, in the model's own frame of reference.

    Given as a fraction of the canvas rather than in pixels: the plan pass runs downscaled,
    so a pixel coordinate would be wrong by the scale factor, and models place things by
    proportion far better than by number anyway.
    """
    if not spec.door_origin:
        return None
    fx = spec.door_origin[0] / spec.size[0]
    fy = spec.door_origin[1] / spec.size[1]
    horizontal = "left" if fx < 0.4 else "right" if fx > 0.6 else "centre"
    vertical = "top" if fy < 0.4 else "bottom" if fy > 0.6 else "middle"
    where = f"{vertical}-{horizontal}" if horizontal != "centre" else vertical
    entrance = spec.entrance_prompt or "doorway"
    return [
        "THE ENTRANCE - THIS IS THE PART THAT MATTERS",
        f"  There is one {entrance}, already painted, on the {where} edge. It is held out of",
        "  the mask: do not paint over it, do not move it, do not draw another one.",
        "  FLOOR must start immediately behind it and run inward. Not near it - AT it.",
        "  If the only thing you get right is that the floor meets that doorway, the plan is",
        "  usable. If you get everything else right and it does not, the plan is discarded.",
        "  Every room must be reachable on floor from that doorway.",
    ]


def scale_block(spec) -> Block:
    """Scale in characters, computed from the building. Never typed by a person."""
    width, height = spec.tiles
    lines = [
        "SCALE",
        f"  The whole building is about {width:.0f} x {height:.0f} characters across.",
        "  A corridor is 1 to 2 characters wide. A room is 3 to 6 characters across.",
    ]
    if spec.door_width:
        lines.append(f"  The doorway is {spec.door_width / spec.tile:.1f} characters wide; the "
                     f"corridor behind it should match.")
    if spec.rooms:
        lines.append(f"  Draw {spec.rooms} rooms joined by corridors, and no more.")
    return lines


def rules_block(spec) -> Block:
    return [
        "DO NOT",
        "  Do not paint any colour but the two given.",
        "  Do not draw texture, stone courses, blocks, shadow, or a border line.",
        "  Do not paint outside the mask.",
        "  Do not leave any part of the mask unpainted.",
        "  No text, labels, keys, grid lines, characters or objects.",
    ]


def plan_prompt(spec) -> str:
    return assemble(
        task_block(spec),
        classes_block(spec),
        subject_block(spec),
        threshold_block(spec),
        scale_block(spec),
        rules_block(spec),
    )
