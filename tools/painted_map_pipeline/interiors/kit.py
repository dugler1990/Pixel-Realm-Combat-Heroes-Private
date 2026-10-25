"""Furnishing, step 2: a sprite sheet of the objects in each decorated room. The second gen-AI call.

By hand this was the Leonardo web UI again -- "make a sprite sheet of the objects" on one
decorated image. Here it is one edit call per kept variant: the decorated room is IMAGE 1,
and the model is asked for a sprite sheet of the objects in it, each whole and separate, on a
flat key colour. Step 3 cuts the sheet; step 4 finds each cut object in this room.

The room is the call's first image because an edit returns the size of its first image: it
is sent at the largest size the backend takes, so the sheet is too.

`--dry-run` hands the room back unchanged (the copy backend).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from ..image_client import make_image_client
from .prompt import assemble, with_criticism
from .trace import save_image

Image.MAX_IMAGE_PIXELS = None

PROPS_ROOT = Path("Graphics/Props")
STYLE_MASTER = "style_master.png"
DRY_RUN = "_dry_run"


def dry_run_sets() -> None:
    """Send this run's prop sets to `<root>/_dry_run/`: a --dry-run sheet is the copy
    backend's, and its cut-outs must never join the real set the game draws from."""
    global PROPS_ROOT
    if PROPS_ROOT.name != DRY_RUN:
        PROPS_ROOT = PROPS_ROOT / DRY_RUN

SHEET = "sheet.png"
SHEET_ROOM = "sheet_room.png"
SHEET_PROMPT = "sheet_prompt.txt"
SHEET_META = "sheet.json"
STRIP = "sheets_strip.png"
# Everything a sheet draw writes into its variant's folder: moved aside before a redraw.
SHEET_FILES = ("sheet*",)

# The background the sheet is drawn on. Not black: dark statues on a black sheet came out
# notched and fringed, because "background" and "dark object" were the same test. Nothing in
# a tomb is magenta.
KEY = (255, 0, 255)
KEY_NAME = "MAGENTA, RGB(255, 0, 255)"
# The largest the room is sent at when the backend does not fix a size: both edges within
# this, and a multiple of 16 (gpt-image-2).
SHEET_SIZE = (2880, 2880)


def _slug(text: str) -> str:
    return "_".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def prop_set_dir(spec) -> Path:
    """Where this building's props live, shared with every building of its kind.

    Named after what the building is (`object_prompt`), so the four pyramids on sunspine draw
    from, and add to, the one pyramid set (`Graphics/Props/pyramid`).
    """
    return PROPS_ROOT / _slug(spec.object_prompt or spec.building)


def style_master(spec):
    """The set's locked style, or None until one is chosen."""
    path = prop_set_dir(spec) / STYLE_MASTER
    return path if path.exists() else None


def sheet_size(config) -> tuple:
    width, height = int(config.get("width") or 0), int(config.get("height") or 0)
    return (width, height) if width > 0 and height > 0 else SHEET_SIZE


def file_sha1(path: Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- the room sent

def sheet_room(decorated: Image.Image, config) -> Image.Image:
    """The decorated room at the size the sheet comes back at.

    A backend that fixes its size (`width`/`height` in the config) gets exactly that;
    otherwise the room keeps its shape, as large as fits SHEET_SIZE, edges a multiple of 16.
    """
    room = decorated.convert("RGB")
    width, height = int(config.get("width") or 0), int(config.get("height") or 0)
    if width <= 0 or height <= 0:
        factor = min(SHEET_SIZE[0] / room.width, SHEET_SIZE[1] / room.height)
        width = max(16, int(room.width * factor) // 16 * 16)
        height = max(16, int(room.height * factor) // 16 * 16)
    return room.resize((width, height), Image.LANCZOS)


# ---------------------------------------------------------------- the prompt

def sheet_block(spec, additions: str):
    subject = spec.object_prompt or "building"
    lines = [
        f"IMAGE 1 IS A ROOM: the inside of a {subject}, seen from above at a three-quarter angle.",
    ]
    if additions.strip():
        lines.append(f"  It was furnished with: {additions.strip()}")
    lines += [
        "",
        "MAKE A SPRITE SHEET OF THE OBJECTS IN THIS ROOM:",
        "  - each object whole and separate, with a clear gap of background round it",
        "  - the objects as they are in the room: seen from the same angle, painted the same way",
        "  - the object only: no floor under it, no wall behind it, no shadow on the ground",
        "",
        f"THE BACKGROUND IS FLAT {KEY_NAME}: one solid colour, with no gradient, texture or",
        "glow. No object is that colour.",
    ]
    return lines


def reference_block(spec, has_style: bool):
    lines = []
    if has_style:
        lines += ["IMAGE 2 IS THE PROP SET'S STYLE: render the objects the way these are.", ""]
    lines.append("No text, numbers, labels, captions, outlines, frames, grid lines or watermarks.")
    return lines


def sheet_prompt(spec, additions: str, has_style: bool) -> str:
    return assemble(sheet_block(spec, additions), reference_block(spec, has_style))


# ---------------------------------------------------------------- per variant

@dataclass
class SheetState:
    """Where a variant stands at step 2."""
    variant: object          # decorate.Variant
    sheet: Path = None       # None until drawn
    stale: str = ""

    @property
    def tag(self) -> str:
        return self.variant.tag

    @property
    def drawn(self) -> bool:
        return self.sheet is not None

    @property
    def usable(self) -> bool:
        return self.drawn and not self.stale

    def status(self) -> str:
        if not self.drawn:
            return "not drawn"
        return f"STALE: {self.stale}" if self.stale else "drawn"


def sheet_state(variant, dry_run: bool = False) -> SheetState:
    folder = variant.folder
    sheet = folder / SHEET
    if not sheet.exists():
        return SheetState(variant)
    meta = _read_json(folder / SHEET_META)
    stale = ""
    if not variant.drawn or meta.get("composited_sha1") != file_sha1(variant.composited):
        stale = "the decorated room was redrawn under it"
    elif meta.get("provider") == "copy" and not dry_run:
        stale = "it was drawn by --dry-run (the copy backend)"
    return SheetState(variant, sheet=sheet, stale=stale)


def draw_sheet(plan, config, variant, criticism: str = "", attach=()) -> Path:
    """One edit call: the decorated room in, a sprite sheet of its objects out."""
    spec = plan.spec
    folder = variant.folder
    if not variant.drawn:
        raise ValueError(f"{variant.tag} has no decorated room to draw a sheet of")
    room = sheet_room(Image.open(variant.composited), config)
    room_path = save_image(room, folder / SHEET_ROOM)
    style = style_master(spec)
    images = [room_path] + ([style] if style else [])
    prompt = with_criticism(sheet_prompt(spec, variant.additions, bool(style)),
                            criticism, attach, first_index=len(images) + 1)
    (folder / SHEET_PROMPT).write_text(prompt, encoding="utf-8")

    out = folder / SHEET
    print(f"  {variant.tag}: the room at {room.width}x{room.height}, "
          f"{len(images) + len(attach)} image(s)")
    make_image_client(config).generate(
        prompt, [str(p) for p in images] + [str(p) for p in attach], str(out), mask=None)
    if not out.exists():
        raise RuntimeError(f"{variant.tag}: the backend produced no sheet at {out}")
    _write_json(folder / SHEET_META, {
        "composited_sha1": file_sha1(variant.composited),
        "provider": str(config.get("provider") or ""), "criticism": criticism})
    return out


def use_as_style(spec, source: Path) -> Path:
    """Lock the set's style to `source`: later sheets are shown it as image 2."""
    target = prop_set_dir(spec) / STYLE_MASTER
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.open(source).convert("RGB").save(target)
    return target


# ---------------------------------------------------------------- the strip

def sheets_strip(states: list, out_path: Path, width: int = 560) -> Path:
    """One row per variant: its decorated room and the sheet that came back."""
    from .decorate import _font

    font = _font(18)
    label_h, gap = 30, 10
    rows = []
    for state in states:
        tiles = []
        for path in (state.variant.composited, state.sheet):
            if path and Path(path).exists():
                thumb = Image.open(path).convert("RGB")
                thumb.thumbnail((width, width))
            else:
                thumb = Image.new("RGB", (width, width * 3 // 4), (40, 40, 44))
            tiles.append(thumb)
        rows.append((f"{state.tag}  {state.status()}", tiles, bool(state.stale)))
    row_h = max((max(t.height for t in tiles) for _l, tiles, _s in rows), default=width)
    sheet = Image.new("RGB", (2 * width + gap, max(1, len(rows)) * (row_h + label_h + gap)),
                      (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for index, (label, tiles, stale) in enumerate(rows):
        y = index * (row_h + label_h + gap)
        draw.text((6, y + 5), label + "      room  |  sheet",
                  fill=(255, 140, 60) if stale else (255, 220, 90), font=font)
        for column, thumb in enumerate(tiles):
            sheet.paste(thumb, (column * (width + gap), y + label_h))
    return save_image(sheet, out_path)
