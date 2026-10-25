"""Detect and crop cells from labeled sprite sheets."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Cell:
    """One frame crop in sheet pixel space."""

    name: str
    box: tuple[int, int, int, int]  # left, top, right, bottom (exclusive)

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


def _dark_runs(mean: np.ndarray, percentile: float, min_len: int) -> list[tuple[int, int]]:
    thr = float(np.percentile(mean, percentile))
    dark = mean < thr
    runs: list[tuple[int, int]] = []
    i = 0
    n = len(dark)
    while i < n:
        if not dark[i]:
            i += 1
            continue
        j = i
        while j < n and dark[j]:
            j += 1
        if j - i >= min_len:
            runs.append((i, j))
        i = j
    return runs


def _content_spans(
    length: int,
    gutters: Sequence[tuple[int, int]],
    *,
    margin: int = 2,
    min_span: int = 24,
) -> list[tuple[int, int]]:
    """Invert gutter runs into content spans, clamped to [0, length)."""
    cuts = [(0, 0)] + list(gutters) + [(length, length)]
    spans: list[tuple[int, int]] = []
    for (a0, a1), (b0, b1) in zip(cuts, cuts[1:]):
        lo = a1 + margin
        hi = b0 - margin
        if hi - lo >= min_span:
            spans.append((lo, hi))
    return spans


def detect_gutter_grid(
    image: Image.Image,
    *,
    row_percentile: float = 18,
    col_percentile: float = 12,
    min_gutter: int = 4,
    skip_first_row_span: bool = True,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return (row_spans, col_spans) from dark label/gutter bands.

    AI sheets often put black headers and thin black separators between cells.
    The first row span is usually the title band — skip it by default.
    """
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    row_mean = arr.mean(axis=(1, 2))
    col_mean = arr.mean(axis=(0, 2))
    h, w = arr.shape[:2]
    row_gutters = _dark_runs(row_mean, row_percentile, min_gutter)
    col_gutters = _dark_runs(col_mean, col_percentile, min_gutter)
    rows = _content_spans(h, row_gutters, min_span=40)
    cols = _content_spans(w, col_gutters, min_span=40)
    if skip_first_row_span and len(rows) > 1:
        # Drop title strip when it is much shorter than the next content row.
        if rows[0][1] - rows[0][0] < 0.55 * (rows[1][1] - rows[1][0]):
            rows = rows[1:]
    return rows, cols


def cells_from_grid(
    row_spans: Sequence[tuple[int, int]],
    col_spans: Sequence[tuple[int, int]],
    *,
    row_names: Sequence[str] | None = None,
    cols_per_row: Sequence[int] | None = None,
    inset: tuple[int, int, int, int] = (4, 10, 4, 4),
) -> list[Cell]:
    """Build named cells. cols_per_row lets short rows (e.g. targeting=5) drop extras."""
    left_i, top_i, right_i, bottom_i = inset
    cells: list[Cell] = []
    for ri, (y0, y1) in enumerate(row_spans):
        name = row_names[ri] if row_names and ri < len(row_names) else f"row{ri:02d}"
        n_cols = cols_per_row[ri] if cols_per_row and ri < len(cols_per_row) else len(col_spans)
        for ci, (x0, x1) in enumerate(col_spans[:n_cols]):
            box = (
                int(x0 + left_i),
                int(y0 + top_i),
                int(x1 - right_i),
                int(y1 - bottom_i),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            cells.append(Cell(name=f"{name}_{ci + 1:02d}", box=box))
    return cells


def cells_from_boxes(
    named_boxes: Iterable[tuple[str, tuple[int, int, int, int]]],
) -> list[Cell]:
    return [Cell(name=n, box=tuple(b)) for n, b in named_boxes]  # type: ignore[arg-type]


@dataclass(frozen=True)
class FoundObject:
    """One loose object on a flat sheet: its box and which pixels are its own."""

    cell: Cell
    mask: np.ndarray  # bool, cell.box-sized: this object's area (neighbours excluded)
    black_thr: float  # what counted as lit on this sheet; the matte cuts at the same level
    background: tuple = (0, 0, 0)  # the sheet's colour; "lit" is distance from it


# A background darker than this (its brightest channel) is a black sheet, and is measured
# as black exactly: the thresholds below were tuned on brightness, and the textured near-black
# of a "concept" sheet is what `sheet_black` already allows for.
DARK_BACKGROUND = 60


def sheet_background(rgb: np.ndarray, border: float = 0.01) -> tuple:
    """The sheet's own colour: the median of a thin band round its edge.

    A sheet is drawn on one flat colour, and nothing is drawn across its rim, so the border
    is that colour wherever an object does not reach it. Black for the Leonardo sheets,
    magenta for the furnishing ones.
    """
    h, w = rgb.shape[:2]
    band = max(2, round(min(h, w) * border))
    edge = np.concatenate([rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                           rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)])
    colour = tuple(int(round(v)) for v in np.median(edge, axis=0))
    return (0, 0, 0) if max(colour) < DARK_BACKGROUND else colour


def distance_from(rgb: np.ndarray, background: tuple) -> np.ndarray:
    """How far each pixel is from the sheet's colour: its largest channel difference.

    For a black sheet this is the brightest channel, which is what "lit" always meant.
    """
    if not any(background):
        return rgb.max(axis=2)
    return np.abs(rgb - np.asarray(background, dtype=np.float32)).max(axis=2)


def _is_text_or_rule(w: int, h: int, text_h: int) -> bool:
    """Headings, captions and divider lines: a flat wide strip, or hairline thin."""
    if min(w, h) <= 4:
        return True  # divider rule
    if w >= 8 * h:
        return True  # heading underline with its diamond ends
    return h <= text_h and w >= 2 * h  # a word or a caption


def _erase_long_hairlines(
    lit: np.ndarray, black: np.ndarray, min_len: int, clear: int = 3, max_gap: int = 15
) -> None:
    """Clear section dividers from ``lit`` in place: straight 1–3 px lines, ``min_len`` long.

    A divider brushing a heading or an object would glue them together. Only pixels with
    the sheet's own ``black`` ``clear`` px to both sides count as hairline -- a gold trim
    on a dark statue has dark, not black, beside it -- and only long runs of them, so a
    statue's staff (thin, but shorter) stays. Dividers are often dashed, so breaks up to
    ``max_gap`` are bridged before measuring.
    """
    from scipy import ndimage

    def dark_at(dy: int, dx: int) -> np.ndarray:
        out = np.ones_like(black)
        h, w = black.shape
        src = black[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)]
        out[max(0, -dy):h + min(0, -dy), max(0, -dx):w + min(0, -dx)] = src
        return out

    thin_v = lit & dark_at(0, clear) & dark_at(0, -clear)
    thin_h = lit & dark_at(clear, 0) & dark_at(-clear, 0)
    bridge_v = np.ones((max_gap, 1), dtype=bool)
    bridge_h = np.ones((1, max_gap), dtype=bool)
    thin_v = ndimage.binary_closing(thin_v, structure=bridge_v)
    thin_h = ndimage.binary_closing(thin_h, structure=bridge_h)
    lines = ndimage.binary_opening(thin_v, structure=np.ones((min_len, 1), dtype=bool))
    lines |= ndimage.binary_opening(thin_h, structure=np.ones((1, min_len), dtype=bool))
    lit[ndimage.binary_dilation(lines, iterations=1) & lit] = False


def _erase_text_and_rules(
    lit: np.ndarray, black: np.ndarray, text_h: int, letter_gap: int
) -> None:
    """Clear headings, captions and rules from ``lit`` in place.

    Done before objects are grouped, because a heading sitting a few pixels above a
    statue's ears would otherwise join it. Letters are joined sideways only, so a word
    becomes one flat strip while a column of art stays tall.
    """
    from scipy import ndimage

    _erase_long_hairlines(lit, black, min_len=max(60, round(min(lit.shape) * 0.15)))
    sideways = np.ones((1, 2 * letter_gap + 1), dtype=bool)
    labels, _ = ndimage.label(ndimage.binary_dilation(lit, structure=sideways))
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        own = (labels[sl] == idx) & lit[sl]
        ys, xs = np.nonzero(own)
        if len(xs) == 0:
            continue
        w = int(xs.max() - xs.min()) + 1
        h = int(ys.max() - ys.min()) + 1
        if _is_text_or_rule(w, h, text_h):
            lit[sl][own] = False


def _reading_order(boxes: list[tuple[int, int, int, int]]) -> list[int]:
    """Indices of boxes in rows top-to-bottom, left-to-right within a row."""
    order = sorted(range(len(boxes)), key=lambda i: (boxes[i][1] + boxes[i][3]) / 2)
    rows: list[list[int]] = []
    row_bottom = -1
    for i in order:
        cy = (boxes[i][1] + boxes[i][3]) / 2
        if not rows or cy > row_bottom:
            rows.append([])
            row_bottom = boxes[i][3]
        rows[-1].append(i)
    return [i for row in rows for i in sorted(row, key=lambda j: boxes[j][0])]


def find_objects(
    image: Image.Image,
    *,
    prefix: str = "obj",
    black_thr: float = 26.0,
    join_px: int = 3,
    letter_gap: int = 6,
    min_area: int = 120,
    pad: int = 3,
    background: tuple | None = None,
) -> list[FoundObject]:
    """Find each separate object on a flat prop sheet: black, or any one colour.

    AI prop sheets are not grids: sections of different sizes, headings, captions under
    the art. So instead of gutters, take everything that differs from the sheet's colour,
    drop the text and divider lines, grow the rest by ``join_px`` so a flame and its torch
    (or a banner and its pole) count as one, and keep each connected piece bigger than a
    spark. ``background`` is read off the sheet's border when not given.
    """
    from scipy import ndimage

    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    if background is None:
        background = sheet_background(rgb)
    brightest = distance_from(rgb, background)
    # Most of a sheet is background; "concept" sheets have a textured near-black, not 0.
    sheet_black = float(np.median(brightest))
    black_thr = max(black_thr, sheet_black + 14.0)
    lit = brightest > black_thr
    h_img, w_img = lit.shape
    text_h = max(18, round(h_img * 0.02))
    _erase_text_and_rules(lit, brightest < sheet_black + 8.0, text_h, letter_gap)
    grown = ndimage.binary_dilation(lit, iterations=join_px) if join_px > 0 else lit
    labels, _ = ndimage.label(grown)

    kept: list[tuple[tuple[int, int, int, int], np.ndarray]] = []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        own = (labels[sl] == idx) & lit[sl]
        area = int(own.sum())
        if area < min_area:
            continue
        ys, xs = np.nonzero(own)
        y0, y1 = sl[0].start + int(ys.min()), sl[0].start + int(ys.max()) + 1
        x0, x1 = sl[1].start + int(xs.min()), sl[1].start + int(xs.max()) + 1
        if _is_text_or_rule(x1 - x0, y1 - y0, text_h):
            continue
        box = (max(0, x0 - pad), max(0, y0 - pad), min(w_img, x1 + pad), min(h_img, y1 + pad))
        # Holes included: a dark body inside a bright outline is still this object's own.
        region = ndimage.binary_fill_holes(labels[box[1]:box[3], box[0]:box[2]] == idx)
        kept.append((box, region))

    found: list[FoundObject] = []
    for n, i in enumerate(_reading_order([b for b, _ in kept])):
        box, region = kept[i]
        found.append(FoundObject(Cell(name=f"{prefix}_{n:02d}", box=box), region, black_thr,
                                 tuple(background)))
    return found


def cut_cells(image: Image.Image, cells: Sequence[Cell]) -> list[tuple[Cell, Image.Image]]:
    rgb = image.convert("RGBA")
    return [(cell, rgb.crop(cell.box)) for cell in cells]


def save_debug_overlay(
    image: Image.Image, cells: Sequence[Cell], path: Path, *, labels: bool = False
) -> None:
    from PIL import ImageDraw

    vis = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(vis)
    for cell in cells:
        draw.rectangle(
            [cell.box[0], cell.box[1], cell.box[2] - 1, cell.box[3] - 1],
            outline=(0, 255, 80, 255),
            width=2,
        )
        if labels:
            draw.text((cell.box[0] + 3, cell.box[1] + 2), cell.name, fill=(255, 255, 255, 255),
                      stroke_width=2, stroke_fill=(0, 0, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    vis.save(path)
