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
from ..review_gate import with_criticism  # noqa: F401  (kit, plan and render import it from here)

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
        "  \"Inside\" means towards the middle of the building, not further from the camera.",
        "  FLOOR must start ON THE INSIDE FACE of that doorway and run into the building.",
        "  If the only thing you get right is that the floor meets that doorway, the plan is",
        "  usable. If you get everything else right and it does not, the plan is discarded.",
        "  Every room must be reachable on floor from that doorway.",
    ]


# How wide a corridor should be, and how big a room, in PLAYERS. The old prompt said "1 to 2
# characters wide" and "3 to 6 characters across" -- fixed text, sent whether the building was
# 25 characters or 5, and a character is 2.8 players. So a 7-character pyramid was asked for
# rooms it could not hold, and the model resolved the contradiction by shrinking everything
# until nothing was walkable.
# The narrowest anything walkable may be, in players. Not 1.0: a gap exactly one person wide
# is one you get stuck in, and it leaves nothing for the collision band's rounding. Nothing --
# corridor, doorway, or a value typed at the menu -- may go below this, and anything that does
# is reported rather than accepted.
MIN_CORRIDOR_PLAYERS = 1.25
CORRIDOR_PLAYERS = (1.5, 2.5)
ROOM_PLAYERS = (4.0, 8.0)

# Below this many rooms' worth of chamber, there is no plan with rooms AND corridors that
# fits, and asking for one produces a miniature of a real dungeon rather than a small dungeon.
SINGLE_CHAMBER_BELOW = 2.5


def _players(spec, player_width: float) -> tuple:
    """The chamber measured in players -- the unit that decides what can fit in it."""
    return (spec.size[0] / player_width, spec.size[1] / player_width)


def scale_block(spec, player_width: float = None, player_height: float = None,
                corridor_players: tuple = CORRIDOR_PLAYERS,
                room_players: tuple = ROOM_PLAYERS) -> Block:
    """Scale in players, computed from the building and the character. Never typed.

    In players rather than characters because the player is the thing that has to fit, and a
    tile is nearly three of him. Everything here is derived: the only judgement is how many
    players wide a corridor should be, and that is a constant above with a name.
    """
    from .player_size import player_size

    if player_width is None or player_height is None:
        measured = player_size(scale=spec.world_scale)
        player_width = player_width or measured.width
        player_height = player_height or measured.height

    corridor_players = getattr(spec, "corridor_players", None) or corridor_players
    room_players = getattr(spec, "room_players", None) or room_players
    across, down = _players(spec, player_width)
    lines = [
        "SCALE",
        f"  A person is one unit wide. The whole building is about {across:.0f} x {down:.0f} "
        f"people across.",
    ]

    # One chamber for two different reasons, said once. Either you asked for a single room,
    # or two rooms and a corridor between them do not fit -- and the prompt should not tell
    # you the building is small when you simply asked for one room.
    asked_for_one = spec.rooms == 1
    too_small = min(across, down) < SINGLE_CHAMBER_BELOW * room_players[0]
    single = asked_for_one or too_small

    if single:
        if too_small and not asked_for_one:
            lines.append("  This building is SMALL: rooms joined by corridors do not fit in "
                         "it and would come out too narrow to walk down.")
        lines.append("  Draw ONE chamber. A single open floor filling most of the inside and "
                     "reaching the doorway -- no corridors, no side chambers, nothing "
                     "branching.")
    else:
        lines.append(f"  A corridor is {corridor_players[0]:g} to {corridor_players[1]:g} "
                     f"people wide. A room is {room_players[0]:g} to {room_players[1]:g} "
                     f"people across.")
        if spec.rooms:
            lines.append(f"  Draw {spec.rooms} rooms joined by corridors, and no more.")
        lines.append(f"  A wall between two rooms is about "
                     f"{spec.partition / player_width:.1f} people thick.")

    if spec.door_width:
        lines.append(f"  The doorway is {spec.door_width / player_width:.1f} people wide; the "
                     f"floor behind it must be at least that wide.")
    # The ruler is in the picture because the numbers alone were not enough: given only
    # "1.5 people wide", the width has to be derived from the frame, and a plan came back with
    # corridors half the size asked for. A thing to match is not a sum.
    lines.append("  THE FIGURE AND THE BAR drawn on the image are one person. Nothing walkable "
                 "may be narrower than that bar. Paint over both -- they are a ruler, not part "
                 "of the building.")
    return lines


def rules_block(spec) -> Block:
    return [
        "DO NOT",
        "  Do not paint any colour but the colours given.",
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

