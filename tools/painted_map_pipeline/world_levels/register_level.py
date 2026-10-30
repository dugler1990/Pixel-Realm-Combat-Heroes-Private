"""Register an assembled level with the game: a path, a lookup entry and a menu slot.

Adding a level touches two files, and each is a literal that has to gain exactly one entry:
``Code/level_layouts.py`` (the one level table the client, the server and these tools read)
and the selection grid. Kept apart from the assembly so a failure here cannot leave the game
code half-edited, and written to be idempotent: running it twice adds nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

LAYOUTS = Path("Code/level_layouts.py")
SELECTION = Path("Code/LevelSelection.py")


def existing_levels(repo: Path) -> dict[int, str]:
    """Level number -> layout path, read from Code/level_layouts.py."""
    text = (repo / LAYOUTS).read_text(encoding="utf-8")
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
    """Kept for callers: the level lookup is already a dict in Code/level_layouts.py."""
    return False


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


def find_existing(repo: Path, slug: str, region: str = "Frostreach"):
    """The number and slot this slug is already registered under, or None.

    Without this, re-running against a level that already exists allocates a FRESH number and
    slot: the per-file guards each ask "is my line already here?", and the answer for Main2 is
    yes (so no level_N_layout_path is written) while for the menu it is no (so a new slot is).
    The result is a menu entry pointing at a number nothing maps to, which falls through to the
    default layout -- a second tile that silently opens a different level.
    """
    layout = f"../levels/{region}/{slug}"
    layouts_text = (repo / LAYOUTS).read_text(encoding="utf-8")
    match = re.search(rf"^level_(\d+)_layout_path = '{re.escape(layout)}'", layouts_text, re.M)
    if not match:
        return None
    number = int(match.group(1))
    sel_text = (repo / SELECTION).read_text(encoding="utf-8")
    slot = re.search(rf"\((\d+),\s*(\d+)\)\s*:\s*{number}\b", sel_text)
    return number, (int(slot.group(1)), int(slot.group(2))) if slot else None


def register(repo: Path, *, slug: str, number: int, slot: tuple[int, int],
             region: str = "Frostreach", world_png: Path | None = None) -> dict:
    """Add the level to Code/level_layouts.py, the selection grid and the thumbnail folder."""
    repo = Path(repo).resolve()
    layout = f"../levels/{region}/{slug}"
    changed: list[str] = []
    refactored = ensure_dict_lookup(repo)

    layouts_path = repo / LAYOUTS
    text = layouts_path.read_text(encoding="utf-8")
    if layout not in text:
        # The path name after the last one, then its entry at the end of LAYOUT_TO_LEVEL.
        text = re.sub(
            r"(^level_\d+_layout_path = '[^']+'\n)(?!level_)",
            lambda m: m.group(1) + f"level_{number}_layout_path = '{layout}'\n",
            text, count=1, flags=re.M,
        )
        text, count = re.subn(
            r"(LAYOUT_TO_LEVEL = \{.*?)(\n\})",
            lambda m: m.group(1) + f"\n    level_{number}_layout_path: {number}," + m.group(2),
            text, count=1, flags=re.DOTALL,
        )
        if not count:
            raise RuntimeError(f"{LAYOUTS}: could not find LAYOUT_TO_LEVEL")
        layouts_path.write_text(text, encoding="utf-8")
        changed.append(str(LAYOUTS))

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
