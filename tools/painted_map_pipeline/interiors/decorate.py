"""Furnishing, step 1: the bare interior decorated N ways. The first of two gen-AI calls.

By hand this was the Leonardo web UI -- "decorate this with <adjectives>", eight or nine
times. Here it is `augment_interior` once per line of `decor/styles.txt`, and augment is the
right call rather than a fresh image: it starts from the accepted room, with the mask and the
downscale the room was rendered at, and writes the exterior back byte-identical. So a
decorated pixel (x, y) is the bare room's pixel (x, y), and positions read off a decorated
image later need no alignment step.

A variant is its folder, `decor/vNN`, seeded by line N of the styles file. Its `meta.json`
says what it was drawn from -- the line and the room -- so editing a line, or re-rendering the
room under it, shows the variant as stale at the gate instead of passing it on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import floor as floor_mod
from . import render as render_mod
from .trace import save_image

Image.MAX_IMAGE_PIXELS = None

DECOR = "decor"
STYLES = "styles.txt"
BASE = "base.png"
BASE_META = "base.json"
META = "meta.json"
STRIP = "decor_strip.png"
# What `augment_interior` writes for a single draw. The composite's real name is kept in the
# variant's meta, because `save_image` falls back to a fresh name when a viewer holds the file.
COMPOSITED = "augment_composited.png"
DRIFT = "augment_drift.txt"
PROMPT = "augment_prompt.txt"
# Everything a draw writes into its folder: what is moved aside before a redraw replaces it.
DRAW_FILES = ("augment*", "control.png", META)

# What a new building's styles file starts with. Furnishings only: the room's own look is the
# spec's intent, appended to every line, so the variants differ in what stands in the room
# and not in how it is painted.
STARTER_FURNISHINGS = (
    "statues and braziers standing against the walls, urns and an offering table on the floor",
    "a treasure hall: chests, heaps of gold and jewels, golden statues along the walls",
    "a shrine: an altar against the far wall, kneeling statues, braziers, banners hanging "
    "on the walls",
    "a burial chamber: a sarcophagus on a plinth, jars and guardian statues beside the doorways",
)

STYLES_HEADER = """\
# One furnishing variant per line: what to add to the room, and how it should look.
# Variant N is line N (blank lines and # comments do not count). Edit a line and the
# decorate gate shows that variant as stale; [r N] there redraws it, [x N] drops it.
"""


def decor_dir(work: Path) -> Path:
    return Path(work) / DECOR


def variant_folder(work: Path, number: int) -> Path:
    return decor_dir(work) / f"v{number:02d}"


# ---------------------------------------------------------------- the styles file

def ensure_styles(spec, work: Path, count: int) -> Path:
    """The styles file, written with `count` starter lines if the building has none yet.

    Never rewritten once it exists: it is the one thing in this step written by hand.
    """
    path = decor_dir(work) / STYLES
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    look = (spec.intent or "").strip()
    lines = []
    for index in range(max(1, int(count))):
        furnishings = STARTER_FURNISHINGS[index % len(STARTER_FURNISHINGS)]
        lines.append(f"{furnishings}; {look}" if look else furnishings)
    path.write_text(STYLES_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_styles(path: Path) -> list:
    """The variant lines, in order: blank lines and # comments skipped."""
    path = Path(path)
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


# ---------------------------------------------------------------- the room drawn on

def room_image(spec) -> Image.Image:
    """The accepted room as the game shows it: the interior asset over the exterior."""
    interior = Path(spec.interior_image)
    if not interior.exists():
        raise FileNotFoundError(f"no accepted interior at {interior}: finish `build` first")
    room = Image.open(spec.roof_image).convert("RGBA")
    asset = Image.open(interior).convert("RGBA")
    if asset.size != room.size:
        raise ValueError(f"{interior} is {asset.size}, the exterior is {room.size}")
    room.alpha_composite(asset)
    return room


def pixels_sha1(image: Image.Image) -> str:
    """A hash of the pixels, not the file: the same room saved twice hashes the same."""
    return hashlib.sha1(np.asarray(image.convert("RGBA")).tobytes()).hexdigest()


def write_base(spec, work: Path) -> tuple:
    """(path, sha1) of the room every variant is drawn on, rewritten only when it changed."""
    room = room_image(spec)
    digest = pixels_sha1(room)
    folder = decor_dir(work)
    path, meta_path = folder / BASE, folder / BASE_META
    if not (path.exists() and _read_json(meta_path).get("sha1") == digest):
        folder.mkdir(parents=True, exist_ok=True)
        room.save(path)
        meta_path.write_text(json.dumps({"sha1": digest, "interior": str(spec.interior_image)},
                                        indent=2), encoding="utf-8")
    return path, digest


def room_plan(spec, work: Path):
    """The room as it was painted -- the floor trace accept wrote the map from -- or None.

    Re-traced from `floor_raw.png` on disk, which is free. The plan the room was REQUESTED
    with is the wrong thing to show the model: the render insets floors and thickens walls,
    and "stand it on the floor" has to mean the floor that is actually painted.
    """
    raw = Path(work) / "floor_raw.png"
    if not raw.exists():
        return None
    return floor_mod.trace_floor(Image.open(raw).convert("RGB"), spec)


# ---------------------------------------------------------------- variants

@dataclass
class Variant:
    number: int
    additions: str           # its styles line; "" when the folder has no line any more
    folder: Path
    composited: Path = None  # None until drawn
    drift: float = None      # share of the room the draw changed
    kept: bool = True        # False once dropped at the gate
    stale: str = ""          # why the draw no longer matches its line or the room

    @property
    def tag(self) -> str:
        return f"v{self.number:02d}"

    @property
    def drawn(self) -> bool:
        return self.composited is not None

    @property
    def usable(self) -> bool:
        """What the next step may take: drawn, kept, and drawn from what is there now."""
        return self.drawn and self.kept and not self.stale

    def status(self) -> str:
        if not self.kept:
            return "dropped"
        if not self.drawn:
            return "not drawn"
        changed = "" if self.drift is None else f"{self.drift:.0%} changed"
        return f"STALE: {self.stale}" if self.stale else changed


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(folder: Path, **fields) -> None:
    meta = _read_json(folder / META)
    meta.update(fields)
    (folder / META).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def variants(work: Path, base_sha1: str, dry_run: bool = False) -> list:
    """Every variant: one per styles line, plus any folder left over from a longer file.

    A `--dry-run` draw is the copy backend handing the room back undecorated. It proves the
    walk, and must never be mistaken for a decoration by the run after it, so outside a dry
    run it counts as stale.
    """
    lines = read_styles(decor_dir(work) / STYLES)
    numbers = set(range(1, len(lines) + 1))
    for folder in decor_dir(work).glob("v[0-9][0-9]"):
        if folder.is_dir():
            numbers.add(int(folder.name[1:]))

    out = []
    for number in sorted(numbers):
        folder = variant_folder(work, number)
        meta = _read_json(folder / META)
        additions = lines[number - 1] if number <= len(lines) else ""
        composited = folder / meta.get("composited", COMPOSITED)
        drift = None
        try:
            drift = float((folder / DRIFT).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
        stale = ""
        if composited.exists():
            if not additions:
                stale = "it has no line in styles.txt any more"
            elif meta.get("additions") != additions:
                stale = "its line in styles.txt was edited"
            elif meta.get("base_sha1") != base_sha1:
                stale = "the room was re-rendered under it"
            elif meta.get("provider") == "copy" and not dry_run:
                stale = "it was drawn by --dry-run (the copy backend)"
        out.append(Variant(number=number, additions=additions, folder=folder,
                           composited=composited if composited.exists() else None,
                           drift=drift, kept=bool(meta.get("kept", True)) and bool(additions),
                           stale=stale))
    return out


def draw_variant(plan, config, variant: Variant, base: Path, base_sha1: str,
                 criticism: str = "") -> Path:
    """One edit call: the room plus this variant's furnishings. Returns the composite.

    Whatever the folder held from an earlier draw is overwritten; the gate moves it aside
    first, since a draw is paid for.
    """
    variant.folder.mkdir(parents=True, exist_ok=True)
    composited = render_mod.augment_interior(plan, config, variant.folder, base,
                                             variant.additions, criticism=criticism,
                                             decorate=True)[0]
    _write_meta(variant.folder, additions=variant.additions, base_sha1=base_sha1, kept=True,
                composited=Path(composited).name, provider=str(config.get("provider") or ""))
    return Path(composited)


def set_kept(variant: Variant, kept: bool) -> None:
    variant.folder.mkdir(parents=True, exist_ok=True)
    _write_meta(variant.folder, kept=bool(kept))


# ---------------------------------------------------------------- the strip

def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                       # Pillow before 10.1: one size only
        return ImageFont.load_default()


def decor_strip(base: Path, found: list, out_path: Path, width: int = 520,
                per_row: int = 4) -> Path:
    """The bare room, then every variant, labelled with its state, four to a row.

    Judged together, the way the render draws are: the point of drawing several is choosing
    between them, and that needs them side by side. A dropped variant is crossed out, a stale
    one labelled, one never drawn left as a dark tile.
    """
    room = Image.open(base).convert("RGB")
    room.thumbnail((width, width))
    tile_w, tile_h = room.size
    label_h, gap = 30, 10
    tiles = [("bare room", room, (235, 235, 235), False)]
    for variant in found:
        if variant.drawn:
            thumb = Image.open(variant.composited).convert("RGB")
            thumb.thumbnail((width, width))
        else:
            thumb = Image.new("RGB", (tile_w, tile_h), (40, 40, 44))
        colour = ((255, 140, 60) if variant.stale else
                  (150, 150, 150) if not variant.kept else (255, 220, 90))
        tiles.append((f"{variant.tag}  {variant.status()}", thumb, colour, not variant.kept))

    cols = max(1, min(per_row, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w + (cols - 1) * gap,
                              rows * (tile_h + label_h) + (rows - 1) * gap), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    font = _font(18)
    for index, (label, thumb, colour, crossed) in enumerate(tiles):
        row, col = divmod(index, cols)
        x, y = col * (tile_w + gap), row * (tile_h + label_h + gap)
        sheet.paste(thumb, (x, y + label_h))
        draw.text((x + 6, y + 5), label, fill=colour, font=font)
        if crossed:
            top, bottom = y + label_h, y + label_h + thumb.height - 1
            draw.line([x, top, x + thumb.width - 1, bottom], fill=(220, 40, 40), width=4)
            draw.line([x, bottom, x + thumb.width - 1, top], fill=(220, 40, 40), width=4)
    return save_image(sheet, out_path)
