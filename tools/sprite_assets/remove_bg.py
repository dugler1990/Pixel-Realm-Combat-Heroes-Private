"""Matte painted stone-floor backgrounds out of effect frames."""
from __future__ import annotations

import numpy as np
from PIL import Image


def _border_samples(rgb: np.ndarray, border: int = 6) -> np.ndarray:
    """Collect edge pixels as floor samples (skip very bright label glyphs)."""
    h, w, _ = rgb.shape
    b = max(1, min(border, h // 6, w // 6))
    strips = [
        rgb[:b, :, :],
        rgb[-b:, :, :],
        rgb[:, :b, :],
        rgb[:, -b:, :],
    ]
    samples = np.concatenate([s.reshape(-1, 3) for s in strips], axis=0)
    lum = samples.mean(axis=1)
    # Drop white frame numbers / labels that sit on the border.
    keep = lum < 160
    if keep.sum() < 32:
        return samples
    return samples[keep]


def _hot_mask(rgb: np.ndarray) -> np.ndarray:
    """Fire, glow, purple sigil cores — keep even if near floor luminance."""
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    # Warm fire / lava — require real chroma so lit grey-brown floor fails.
    warm = (r > 85) & (r > g + 8) & (r > b + 18) & (sat > 0.28) & (mx > 100)
    # Magenta / purple targeting tip
    purple = (r > 70) & (b > 70) & (g < r * 0.85) & (g < b * 0.95) & (sat > 0.22)
    # Hot white / cyan cores (impact flash)
    white = (mx > 210) & (sat < 0.35) & (mx > mn + 5)
    cyan = (b > 140) & (g > 120) & (r < g) & (sat > 0.12)
    return warm | purple | white | cyan


def _smoke_mask(rgb: np.ndarray, floor_lum: float) -> np.ndarray:
    """Grey smoke / debris brighter or cooler than the floor."""
    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)
    lum = (r + g + b) / 3.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    # Cooler / brighter grey than typical stone, low saturation.
    # Keep delta large so warm-lit floor tiles do not qualify as smoke.
    return (sat < 0.14) & (lum > floor_lum + 28) & (lum > 45) & (lum < 200)


def _scrub_labels(rgb: np.ndarray, alpha: np.ndarray) -> None:
    """Zero bright glyph pixels (frame numbers / variant captions)."""
    h, w = alpha.shape
    lum = rgb.mean(axis=2)
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    # Near-white, low-sat text.
    glyph = (lum > 155) & (sat < 0.22)
    # Only scrub near edges where labels live (top strip + bottom caption band).
    band = np.zeros((h, w), dtype=bool)
    band[: max(22, h // 8), : max(36, w // 5)] = True  # top-left number
    band[: max(18, h // 10), :] = True  # top numbers across
    band[h - max(28, h // 7) :, :] = True  # bottom captions
    alpha[glyph & band] = 0


def _drop_orphan_crumbs(alpha: np.ndarray, min_neighbors: int = 2) -> None:
    """Kill lone semi-opaque crumbs left from floor texture."""
    a = alpha > 20
    # 4-neighbor count via shifts
    n = np.zeros_like(a, dtype=np.uint8)
    n[1:, :] += a[:-1, :]
    n[:-1, :] += a[1:, :]
    n[:, 1:] += a[:, :-1]
    n[:, :-1] += a[:, 1:]
    weak = (alpha > 0) & (alpha < 140) & (n < min_neighbors)
    alpha[weak] = 0


def matte_stone_floor(
    image: Image.Image,
    *,
    dist_thr: float = 32.0,
    soft: float = 12.0,
    border: int = 6,
    erode_floor: int = 0,
) -> Image.Image:
    """Make stone-floor pixels transparent; keep fire / glow / smoke.

    Strategy:
    - Sample floor colors from the cell border.
    - Pixels close to those samples become transparent (soft falloff).
    - Hot / purple / white effect pixels are forced opaque.
    - Bright low-sat smoke above floor luminance is kept.
    """
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    samples = _border_samples(rgb, border=border)
    if len(samples) == 0:
        return Image.fromarray(rgba, "RGBA")

    # Distance to nearest floor sample (chunked for speed on large cells).
    # Subsample floor colors.
    if len(samples) > 256:
        idx = np.linspace(0, len(samples) - 1, 256).astype(np.int32)
        samples = samples[idx]
    samples_f = samples.astype(np.float32)

    flat = rgb.reshape(-1, 3)
    # Chunked min distance
    chunk = 8192
    dist = np.empty(flat.shape[0], dtype=np.float32)
    for i0 in range(0, flat.shape[0], chunk):
        block = flat[i0 : i0 + chunk]
        # (n,1,3) - (1,m,3) -> (n,m)
        d2 = ((block[:, None, :] - samples_f[None, :, :]) ** 2).sum(axis=2)
        dist[i0 : i0 + chunk] = np.sqrt(d2.min(axis=1))
    dist = dist.reshape(rgb.shape[:2])

    floor_lum = float(samples_f.mean())
    hot = _hot_mask(rgb)
    smoke = _smoke_mask(rgb, floor_lum)

    # Soft alpha from distance: close to floor → transparent.
    # alpha = 0 at dist<=dist_thr, 255 at dist>=dist_thr+soft
    t = (dist - dist_thr) / max(soft, 1e-3)
    t = np.clip(t, 0.0, 1.0)
    alpha = (t * 255.0).astype(np.float32)
    # Lit floor often sits mid-distance; only force-keep true effect pixels.
    alpha[hot | smoke] = 255.0
    # Anything still close to floor and not hot/smoke → kill harder.
    near_floor = dist < (dist_thr + soft * 0.35)
    alpha[near_floor & ~(hot | smoke)] = 0.0

    _scrub_labels(rgb, alpha)
    _drop_orphan_crumbs(alpha)

    rgba[:, :, 3] = alpha.astype(np.uint8)
    if erode_floor > 0:
        # Optional: shrink opaque region slightly — reserved for stubborn crumbs.
        pass
    return Image.fromarray(rgba, "RGBA")


def matte_black_bg(
    image: Image.Image,
    *,
    black_thr: float = 14.0,
    soft: float = 18.0,
) -> Image.Image:
    """Make near-black pixels transparent; keep fire, glow, smoke, scorched ground.

    Tuned for sheets authored on solid black (not stone-floor concept art).
    Dark smoke near black is fragile — keep a soft floor so mid-grey smoke survives.
    """
    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    lum = rgb.mean(axis=2)
    hot = _hot_mask(rgb)
    # Mid/dark greys that are still above pure black — smoke + char.
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    smoke_or_char = (sat < 0.22) & (lum > black_thr) & (lum < 210)

    t = (lum - black_thr) / max(soft, 1e-3)
    t = np.clip(t, 0.0, 1.0)
    alpha = (t * 255.0).astype(np.float32)
    alpha[hot | smoke_or_char] = np.maximum(alpha[hot | smoke_or_char], 220.0)
    alpha[lum <= black_thr * 0.6] = 0.0

    _scrub_labels(rgb, alpha)
    _drop_orphan_crumbs(alpha)

    rgba[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def _see_through_holes(
    core: np.ndarray, brightest: np.ndarray, black_level: float, open_px: int
) -> np.ndarray:
    """The holes in ``core`` where the sheet shows through: big and mostly black.

    The gap between a hanging brazier's chains, between a statue and its staff. A small
    or not-black hole is a crevice or a shadow in the art (a carving's recess, a dark
    robe), and left open it shows as a speck of floor.
    """
    from scipy import ndimage

    holes, count = ndimage.label(ndimage.binary_fill_holes(core) & ~core)
    if count == 0:
        return np.zeros_like(core)
    index = np.arange(1, count + 1)
    black_share = np.asarray(ndimage.mean(brightest < black_level, holes, index=index))
    area = np.asarray(ndimage.sum(np.ones_like(core), holes, index=index))
    return np.concatenate([[False], (black_share >= 0.5) & (area >= open_px)])[holes]


def _drop_specks(mask: np.ndarray, min_px: int) -> np.ndarray:
    """``mask`` without islands smaller than ``min_px`` (JPEG noise round the edge)."""
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = np.asarray(ndimage.sum(mask, labels, index=np.arange(1, count + 1)))
    return np.concatenate([[False], sizes >= min_px])[labels]


def _flame_glow(rgb: np.ndarray, brightest: np.ndarray, glow_thr: float, reach: int) -> np.ndarray:
    """The dim haze and smoke around fire: below ``glow_thr``, within ``reach`` of a
    flame, open to the outside, and not below the fire — haze rises, while the dark
    bowl or bracket under a flame is part of the object."""
    from scipy import ndimage

    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    # Fire is orange; gold is yellower. A gilded lid has a few orange-ish glints (well
    # under 1% of the crop), a torch has a flame (2-4%).
    orange = (r > 200) & (g < 0.72 * r) & (b < 0.35 * r)
    if orange.mean() < 0.012:
        return np.zeros_like(orange)
    fire = ndimage.binary_opening(orange, iterations=1)
    if not fire.any():
        fire = orange
    dim = brightest < glow_thr
    labels, _ = ndimage.label(dim)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    outside = np.isin(labels, border[border > 0])
    near = ndimage.binary_dilation(fire, iterations=reach)
    near[int(np.nonzero(fire.any(axis=1))[0].max()) + 1:] = False
    return outside & near


def _decontaminate(rgb: np.ndarray, solid: np.ndarray, background: np.ndarray,
                   band: int = 2) -> tuple:
    """(rgb, alpha) for the rim of ``solid`` with the sheet's colour taken back out of it.

    An object drawn on a coloured sheet is blended with that colour along its outline, and
    cut with a hard edge that blend is a pink fringe. Each rim pixel is read as a mix of the
    object's colour just inside it and the sheet's: its colour becomes the object's, and how
    much of the object it held becomes its alpha.
    """
    from scipy import ndimage

    alpha = solid.astype(np.float32)
    inner = ndimage.binary_erosion(solid, iterations=band)
    if not inner.any():
        return rgb, alpha
    rim = solid & ~inner
    _distance, (iy, ix) = ndimage.distance_transform_edt(~inner, return_indices=True)
    ys, xs = np.nonzero(rim)
    fg = rgb[iy[ys, xs], ix[ys, xs]]
    span = fg - background
    mix = ((rgb[ys, xs] - background) * span).sum(axis=1) / np.maximum((span * span).sum(axis=1), 1.0)
    out = rgb.copy()
    out[ys, xs] = fg
    alpha[ys, xs] = np.clip(mix, 0.0, 1.0)
    return out, alpha


def matte_object(
    image: Image.Image,
    region: np.ndarray,
    *,
    black_thr: float = 26.0,
    glow_thr: float = 64.0,
    glow_reach: int = 40,
    close_px: int = 2,
    speck_px: int = 12,
    edge_blur: float = 0.0,
    background: tuple = (0, 0, 0),
) -> Image.Image:
    """Cut one object (a crop from ``find_objects``) off its flat sheet, with a hard edge.

    ``region`` is the object's own pixels, so a neighbour poking into the crop is dropped.
    Everything further than ``black_thr`` from the sheet's colour is solid; dark nicks up to
    ``2 * close_px`` wide along the outline are closed, small enclosed holes are filled and
    loose specks dropped, because art on black is dark at its own edges and shadows, and
    cutting by brightness alone leaves the floor showing through. ``edge_blur`` decides the
    edge on blurred brightness, which smooths the hairy outline JPEG noise makes in the soft
    dark shadow round AI art -- but it also eats into near-black bodies (a black cat statue),
    so it is off by default. Only the haze around a flame fades with brightness, with the
    sheet's colour taken back out of it so it leaves no halo. On a coloured sheet the
    outline is decontaminated the same way (`_decontaminate`).
    """
    from scipy import ndimage

    from tools.sprite_assets.cut_sheet import distance_from

    rgba = np.asarray(image.convert("RGBA")).copy()
    rgb = rgba[:, :, :3].astype(np.float32)
    background = tuple(background)
    sheet = np.asarray(background, dtype=np.float32)
    brightest = distance_from(rgb, background)
    glow_thr = max(glow_thr, black_thr * 1.5)
    smooth = ndimage.gaussian_filter(brightest, edge_blur) if edge_blur > 0 else brightest
    lit = (smooth > black_thr) & region
    # Decided before closing, which would chop a chain gap into small sealed pieces.
    open_px = max(60, round(0.01 * lit.sum()))
    see_through = _see_through_holes(lit, brightest, black_thr * 0.5, open_px)
    solid = lit
    if close_px > 0:
        padded = np.pad(solid, close_px)
        solid = ndimage.binary_closing(padded, iterations=close_px)[
            close_px:-close_px, close_px:-close_px] & region
    solid = ndimage.binary_fill_holes(_drop_specks(solid, speck_px)) & ~see_through
    if any(background):
        # Nothing is drawn in a coloured sheet's colour, so a hole that colour is a hole,
        # however small. (On black, a small dark hole is a crevice in the art, and is kept.)
        solid &= brightest > black_thr
    glow = _flame_glow(rgb, brightest, glow_thr, glow_reach) & region
    solid &= ~glow
    floor = black_thr * 0.4
    haze = np.clip((brightest - floor) / (glow_thr - floor), 0.0, 1.0)
    alpha = np.where(solid, 1.0, np.where(glow, haze, 0.0))
    if any(background):
        rgb, edge = _decontaminate(rgb, solid, sheet)
        alpha = np.where(solid, edge, alpha)
        # The rim already carries the object's own colour; only the haze is un-blended.
        fading = glow & (alpha > 0.0) & (alpha < 1.0)
    else:
        fading = (alpha > 0.0) & (alpha < 1.0)
    a = alpha[fading, None]
    rgb[fading] = np.clip((rgb[fading] - (1.0 - a) * sheet) / a, 0.0, 255.0)
    rgba[:, :, :3] = rgb.round().astype(np.uint8)
    rgba[:, :, 3] = (alpha * 255.0).round().astype(np.uint8)
    return Image.fromarray(rgba)


def trim_box(image: Image.Image, pad: int = 2) -> tuple[int, int, int, int]:
    """The crop `trim_transparent` takes: the visible pixels' box, `pad` wider."""
    arr = np.asarray(image.convert("RGBA"))
    a = arr[:, :, 3]
    ys, xs = np.nonzero(a > 8)
    if len(xs) == 0:
        return (0, 0, arr.shape[1], arr.shape[0])
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    return (max(0, x0 - pad), max(0, y0 - pad),
            min(arr.shape[1], x1 + pad), min(arr.shape[0], y1 + pad))


def trim_transparent(image: Image.Image, pad: int = 2) -> Image.Image:
    return image.crop(trim_box(image, pad))
