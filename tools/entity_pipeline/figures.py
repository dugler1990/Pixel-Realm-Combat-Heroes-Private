"""Cut a light idle sheet into one clean sprite per warrior.

A parchment sheet has no black gutters, so the figures are the dark regions on the
sheet colour. The caption under each figure is a short strip of small pieces with a
row of background between it and the body. Black-gap sheets still use the existing
gutter cutter.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from tools.sprite_assets.cut_sheet import (
    cells_from_boxes,
    cells_from_grid,
    cut_cells,
    detect_gutter_grid,
    sheet_background,
)
from tools.sprite_assets.cut_sheet import distance_from
from tools.sprite_assets.pack_sequence import write_contact_sheet
from tools.sprite_assets.remove_bg import matte_black_bg, trim_transparent

# How far a hand-drawn cell sits outside the figure. The Necron boxes match at this pad.
CELL_PAD = 5
# A found box is the same cell when every edge is this close to the hand box.
BOX_TOLERANCE_PX = 12


@dataclass
class Figure:
    name: str
    box: tuple[int, int, int, int]
    caption: str


def _parchment_colour(rgb: np.ndarray) -> np.ndarray:
    """The sheet colour, from the light flat pixels inside the border."""
    h, w = rgb.shape[:2]
    y0, y1 = h // 10, h - h // 10
    x0, x1 = w // 10, w - w // 10
    inset = rgb[y0:y1, x0:x1]
    lum = inset.mean(axis=2)
    mx = inset.max(axis=2)
    mn = inset.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    samples = inset[(lum > 160) & (sat < 0.4)]
    if len(samples) < 64:
        return np.median(inset.reshape(-1, 3), axis=0)
    return np.median(samples, axis=0)


def is_light_sheet(image: Image.Image) -> bool:
    """Parchment (or any light flat sheet), rather than a black-gap sheet."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    inset = rgb[h // 10: h - h // 10, w // 10: w - w // 10]
    return float(np.median(inset)) > 140


def _components(rgb: np.ndarray, colour: np.ndarray) -> list[dict]:
    from scipy import ndimage

    dist = np.abs(rgb - colour).max(axis=2)
    content = dist > 28
    h, w = content.shape
    rim = max(12, min(h, w) // 64)
    content[:rim, :] = False
    content[-rim:, :] = False
    content[:, :rim] = False
    content[:, -rim:] = False
    labels, _count = ndimage.label(content)
    found = []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        own = labels[sl] == idx
        area = int(own.sum())
        if area < 80:
            continue
        ys, xs = np.nonzero(own)
        box = (
            sl[1].start + int(xs.min()),
            sl[0].start + int(ys.min()),
            sl[1].start + int(xs.max()) + 1,
            sl[0].start + int(ys.max()) + 1,
        )
        bw, bh = box[2] - box[0], box[3] - box[1]
        # The decorative frame and the footer are one piece that spans the sheet.
        if bw > w * 0.55 or bh > h * 0.45:
            continue
        found.append({"box": box, "area": area, "w": bw, "h": bh})
    return found


def _overlaps_x(body: tuple[int, int, int, int], scrap: tuple[int, int, int, int]) -> bool:
    x0 = max(body[0] - 40, scrap[0])
    x1 = min(body[2] + 40, scrap[2])
    return x1 - x0 >= min(12, scrap[2] - scrap[0])


def _read_caption(crop: Image.Image) -> str | None:
    """The caption text, when a reader is available. Otherwise None."""
    try:
        import pytesseract
    except ImportError:
        return None
    try:
        text = pytesseract.image_to_string(crop, config="--psm 7")
    except Exception:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or None


def find_light_figures(image: Image.Image) -> list[Figure]:
    """One figure per warrior, box including the caption strip under it."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    colour = _parchment_colour(rgb)
    comps = _components(rgb, colour)
    min_area = max(800, int(0.003 * h * w))
    min_h = max(40, int(0.05 * h))
    bodies = [c for c in comps if c["h"] >= min_h and c["area"] >= min_area]
    scraps = [c for c in comps if c not in bodies and c["h"] <= max(18, int(0.025 * h))]
    bodies.sort(key=lambda c: (c["box"][1], c["box"][0]))

    claimed: set[int] = set()
    figures: list[tuple[tuple[int, int, int, int], Image.Image | None]] = []
    for body in bodies:
        box = body["box"]
        attached = []
        for i, scrap in enumerate(scraps):
            if i in claimed:
                continue
            sb = scrap["box"]
            if sb[1] < box[3] - 4 or sb[1] > box[3] + 48:
                continue
            if not _overlaps_x(box, sb):
                continue
            attached.append(i)
        for i in attached:
            claimed.add(i)
        x0 = max(0, box[0] - CELL_PAD)
        y0 = max(0, box[1] - CELL_PAD)
        x1 = min(w, box[2] + CELL_PAD)
        bottom = box[3]
        caption_crop = None
        if attached:
            pieces = [scraps[i]["box"] for i in attached]
            bottom = max(p[3] for p in pieces)
            cx0 = min(p[0] for p in pieces)
            cy0 = min(p[1] for p in pieces)
            cx1 = max(p[2] for p in pieces)
            cy1 = max(p[3] for p in pieces)
            caption_crop = image.crop((cx0, cy0, cx1, cy1))
        y1 = min(h, bottom + CELL_PAD)
        figures.append(((x0, y0, x1, y1), caption_crop))

    from tools.sprite_assets.cut_sheet import _reading_order

    order = _reading_order([box for box, _ in figures])
    named: list[Figure] = []
    used: set[str] = set()
    for n, i in enumerate(order):
        box, caption = figures[i]
        slug = _read_caption(caption) if caption is not None else None
        name = slug or f"warrior_{n:02d}"
        base = name
        k = 2
        while name in used:
            name = f"{base}_{k}"
            k += 1
        used.add(name)
        named.append(Figure(name=name, box=box, caption=slug or ""))
    return named


def _clear_caption(crop: Image.Image, colour: np.ndarray) -> Image.Image:
    """Drop the caption strip under the body. The body is the large dark region."""
    from scipy import ndimage

    rgba = np.asarray(crop.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    dist = np.abs(rgb - colour).max(axis=2)
    content = dist > 28
    labels, _count = ndimage.label(content)
    h, w = content.shape
    bodies = []
    scraps = []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        own = labels[sl] == idx
        area = int(own.sum())
        if area < 40:
            continue
        ys, xs = np.nonzero(own)
        box = (
            sl[1].start + int(xs.min()),
            sl[0].start + int(ys.min()),
            sl[1].start + int(xs.max()) + 1,
            sl[0].start + int(ys.max()) + 1,
        )
        bh = box[3] - box[1]
        if bh >= h * 0.25 and area >= 0.02 * h * w:
            bodies.append((area, box))
        elif bh <= max(18, int(0.08 * h)):
            scraps.append((idx, box, own, sl))
    if not bodies:
        return Image.fromarray(rgba, "RGBA")
    body = max(bodies, key=lambda item: item[0])[1]
    for idx, box, own, sl in scraps:
        if box[1] < body[3] - 4:
            continue
        if not _overlaps_x(body, box):
            continue
        rgba[sl][own, 3] = 0
    return Image.fromarray(rgba, "RGBA")


def _drop_caption_crumbs(image: Image.Image) -> Image.Image:
    """Remove a short leftover underline. A detached weapon is taller and stays."""
    from scipy import ndimage

    rgba = np.asarray(image.convert("RGBA")).copy()
    opaque = rgba[:, :, 3] > 16
    labels, count = ndimage.label(opaque)
    if count <= 1:
        return Image.fromarray(rgba, "RGBA")
    sizes = np.asarray(ndimage.sum(np.ones_like(opaque), labels, index=np.arange(1, count + 1)))
    main = int(np.argmax(sizes)) + 1
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None or idx == main:
            continue
        height = sl[0].stop - sl[0].start
        area = int(sizes[idx - 1])
        if height <= 16 and area < 400:
            rgba[labels == idx, 3] = 0
    return Image.fromarray(rgba, "RGBA")


def matte_parchment(image: Image.Image, colour: tuple[int, int, int] | np.ndarray) -> Image.Image:
    """Make the sheet colour transparent, the way matte_black_bg keys on black."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    dist = distance_from(rgb, tuple(int(round(v)) for v in colour))
    # The caption underline is only a little darker than the sheet. The figure's
    # own paint sits much further away, so this threshold takes the line with the sheet.
    thr, soft = 52.0, 12.0
    t = np.clip((dist - thr) / soft, 0.0, 1.0)
    keyed = (t * 255.0).astype(np.float32)
    # Keep whatever alpha the caption crop already cleared.
    rgba[:, :, 3] = np.minimum(rgba[:, :, 3].astype(np.float32), keyed).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def cut_sheet(image: Image.Image, out_dir: Path) -> list[Figure]:
    """Write layout.json, crop with the existing cutter, and save clean cells.

    ``out_dir`` receives layout.json, contact.png, and cells/<name>.png.
    """
    out_dir = Path(out_dir)
    cells_dir = out_dir / "cells"
    cells_dir.mkdir(parents=True, exist_ok=True)

    if is_light_sheet(image):
        figures = find_light_figures(image)
        if not figures:
            raise RuntimeError("no figures found on the light sheet")
        layout = {"named_boxes": [[fig.name, list(fig.box)] for fig in figures]}
        (out_dir / "layout.json").write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
        cells = cells_from_boxes((fig.name, fig.box) for fig in figures)
        cropped = cut_cells(image, cells)
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
        colour = _parchment_colour(rgb)
        clean = []
        for (cell, crop), fig in zip(cropped, figures):
            sprite = _clear_caption(crop, colour)
            sprite = matte_parchment(sprite, colour)
            sprite = _drop_caption_crumbs(sprite)
            sprite = trim_transparent(sprite)
            sprite.save(cells_dir / f"{cell.name}.png")
            clean.append(sprite)
        write_contact_sheet(clean, out_dir / "contact.png", cols=min(4, len(clean)), cell=160)
        return figures

    rows, cols = detect_gutter_grid(image)
    cells = cells_from_grid(rows, cols)
    if not cells:
        raise RuntimeError("no black-gap cells found")
    layout = {
        "row_spans": [list(span) for span in rows],
        "col_spans": [list(span) for span in cols],
    }
    (out_dir / "layout.json").write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    cropped = cut_cells(image, cells)
    colour = sheet_background(np.asarray(image.convert("RGB"), dtype=np.float32))
    clean = []
    figures = []
    for i, (cell, crop) in enumerate(cropped):
        if max(colour) < 60:
            sprite = matte_black_bg(crop)
        else:
            sprite = matte_parchment(crop, colour)
        sprite = trim_transparent(sprite)
        name = f"warrior_{i:02d}"
        sprite.save(cells_dir / f"{name}.png")
        clean.append(sprite)
        figures.append(Figure(name=name, box=cell.box, caption=""))
    write_contact_sheet(clean, out_dir / "contact.png", cols=min(8, len(clean)))
    return figures


def box_deltas(
    found: list[tuple[int, int, int, int]],
    hand: list[tuple[str, tuple[int, int, int, int]]],
) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Each hand box and how far the nearest found box is, edge by edge."""

    def iou(a, b) -> float:
        x0, y0 = max(a[0], b[0]), max(a[1], b[1])
        x1, y1 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0, x1 - x0) * max(0, y1 - y0)
        if inter == 0:
            return 0.0
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        return inter / (area_a + area_b - inter)

    report = []
    for name, hb in hand:
        best = max(found, key=lambda box: iou(hb, box))
        delta = tuple(abs(best[i] - hb[i]) for i in range(4))
        report.append((name, delta))
    return report
