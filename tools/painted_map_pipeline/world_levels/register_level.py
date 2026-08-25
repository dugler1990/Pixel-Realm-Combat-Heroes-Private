"""Register an assembled level with the game: a path, two lookups and a menu slot.

Adding a level touches three files, and every one of them is a literal that has to gain
exactly one entry. Kept apart from the assembly so a failure here cannot leave the game code
half-edited, and written to be idempotent: running it twice adds nothing.

``Code/Main2.py`` also carried a ternary chain mapping level number to path, which is not
something to edit programmatically. ``ensure_dict_lookup`` replaces it with a dict lookup over
the LAYOUT_TO_LEVEL that was already there -- behaviour identical, and registration becomes a
single dict entry rather than another link in a chain.
"""

from __future__ import annotations

import re
from pathlib import Path

MAIN = Path("Code/Main2.py")
DEV = Path("Code/Level4_tmxdev.py")
SELECTION = Path("Code/LevelSelection.py")

_TERNARY = re.compile(
    r"layouts_dir = \(level_6_layout_path if level_number == 6 else.*?"
    r"else level_10_layout_path\)",
    re.DOTALL,
)
_LOOKUP = (
    "layouts_dir = LEVEL_TO_LAYOUT.get(level_number, level_10_layout_path)"
)


def existing_levels(repo: Path) -> dict[int, str]:
    """Level number -> layout path, read from Main2's LAYOUT_TO_LEVEL."""
    text = (repo / MAIN).read_text(encoding="utf-8")
    out: dict[int, str] = {}
    for name, value in re.findall(r"^level_(\d+)_layout_path = '([^']+)'", text, re.M):
        out[int(name)] = value
    return out


def taken_slots(repo: Path) -> set[tuple[int, int]]:
    text = (repo / SELECTION).read_text(encoding="utf-8")
    block = re.search(r"level_map = \{(.*?)\n\s*\}", text, re.DOTALL)
    if not block:
        return set()
    # Commented-out entries are free slots, not taken ones -- the block is full of them.
    live = "\n".join(line for line in block.group(1).splitlines()
                     if not line.lstrip().startswith("#"))
    return {
        (int(row), int(col))
        for row, col in re.findall(r"\((\d+)\s*,\s*(\d+)\)\s*:", live)
    }


def ensure_dict_lookup(repo: Path) -> bool:
    """Swap Main2's level-number ternary chain for a dict lookup. Idempotent."""
    path = repo / MAIN
    text = path.read_text(encoding="utf-8")
    if "LEVEL_TO_LAYOUT" in text:
        return False
    if not _TERNARY.search(text):
        raise RuntimeError(f"{MAIN}: the layouts_dir ternary is not where it was; not editing")
    text = _TERNARY.sub(_LOOKUP, text)
    # Defined right after the table it inverts, so the two cannot drift apart.
    text = text.replace(
        "\n\nLAYOUT_TO_LEVEL = {",
        "\n\nLAYOUT_TO_LEVEL = {",
    )
    anchor = re.search(r"(LAYOUT_TO_LEVEL = \{.*?\n\})", text, re.DOTALL)
    text = text[: anchor.end()] + (
        "\n\n# Inverted so a level number resolves to its folder in one lookup. Adding a level\n"
        "# is then one entry in the table above rather than another branch in a chain.\n"
        "LEVEL_TO_LAYOUT = {number: path for path, number in LAYOUT_TO_LEVEL.items()}\n"
    ) + text[anchor.end():]
    path.write_text(text, encoding="utf-8")
    return True


def write_thumbnail(repo: Path, slot: tuple[int, int], world_png: Path) -> Path:
    """The grid thumbnail, without which the slot does not appear at all.

    ``LevelSelection.load_level_images`` treats the presence of
    ``Graphics/Level/{row+1}_{col+1}.png`` as the level being unlocked -- a ``level_map`` entry
    on its own is invisible. So registering without this looks like it silently did nothing.
    Scaled to the grid cell at draw time, so only the aspect ratio matters here.
    """
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    destination = repo / "Graphics" / "Level" / f"{slot[0] + 1}_{slot[1] + 1}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(world_png) as opened:
        world = opened.convert("RGB")
        world.resize((800, max(1, round(800 * world.height / world.width)))).save(destination)
    return destination


def register(repo: Path, *, slug: str, number: int, slot: tuple[int, int],
             region: str = "Frostreach", world_png: Path | None = None) -> dict:
    """Add the level to Main2, Level4_tmxdev, the selection grid and the thumbnail folder."""
    repo = Path(repo).resolve()
    layout = f"../levels/{region}/{slug}"
    changed: list[str] = []
    refactored = ensure_dict_lookup(repo)

    main_path = repo / MAIN
    text = main_path.read_text(encoding="utf-8")
    if layout not in text:
        text = re.sub(
            r"(^level_\d+_layout_path = '[^']+'\n)(?!level_)",
            lambda m: m.group(1) + f"level_{number}_layout_path = '{layout}'\n",
            text, count=1, flags=re.M,
        )
        text = text.replace(
            "    level_11_layout_path: 11,\n",
            f"    level_11_layout_path: 11,\n    level_{number}_layout_path: {number},\n",
        )
        main_path.write_text(text, encoding="utf-8")
        changed.append(str(MAIN))

    dev_path = repo / DEV
    text = dev_path.read_text(encoding="utf-8")
    if layout not in text:
        text = text.replace(
            "    '../levels/Frostreach/sunspine_dunes_01': 11,\n",
            f"    '../levels/Frostreach/sunspine_dunes_01': 11,\n    '{layout}': {number},\n",
        )
        dev_path.write_text(text, encoding="utf-8")
        changed.append(str(DEV))

    sel_path = repo / SELECTION
    text = sel_path.read_text(encoding="utf-8")
    entry = f"({slot[0]}, {slot[1]}): {number}"
    if entry not in text:
        # Anchored on the whole line, comment included. Matching only the prefix left the
        # previous entry's trailing comment dangling off the end of the new one.
        text, count = re.subn(
            r"^(\s*\(1, 0\): 11,.*)$",
            lambda m: m.group(1) + f"\n{' ' * 13}({slot[0]}, {slot[1]}): {number},  # {slug}",
            text, count=1, flags=re.M,
        )
        if not count:
            raise RuntimeError(f"{SELECTION}: could not find the level_map anchor")
        sel_path.write_text(text, encoding="utf-8")
        changed.append(str(SELECTION))

    thumbnail = None
    if world_png is not None:
        thumbnail = str(write_thumbnail(repo, slot, Path(world_png)))
        changed.append(thumbnail)

    return {"slug": slug, "level_number": number, "slot": list(slot),
            "layout": layout, "changed": changed, "ternary_refactored": refactored,
            "thumbnail": thumbnail}
