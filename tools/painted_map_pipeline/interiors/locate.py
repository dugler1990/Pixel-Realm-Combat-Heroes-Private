"""Furnishing, step 4: each object on the sheet found in the decorated room, and placed there.

The sheet was drawn from the decorated room, so every prop cut from it is a picture of one
thing standing in that room. Each is searched for over the whole room -- its outline and its
colours, at a range of sizes, since the sheet's scale is not the room's -- and placed where it
matches best. Only inside the chamber (the part of the room the game shows), and two props
never claim the same spot: the better match keeps it and the other takes its next best.

The search runs coarse over the whole room, then fine round the few best places.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

PLACEMENTS = "placements.json"
RECREATED = "recreated.png"
COMPARE = "compare.png"
LOCATED = "locate.png"

# A prop is placed when its best match scores at least this (0..1).
MATCH_THRESHOLD = 0.35
# Sizes searched, as height in characters (spec.tile): the sheet's scale is not the room's.
MIN_TILES, MAX_TILES = 0.3, 3.0
SIZE_STEPS = 14
# The coarse pass, and the fine pass round its best places, in px per character.
COARSE_TILE_PX = 40.0
FINE_TILE_PX = 100.0
CANDIDATES = 6
FINE_SCALES = (0.9, 0.95, 1.0, 1.05, 1.1)
# Matches this good fix the sheet's scale (needs MIN_ANCHORS of them); every prop is then
# searched at that scale, this much either way.
ANCHOR_SCORE = 0.55
MIN_ANCHORS = 3
SHEET_SCALE_SPREAD = 0.2
# Two placements overlapping this much (of the smaller box) are one spot.
SAME_SPOT = 0.5


@dataclass
class Placement:
    prop: str
    tile_id: int
    box: tuple          # x0, y0, x1, y1 in room canvas px
    score: float
    mount: str = "floor"

    @property
    def feet(self) -> tuple:
        return ((self.box[0] + self.box[2]) / 2, self.box[3])

    def as_json(self) -> dict:
        x, y = self.feet
        return {"prop": self.prop, "tile_id": self.tile_id, "x": round(x, 1), "y": round(y, 1),
                "w": round(self.box[2] - self.box[0], 1), "h": round(self.box[3] - self.box[1], 1),
                "score": round(self.score, 3), "mount": self.mount}


def _edges(gray: np.ndarray) -> np.ndarray:
    smooth = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.0)
    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


class Room:
    """The decorated room at one scale: its colours, its edges, and where the chamber is."""

    def __init__(self, decorated: Image.Image, chamber: np.ndarray, tile: float, tile_px: float):
        self.scale = min(1.0, tile_px / float(tile))
        size = (max(1, round(decorated.width * self.scale)),
                max(1, round(decorated.height * self.scale)))
        self.rgb = cv2.resize(np.asarray(decorated.convert("RGB")), size,
                              interpolation=cv2.INTER_AREA).astype(np.float32)
        self.edges = _edges(cv2.cvtColor(self.rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY))
        self.chamber = cv2.resize(chamber.astype(np.uint8), size,
                                  interpolation=cv2.INTER_NEAREST) > 0

    def to_room(self, box) -> tuple:
        return tuple(v / self.scale for v in box)

    def to_here(self, box) -> tuple:
        return tuple(v * self.scale for v in box)


class Prop:
    """A cut-out from the sheet, ready to be searched for."""

    def __init__(self, record: dict, folder: Path):
        self.record = record
        self.image = Image.open(Path(folder) / record["file"]).convert("RGBA")

    @property
    def id(self) -> str:
        return self.record["id"]

    def at(self, height: int) -> tuple:
        """(rgb, edges, mask) of the prop scaled to `height` px."""
        width = max(3, round(height * self.image.width / self.image.height))
        rgba = np.asarray(self.image.resize((width, height), Image.LANCZOS)).astype(np.float32)
        mask = (rgba[..., 3] > 127).astype(np.float32)
        rgb = rgba[..., :3]
        edges = _edges(cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)) * mask
        return rgb, edges, mask


def _score_map(room: Room, rgb, edges, mask, window=None) -> np.ndarray:
    """Match score of the prop at every place in `window` (or the whole room): half its
    outline and inner edges against the room's, half its colours, each a masked normalised
    correlation, so only the prop's own pixels count."""
    x0, y0, x1, y1 = window or (0, 0, room.rgb.shape[1], room.rgb.shape[0])
    h, w = mask.shape
    if mask.sum() < 9 or x1 - x0 < w or y1 - y0 < h:
        return None
    edge_score = cv2.matchTemplate(room.edges[y0:y1, x0:x1], edges, cv2.TM_CCOEFF_NORMED,
                                   mask=mask)
    colour = np.zeros_like(edge_score)
    for c in range(3):
        colour += cv2.matchTemplate(room.rgb[y0:y1, x0:x1, c].copy(), rgb[..., c].copy(),
                                    cv2.TM_CCOEFF_NORMED, mask=mask)
    score = 0.5 * np.nan_to_num(edge_score) + 0.5 * np.nan_to_num(colour / 3)
    # Feet inside the chamber: the bottom centre of each placement.
    rows, cols = score.shape
    feet = room.chamber[y0:y1, x0:x1][h - 1:h - 1 + rows, w // 2:w // 2 + cols]
    return np.where(feet, score, -1.0)


def _heights(low: float, high: float, scale: float, steps: int = SIZE_STEPS) -> list:
    """Heights (px at `scale`) from `low` to `high` room px."""
    tall = np.geomspace(low * scale, high * scale, steps)
    return sorted({max(6, int(round(v))) for v in tall})


def candidates(coarse: Room, prop: Prop, low: float, high: float) -> list:
    """[(score, box in room px)]: the prop's best places in the room, distinct, best first,
    searched at heights `low`..`high` room px."""
    found = []
    for height in _heights(low, high, coarse.scale):
        rgb, edges, mask = prop.at(height)
        score = _score_map(coarse, rgb, edges, mask)
        if score is None:
            continue
        for _ in range(CANDIDATES):
            y, x = np.unravel_index(int(np.argmax(score)), score.shape)
            best = float(score[y, x])
            if best <= 0:
                break
            found.append((best, coarse.to_room((x, y, x + mask.shape[1], y + mask.shape[0]))))
            score[max(0, y - mask.shape[0] // 2):y + mask.shape[0] // 2 + 1,
                  max(0, x - mask.shape[1] // 2):x + mask.shape[1] // 2 + 1] = -1.0
    found.sort(key=lambda f: -f[0])
    distinct = []
    for score, box in found:
        if all(_overlap(box, other) < SAME_SPOT for _s, other in distinct):
            distinct.append((score, box))
        if len(distinct) == CANDIDATES:
            break
    return distinct


def refine(fine: Room, prop: Prop, box: tuple) -> tuple:
    """(score, box in room px): the best fit near `box`, at the fine scale."""
    x0, y0, x1, y1 = fine.to_here(box)
    height = y1 - y0
    best = (-1.0, box)
    for factor in FINE_SCALES:
        h = max(6, int(round(height * factor)))
        rgb, edges, mask = prop.at(h)
        w = mask.shape[1]
        cx, bottom = (x0 + x1) / 2, y1
        reach = 0.25 * h
        window = (int(max(0, cx - w / 2 - reach)), int(max(0, bottom - h - reach)),
                  int(min(fine.rgb.shape[1], cx + w / 2 + reach)),
                  int(min(fine.rgb.shape[0], bottom + reach)))
        score = _score_map(fine, rgb, edges, mask, window)
        if score is None:
            continue
        y, x = np.unravel_index(int(np.argmax(score)), score.shape)
        if score[y, x] > best[0]:
            left, top = window[0] + x, window[1] + y
            best = (float(score[y, x]), fine.to_room((left, top, left + w, top + h)))
    return best


def _overlap(a, b) -> float:
    """Intersection over the smaller box."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / smaller if smaller > 0 else 0.0


def find_props(decorated: Image.Image, chamber: np.ndarray, tile: float, props: list,
               threshold: float = MATCH_THRESHOLD) -> tuple:
    """(placements, missing ids): each prop at its best place in the room, if good enough.

    The sheet is drawn at one scale throughout, so the room's size for a prop is its sheet
    size times one number. First every prop is searched over the whole size range
    (MIN_TILES..MAX_TILES characters); the clear matches give that number; then every prop is
    searched again at it, +-SHEET_SCALE_SPREAD -- where small sizes no longer match noise.
    Best matches go first; a prop whose best place is already taken takes its next best.
    """
    coarse = Room(decorated, chamber, tile, COARSE_TILE_PX)
    fine = Room(decorated, chamber, tile, FINE_TILE_PX)

    def search(prop, low, high):
        return sorted((refine(fine, prop, box) for _s, box in candidates(coarse, prop, low, high)),
                      key=lambda f: -f[0])

    first = [(prop, search(prop, MIN_TILES * tile, MAX_TILES * tile)) for prop in props]
    # Not from the smallest sizes: a tiny template correlates well with noise anywhere.
    ratios = [(fit[0][1][3] - fit[0][1][1]) / prop.image.height
              for prop, fit in first if fit and fit[0][0] >= ANCHOR_SCORE
              and fit[0][1][3] - fit[0][1][1] >= 2 * MIN_TILES * tile]
    if len(ratios) >= MIN_ANCHORS:
        ratio = float(np.median(ratios))
        fits = [(prop, search(prop, prop.image.height * ratio * (1 - SHEET_SCALE_SPREAD),
                              prop.image.height * ratio * (1 + SHEET_SCALE_SPREAD)))
                for prop in props]
    else:
        fits = first
    fits.sort(key=lambda f: -(f[1][0][0] if f[1] else -1))
    placed, missing = [], []
    for prop, refined in fits:
        spot = next(((score, box) for score, box in refined if score >= threshold
                     and all(_overlap(box, p.box) < SAME_SPOT for p in placed)), None)
        if spot is None:
            missing.append(prop.id)
            continue
        placed.append(Placement(prop=prop.id, tile_id=prop.record["tile_id"], box=spot[1],
                                score=spot[0], mount=prop.record.get("mount", "floor")))
    return placed, missing


def recreate(base: Image.Image, placements: list, images: dict) -> Image.Image:
    """The bare room with the props pasted on it, back to front by where their feet are."""
    room = base.convert("RGBA").copy()
    for placement in sorted(placements, key=lambda p: p.feet[1]):
        x0, y0, x1, y1 = placement.box
        size = (max(1, round(x1 - x0)), max(1, round(y1 - y0)))
        sprite = images[placement.prop].resize(size, Image.LANCZOS)
        layer = Image.new("RGBA", room.size, (0, 0, 0, 0))
        layer.paste(sprite, (round(x0), round(y0)), sprite)
        room = Image.alpha_composite(room, layer)
    return room


def located_overlay(decorated: Image.Image, placements: list, width: int = 1600) -> Image.Image:
    """The decorated room with a box and the prop id on each placement."""
    from PIL import ImageDraw

    factor = min(1.0, width / decorated.width)
    out = decorated.convert("RGB").resize((round(decorated.width * factor),
                                           round(decorated.height * factor)), Image.LANCZOS)
    draw = ImageDraw.Draw(out)
    for placement in placements:
        box = [v * factor for v in placement.box]
        draw.rectangle(box, outline=(60, 255, 90), width=2)
        draw.text((box[0] + 2, box[1] + 1), f"{placement.prop} {placement.score:.2f}",
                  fill=(60, 255, 90), stroke_width=1, stroke_fill=(0, 0, 0))
    return out


def side_by_side(left: Image.Image, right: Image.Image, width: int = 1400) -> Image.Image:
    factor = min(1.0, width / left.width)
    size = (round(left.width * factor), round(left.height * factor))
    out = Image.new("RGB", (2 * size[0] + 10, size[1]), (24, 24, 24))
    out.paste(left.convert("RGB").resize(size, Image.LANCZOS), (0, 0))
    out.paste(right.convert("RGB").resize(size, Image.LANCZOS), (size[0] + 10, 0))
    return out


def locate_variant(spec, plan, state, catalog: dict, base_path,
                   threshold: float = MATCH_THRESHOLD) -> tuple:
    """Step 4 for one variant: find its sheet's props in its room, rebuild the room from them.

    Returns (placements, missing prop ids). Writes the review files into the variant folder.
    """
    from . import extract as extract_mod
    from . import kit as kit_mod
    from .emit import chamber_mask_from_plan
    from .trace import save_image

    folder = state.variant.folder
    set_dir = kit_mod.prop_set_dir(spec)
    decorated = Image.open(state.variant.composited).convert("RGB")
    base = Image.open(base_path).convert("RGB")
    kept = {p["id"]: p for p in catalog["props"] if p.get("keep", True)}
    ids = [item["id"] for item in extract_mod.extracted(state.variant).get("props", [])
           if item["id"] in kept]
    props = [Prop(kept[pid], set_dir) for pid in ids]
    placements, missing = find_props(decorated, chamber_mask_from_plan(plan), spec.tile, props,
                                     threshold)

    images = {p.id: p.image for p in props}
    recreated = recreate(base, placements, images)
    save_image(recreated.convert("RGB"), folder / RECREATED)
    save_image(side_by_side(decorated, recreated), folder / COMPARE)
    save_image(located_overlay(decorated, placements), folder / LOCATED)
    (folder / PLACEMENTS).write_text(json.dumps({
        "variant": state.tag, "threshold": threshold, "set": set_dir.name,
        "sheet_sha1": kit_mod.file_sha1(state.sheet),
        "composited_sha1": kit_mod.file_sha1(state.variant.composited),
        "placements": [p.as_json() for p in placements], "missing": missing,
    }, indent=2) + "\n", encoding="utf-8")
    return placements, missing


def review_strip(rows: list, out_path, width: int = 1600):
    """Each variant's decorated | rebuilt pair under its label: the picture step 4 is judged on."""
    from PIL import ImageDraw

    from .decorate import _font
    from .trace import save_image

    font = _font(18)
    pictures = []
    for label, path in rows:
        picture = None
        if path is not None and Path(path).exists():
            picture = Image.open(path).convert("RGB")
            picture = picture.resize((width, round(picture.height * width / picture.width)),
                                     Image.LANCZOS)
        pictures.append((label, picture))
    height = sum(30 + (p.height if p is not None else 0) + 10 for _l, p in pictures)
    sheet = Image.new("RGB", (width, max(1, height)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, picture in pictures:
        draw.text((6, y + 5), label, fill=(255, 220, 90), font=font)
        y += 30
        if picture is not None:
            sheet.paste(picture, (0, y))
            y += picture.height
        y += 10
    return save_image(sheet, out_path)


def read_placements(variant) -> dict:
    try:
        return json.loads((variant.folder / PLACEMENTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
