"""The Legion look in the game: the painted kit sized for the window, and what is built from it.

The design is ui_preview/index.html (Legion), laid out on an 860-px-tall stage: Kit.px turns its
pixels into the window's. The art is in Graphics/UI, made by ui_preview/make_kit.py, with the
measured numbers in Graphics/UI/kit/kit.json.

Everything here is made once and kept for the run. Pictures load through
ImageCache.load_smooth; panels, bars, meters, labels and rain built from them are kept with
ImageCache.keep_frames. A screen blits them with draw(), so a frame makes no surface
(Code/NOTES_performance.md). Kept surfaces up to 512 px a side batch in the GPU atlas; bigger
ones keep a resident texture under their id, which is safe because kept surfaces never die.
Text that changes lives in a TextSlot: one surface per place on screen.
"""

import json
import math
import os
import random

import pygame

from ImageCache import ImageCache

_GRAPHICS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Graphics")
KIT = os.path.join(_GRAPHICS, "UI", "kit") + os.sep
BACKDROPS = os.path.join(_GRAPHICS, "UI", "backdrops") + os.sep
FONT_DIR = os.path.join(_GRAPHICS, "Font") + os.sep
DESIGN_HEIGHT = 860  # the preview's stage, in its pixels

GOLD = (240, 212, 138)
TEXT = (244, 234, 212)
TEXT_ON = (255, 248, 220)
MUTED = (213, 203, 184)
RED = (232, 96, 84)

FONT_FILES = {
    "display": "Cinzel-SemiBold.ttf",
    "body": "Outfit-Regular.ttf",
    "medium": "Outfit-Medium.ttf",
    "numbers": "Joystix.ttf",
}

RAIN_SLANT = math.radians(8)  # drops lean like the preview's rotated rain layer
GLINT_PERIOD = 3.4            # s between highlights running along a selected bar
GLINT_SWEEP = 0.4             # share of the period the highlight is moving

_KITS = {}


def kit_for(backend):
    """The kit for this window's size, made the first time it is asked for."""
    size = tuple(backend.get_size())
    kit = _KITS.get(size)
    if kit is None:
        kit = _KITS[size] = Kit(size)
    return kit


def draw(backend, surface, pos):
    """Blit a kept surface: from the atlas when it fits, else from a texture kept under its id."""
    backend.blit(surface, (round(pos[0]), round(pos[1])), cache_key=id(surface))


def now():
    return pygame.time.get_ticks() / 1000.0


def _keep(key, build):
    """The kept frame list under `key`, built the first time."""
    kept = ImageCache.frames(key)
    if kept is None:
        kept = ImageCache.keep_frames(key, build())
    return kept


def render_text(font, text, colour, spacing=0, shadow=True):
    """Text as one surface: letters spread `spacing` px apart, under the preview's hard shadow
    (two black copies, 1 and 2 steps below)."""
    if spacing and len(text) > 1:
        glyphs = [font.render(ch, True, colour) for ch in text]
        width = sum(g.get_width() for g in glyphs) + spacing * (len(glyphs) - 1)
        face = pygame.Surface((max(1, width), font.get_height()), pygame.SRCALPHA)
        x = 0
        for glyph in glyphs:
            face.blit(glyph, (x, 0))
            x += glyph.get_width() + spacing
    else:
        face = font.render(text or " ", True, colour)
    if not shadow:
        return face
    step = max(1, round(font.get_height() / 16))
    shade = face.copy()
    shade.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MIN)
    out = pygame.Surface((face.get_width(), face.get_height() + 2 * step), pygame.SRCALPHA)
    out.blit(shade, (0, 2 * step))
    out.blit(shade, (0, step))
    out.blit(face, (0, 0))
    return out


def cover(picture, size):
    """`picture` smoothly scaled to cover `size` and cropped to it about its centre."""
    w, h = size
    pw, ph = picture.get_size()
    s = max(w / pw, h / ph)
    scaled = pygame.transform.smoothscale(picture, (max(w, math.ceil(pw * s)), max(h, math.ceil(ph * s))))
    x, y = (scaled.get_width() - w) // 2, (scaled.get_height() - h) // 2
    return scaled.subsurface((x, y, w, h)).copy()


def nine_slice(dest, source, slice_px, corner, centre=False):
    """Draw `source` over all of `dest` 9-sliced: corners `slice_px` square in the source shown
    `corner` px square, edges stretched along their length, the centre only when asked."""
    width, height = dest.get_size()
    sw, sh = source.get_size()
    corner = min(corner, width // 2, height // 2)
    cols = ((0, slice_px, 0, corner),
            (slice_px, sw - 2 * slice_px, corner, width - 2 * corner),
            (sw - slice_px, slice_px, width - corner, corner))
    rows = ((0, slice_px, 0, corner),
            (slice_px, sh - 2 * slice_px, corner, height - 2 * corner),
            (sh - slice_px, slice_px, height - corner, corner))
    for i, (sx, sww, dx, dw) in enumerate(cols):
        for j, (sy, shh, dy, dh) in enumerate(rows):
            if (i == 1 and j == 1 and not centre) or dw <= 0 or dh <= 0:
                continue
            piece = source.subsurface((sx, sy, sww, shh))
            dest.blit(pygame.transform.smoothscale(piece, (dw, dh)), (dx, dy))


def _gradient_alpha(size, alpha_at, colour=(0, 0, 0)):
    """A `colour` surface whose alpha is alpha_at(x, y), both in 0..1, built small and smoothed up."""
    w, h = size
    sw, sh = max(2, w // 8), max(2, h // 8)
    small = pygame.Surface((sw, sh), pygame.SRCALPHA)
    for y in range(sh):
        for x in range(sw):
            a = alpha_at(x / (sw - 1), y / (sh - 1))
            small.set_at((x, y), (*colour, max(0, min(255, round(255 * a)))))
    return pygame.transform.smoothscale(small, (w, h))


def _strengths(surface, levels=6):
    """Copies of `surface` at rising strength, so a fade picks a kept copy per frame."""
    out = []
    for level in range(1, levels + 1):
        copy = surface.copy()
        copy.fill((255, 255, 255, round(255 * level / levels)), special_flags=pygame.BLEND_RGBA_MULT)
        out.append(copy)
    return out


def _pick(frames, strength):
    """The kept copy for a strength in 0..1, or None when it is too faint to draw."""
    i = round(max(0.0, min(1.0, strength)) * len(frames)) - 1
    return frames[i] if i >= 0 else None


class Kit:
    """The kit at one window size. Every kept key carries the size, so another window builds
    its own pieces."""

    def __init__(self, size):
        self.size = self.width, self.height = size
        self.u = self.height / DESIGN_HEIGHT
        with open(KIT + "kit.json", encoding="utf-8") as f:
            self.numbers = json.load(f)
        self.tag = ("legion", size)
        self._fonts = {}

    def px(self, n):
        """The preview's `n` px at this window's size."""
        return max(1, round(n * self.u))

    def font(self, role, size):
        pt = max(12, round(size * self.u))
        key = (role, pt)
        f = self._fonts.get(key)
        if f is None:
            f = self._fonts[key] = pygame.font.Font(FONT_DIR + FONT_FILES[role], pt)
        return f

    def label(self, text, role, size, colour=TEXT, spacing=0.0, upper=False, shadow=True):
        """Fixed text, kept: a title, a menu option. `spacing` is in ems, as in the preview's CSS.
        Only for strings that don't change; changing text goes in a TextSlot."""
        if upper:
            text = text.upper()
        key = self.tag + ("label", text, role, size, colour, spacing, shadow)

        def build():
            font = self.font(role, size)
            return [render_text(font, text, colour, round(spacing * font.get_height()), shadow)]
        return _keep(key, build)[0]

    def lines(self, text, role, size, colour, width, **kw):
        """Fixed text wrapped at word breaks to fit `width` px: a list of kept labels."""
        font = self.font(role, size)
        step = round(kw.get("spacing", 0.0) * font.get_height())

        def wide(s):
            return font.size(s.upper() if kw.get("upper") else s)[0] + step * max(0, len(s) - 1)
        rows, current = [], ""
        for word in text.split():
            trial = (current + " " + word).strip()
            if current and wide(trial) > width:
                rows.append(current)
                current = word
            else:
                current = trial
        rows.append(current)
        return [self.label(row, role, size, colour, **kw) for row in rows]

    def rule(self, width):
        """A thin gold line between stat rows."""
        def build():
            line = pygame.Surface((max(1, width), 1), pygame.SRCALPHA)
            line.fill((*GOLD, 72))
            return [line]
        return _keep(self.tag + ("rule", width), build)[0]

    def picture(self, name, height=None, width=None):
        """A kit picture smoothly scaled to a height or a width, keeping its shape."""
        path = KIT + name
        bw, bh = ImageCache.load_image(path).get_size()
        if height is not None:
            size = (max(1, round(bw * height / bh)), max(1, round(height)))
        else:
            size = (max(1, round(width)), max(1, round(bh * width / bw)))
        return ImageCache.load_smooth(path, size)

    def backdrop(self, name):
        """A backdrop painting covering the window: (surface, top-left)."""
        path = BACKDROPS + name
        bw, bh = ImageCache.load_image(path).get_size()
        s = max(self.width / bw, self.height / bh)
        size = (math.ceil(bw * s), math.ceil(bh * s))
        return ImageCache.load_smooth(path, size), ((self.width - size[0]) // 2, (self.height - size[1]) // 2)

    def shade(self, kind):
        """A kept full-window darkening: "left" behind the start menu's column, "dim" under an
        overlay, "death" red, "vignette" round the edges."""
        def build():
            w, h = self.size
            if kind == "left":
                def a(x, y):
                    return 0.74 - 0.56 * x / 0.36 if x < 0.36 else max(0.0, 0.18 * (1 - (x - 0.36) / 0.28))
                return [_gradient_alpha(self.size, a)]
            if kind == "vignette":
                def a(x, y):
                    edge = min(x, 1 - x, (y * h / w), ((1 - y) * h / w))
                    return 0.72 * max(0.0, 1 - edge / 0.09) ** 2
                return [_gradient_alpha(self.size, a)]
            surf = pygame.Surface(self.size, pygame.SRCALPHA)
            surf.fill({"dim": (0, 0, 0, 105), "death": (60, 0, 0, 102)}[kind])
            return [surf]
        return _keep(self.tag + ("shade", kind), build)[0]

    # -- panels and slots ----------------------------------------------------------------

    def panel(self, w, h, frame=44):
        """The iron frame 9-sliced round the slab's stone, `frame` preview px at the corners. The
        stone starts at the frame's plain edge, so the corners overlap it."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            corner = self.px(frame)
            edge = round(corner * self.numbers["frame-edge"])
            inner = pygame.Rect(edge, edge, w - 2 * edge, h - 2 * edge)
            out.blit(cover(ImageCache.load_image(KIT + "stone.png"), inner.size), inner)
            dark = pygame.Surface(inner.size, pygame.SRCALPHA)
            dark.fill((0, 0, 0, 82))
            out.blit(dark, inner)
            nine_slice(out, ImageCache.load_image(KIT + "frame.png"), self.numbers["frame-slice"], corner)
            return [out]
        return _keep(self.tag + ("panel", w, h, frame), build)[0]

    def covered(self, path, w, h):
        """Any picture cropped to cover w x h, kept: a level card."""
        return _keep(self.tag + ("covered", path, w, h), lambda: [cover(ImageCache.load_image(path), (w, h))])[0]

    def caption_shade(self, w, h):
        """The dark fade under a card's caption, along its bottom."""
        def build():
            return [_gradient_alpha((w, h), lambda x, y: 0.78 * max(0.0, (y - 0.55) / 0.45))]
        return _keep(self.tag + ("caption", w, h), build)[0]

    def pool(self, w, h):
        """A pool of warm light for a hero to stand in."""
        def build():
            return [_gradient_alpha((w, h), lambda x, y: 0.3 * max(0.0, 1 - math.hypot(2 * x - 1, (y - 0.8) / 0.4)),
                                    (255, 190, 110))]
        return _keep(self.tag + ("pool", w, h), build)[0]

    def socket(self, w, h):
        """A body slot on the doll: the slot frame's iron edge round a faint dark well, so the
        painted figure shows through."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            out.fill((4, 5, 8, 76))
            nine_slice(out, ImageCache.load_image(KIT + "slot.jpg"), self.numbers["slot-slice"], self.px(9))
            return [out]
        return _keep(self.tag + ("socket", w, h), build)[0]

    def fitted(self, surface, w, h, key):
        """`surface` (an item or attack picture) fitted inside w x h keeping its shape, kept under
        `key` (its path, or its id when it lives as long as the screen)."""
        def build():
            sw, sh = surface.get_size()
            s = min(w / sw, h / sh)
            return [pygame.transform.smoothscale(surface.convert_alpha(), (max(1, round(sw * s)), max(1, round(sh * s))))]
        return _keep(self.tag + ("fitted", key, w, h), build)[0]

    def faint(self, name, height):
        """A kit picture at half strength: the sigil in an empty helmet slot."""
        def build():
            pic = self.picture(name, height=height).copy()
            pic.fill((255, 255, 255, 128), special_flags=pygame.BLEND_RGBA_MULT)
            return [pic]
        return _keep(self.tag + ("faint", name, height), build)[0]

    def dimmer(self, w, h):
        """Grey shade over a locked slot."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            out.fill((40, 40, 40, 160))
            return [out]
        return _keep(self.tag + ("dimmer", w, h), build)[0]

    def fit_glow(self, w, h):
        """Inside a slot the held item fits: a faint gold wash and a thin gold edge (the cursor's highlight
        is the wider glow round it)."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            out.fill((*GOLD, 70))
            pygame.draw.rect(out, (*GOLD, 255), (0, 0, w, h), max(2, self.px(3)))
            return [out]
        return _keep(self.tag + ("fit_glow", w, h), build)[0]

    def faded(self, w, h):
        """Over a slot the held item does not fit: darker, still readable."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            out.fill((0, 0, 0, 150))
            return [out]
        return _keep(self.tag + ("faded", w, h), build)[0]

    def highlight(self, w, h):
        """A gold edge and glow round a chosen card, `glow` px wider on each side."""
        glow = self.px(10)

        def build():
            out = pygame.Surface((w + 2 * glow, h + 2 * glow), pygame.SRCALPHA)
            for i in range(glow, 0, -1):
                a = round(110 * (1 - i / glow) ** 2)
                pygame.draw.rect(out, (*GOLD, a), (glow - i, glow - i, w + 2 * i, h + 2 * i), 1)
            pygame.draw.rect(out, (*GOLD, 220), (glow - 2, glow - 2, w + 4, h + 4), 2)
            return [out]
        return _keep(self.tag + ("highlight", w, h), build)[0], glow

    def plaque(self, w, h):
        """A text field: a small copy of the frame round a sunken dark well."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            corner = self.px(18)
            edge = round(corner * self.numbers["frame-edge"])
            well = pygame.Rect(edge, edge, w - 2 * edge, h - 2 * edge)
            out.fill((0, 0, 0, 158), well)
            shadow = _gradient_alpha(well.size, lambda x, y: 0.8 * max(0.0, 1 - y / 0.3))
            out.blit(shadow, well)
            nine_slice(out, ImageCache.load_image(KIT + "frame.png"), self.numbers["frame-slice"], corner)
            return [out]
        return _keep(self.tag + ("plaque", w, h), build)[0]

    def frame_over(self, w, h, frame=26):
        """The frame alone, to lay over a picture (a level card, the map)."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            nine_slice(out, ImageCache.load_image(KIT + "frame.png"), self.numbers["frame-slice"], self.px(frame))
            return [out]
        return _keep(self.tag + ("frame", w, h, frame), build)[0]

    def slot(self, w, h):
        """The iron slot frame with its dark well, 9-sliced at 9 preview px like the preview's."""
        def build():
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            nine_slice(out, ImageCache.load_image(KIT + "slot.jpg"), self.numbers["slot-slice"],
                       self.px(9), centre=True)
            return [out]
        return _keep(self.tag + ("slot", w, h), build)[0]

    # -- bars ------------------------------------------------------------------------------

    def bar_cap(self, h, selected=False):
        """How wide a bar's end cap is at height h."""
        return self.picture(("bar_on" if selected else "bar") + "_l.png", height=h).get_width()

    def bar(self, w, h, selected=False):
        """A steel bar: its two caps at their own shape and the centre repeated between them; the
        gold one, with the sigil on its cap, when selected."""
        def build():
            stem = "bar_on" if selected else "bar"
            left = self.picture(stem + "_l.png", height=h)
            right = self.picture(stem + "_r.png", height=h)
            centre = self.picture(stem + "_c.png", height=h)
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            x, end = left.get_width(), w - right.get_width()
            while x < end:
                out.blit(centre, (x, 0), pygame.Rect(0, 0, min(centre.get_width(), end - x), h))
                x += centre.get_width()
            out.blit(left, (0, 0))
            out.blit(right, (end, 0))
            return [out]
        return _keep(self.tag + ("bar", w, h, selected), build)[0]

    def glint(self, w, h):
        """The light that runs along a selected bar, kept at six strengths so it can fade in and
        out without changing a surface."""
        def build():
            inner = w - 2 * self.bar_cap(h, True)
            band_w, band_h = max(8, int(inner * 0.36)), max(2, round(h * 0.86))
            row = pygame.Surface((band_w, 1), pygame.SRCALPHA)
            for x in range(band_w):
                a = 1 - abs(2 * x / max(1, band_w - 1) - 1)
                row.set_at((x, 0), (255, 240, 200, round(255 * 0.42 * a)))
            band = pygame.transform.scale(row, (band_w, band_h))
            frames = []
            for level in range(1, 7):
                f = band.copy()
                f.fill((255, 255, 255, round(255 * level / 6)), special_flags=pygame.BLEND_RGBA_MULT)
                frames.append(f)
            return frames
        return _keep(self.tag + ("glint", w, h), build)

    def icon(self, key, size):
        """A stat icon (health, energy, attack, magic, speed, strength, vitality, agility,
        charisma, exp) fitted in a `size` preview-px square."""
        side = self.px(size)
        base = ImageCache.load_image(f"{KIT}icon_{key}.png")
        if base.get_height() >= base.get_width():
            return self.picture(f"icon_{key}.png", height=side)
        return self.picture(f"icon_{key}.png", width=side)

    def head(self, painting, size):
        """The top of a full-length painting cut square: a roster card's face."""
        def build():
            pic = self.picture(painting, width=size)
            return [pic.subsurface((0, 0, size, min(size, pic.get_height()))).copy()]
        return _keep(self.tag + ("head", painting, size), build)[0]

    def draw_bar(self, backend, rect, label=None, selected=False, value=None, pressed=False, t=None, extra=()):
        """A bar with its label left and an optional value right, the light running along it
        when selected, and 2 preview px lower while pressed. `extra` is more content as
        (surface, (x, y)) from the left of the bar's inside and its top."""
        x, y = rect.x, rect.y + (self.px(2) if pressed else 0)
        draw(backend, self.bar(rect.w, rect.h, selected), (x, y))
        cap, pad = self.bar_cap(rect.h, selected), self.px(10)
        if label is not None:
            draw(backend, label, (x + cap + pad, y + (rect.h - label.get_height()) // 2))
        for surface, (ex, ey) in extra:
            draw(backend, surface, (x + cap + pad + ex, y + ey))
        if value is not None:
            draw(backend, value, (x + rect.w - cap - pad - value.get_width(), y + (rect.h - value.get_height()) // 2))
        if selected:
            frames = self.glint(rect.w, rect.h)
            p = (((now() if t is None else t) - 0.2) % GLINT_PERIOD) / (GLINT_PERIOD * GLINT_SWEEP)
            if p < 1:
                band = frames[0]
                inner = rect.w - 2 * cap
                eased = p * p * (3 - 2 * p)
                strength = min(1.0, p / 0.18, (1 - p) / 0.18)
                f = frames[max(0, min(5, round(strength * 6) - 1))]
                draw(backend, f, (x + cap + eased * (inner - band.get_width()), y + (rect.h - band.get_height()) // 2))


class Meter:
    """A painted meter: the iron trough and the fill sitting in its measured opening. The trough
    and each fill width are kept, cut the first time that width is drawn, so a frame blits two
    kept surfaces and never uses area=."""

    ZOOM = {"fill_gold.png": 4.0, "fill_energy.png": 2.0, "fill_blood.png": 1.0}

    def __init__(self, kit, w, h, fill):
        self.kit, self.w, self.h = kit, w, h
        left = kit.picture("gauge_l.png", height=h)
        right = kit.picture("gauge_r.png", height=h)
        self.cap = left.get_width()
        self.inner = max(1, w - left.get_width() - right.get_width())
        self.top = round(h * kit.numbers["gauge-in-top"])
        self.opening = max(1, h - self.top - round(h * kit.numbers["gauge-in-bottom"]))

        def trough():
            centre = kit.picture("gauge_c.png", height=h)
            out = pygame.Surface((w, h), pygame.SRCALPHA)
            x, end = left.get_width(), w - right.get_width()
            while x < end:
                out.blit(centre, (x, 0), pygame.Rect(0, 0, min(centre.get_width(), end - x), h))
                x += centre.get_width()
            out.blit(left, (0, 0))
            out.blit(right, (end, 0))
            return [out]
        self.trough = _keep(kit.tag + ("meter", w, h), trough)[0]

        zoom = self.ZOOM.get(fill, 1.0)

        def full():
            tile = kit.picture(fill, height=max(1, round(self.opening * zoom)))
            out = pygame.Surface((self.inner, self.opening), pygame.SRCALPHA)
            dy = (tile.get_height() - self.opening) // 2
            x = 0
            while x < self.inner:
                out.blit(tile, (x, -dy))
                x += tile.get_width()
            return [out]
        self.full = _keep(kit.tag + ("meter-fill", fill, self.inner, self.opening), full)[0]
        self._piece_key = kit.tag + ("meter-piece", fill, self.inner, self.opening)

    def _piece(self, px):
        return _keep(self._piece_key + (px,), lambda: [self.full.subsurface((0, 0, px, self.opening)).copy()])[0]

    def draw(self, backend, pos, ratio):
        px = max(0, min(self.inner, round(self.inner * ratio)))
        if px:
            draw(backend, self._piece(px), (pos[0] + self.cap, pos[1] + self.top))
        draw(backend, self.trough, pos)


class TextSlot:
    """One place on screen whose text changes: re-rendered only when the text does, the old
    surface's texture dropped first (as UI.show_exp does)."""

    def __init__(self, backend, kit, role, size, colour=TEXT, spacing=0.0, shadow=True, upper=False):
        self.backend, self.kit = backend, kit
        self.role, self.size, self.colour = role, size, colour
        self.spacing, self.shadow, self.upper = spacing, shadow, upper
        self._text = None
        self._surface = None

    def surface(self, text):
        if self.upper:
            text = text.upper()
        if text != self._text or self._surface is None:
            if self._surface is not None:
                self.backend.invalidate_texture(self._surface)
            font = self.kit.font(self.role, self.size)
            self._surface = render_text(font, text, self.colour, round(self.spacing * font.get_height()), self.shadow)
            self._text = text
        return self._surface

    def draw(self, text, pos, anchor="topleft"):
        surface = self.surface(text)
        rect = surface.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
        self.backend.blit(surface, rect.topleft, cache_key=id(surface))
        return rect


# -- scenes and rain -----------------------------------------------------------------------

def _rain_tile(w, h, count, length, width, colour, opacity, soft, seed):
    """Slanted drops on a tile that repeats both ways. Soft ones are drawn at twice the size and
    smoothed down, which blurs them like the preview's far rain."""
    k = 2 if soft else 1
    tile = pygame.Surface((w * k, h * k), pygame.SRCALPHA)
    rng = random.Random(seed)
    sx, sy = -math.sin(RAIN_SLANT), math.cos(RAIN_SLANT)
    for _ in range(count):
        x, y = rng.random() * w * k, rng.random() * h * k
        length_k = length * k * (0.6 + rng.random() * 0.8)
        alpha = round(255 * opacity * (0.35 + rng.random() * 0.65))
        for ox in (-w * k, 0, w * k):
            for oy in (-h * k, 0, h * k):
                pygame.draw.line(tile, (*colour, alpha), (x + ox, y + oy),
                                 (x + ox + sx * length_k, y + oy + sy * length_k), max(1, round(width * k)))
    return pygame.transform.smoothscale(tile, (w, h)) if soft else tile


class Rain:
    """Rain in a painting, under everything drawn after it: a soft far layer, a few sharp drops
    near, and drops lit warm round each torch."""

    FPS = 30
    TORCH_FRAMES = 10

    def __init__(self, kit, painting, torches):
        self.kit = kit
        self.far = _keep(kit.tag + ("rain", "far"), lambda: [_rain_tile(
            kit.px(180), kit.px(360), 60, kit.px(16), 1, (190, 206, 222), 0.6, True, 7)])[0]
        self.near = _keep(kit.tag + ("rain", "near"), lambda: [_rain_tile(
            kit.px(420), kit.px(640), 8, kit.px(52), max(1, kit.u * 1.3), (228, 236, 244), 1.0, False, 11)])[0]
        self.far_speed = 379 * kit.u    # preview px per second, as in the preview
        self.near_speed = 1524 * kit.u
        self.torches = [self._torch(painting, x, y, i) for i, (x, y) in enumerate(torches)]

    def _layer(self, backend, tile, speed, t):
        tw, th = tile.get_size()
        travel = speed * t
        ox = (-math.sin(RAIN_SLANT) * travel) % tw
        oy = (math.cos(RAIN_SLANT) * travel) % th
        w, h = self.kit.size
        y = oy - th
        while y < h:
            x = ox - tw
            while x < w:
                draw(backend, tile, (x, y))
                x += tw
            y += th

    def _torch(self, painting, xp, yp, index):
        """Drops lit by a torch at (xp, yp) % of the painting: a short loop of frames, each a box
        of warm drops with a soft oval edge baked in."""
        bw, bh = round(painting.w * 0.22), round(painting.h * 0.48)
        at = (round(painting.x + painting.w * xp / 100 - bw / 2), round(painting.y + painting.h * yp / 100 - bh / 2))
        kit = self.kit

        def build():
            mask = _gradient_alpha((bw, bh), lambda x, y: _oval(x, y))
            mask.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGBA_MAX)  # white, keep alpha
            rng = random.Random(100 + index)
            drops = [(rng.random() * bw, rng.random() * bh, kit.px(14 + rng.random() * 40), rng.random())
                     for _ in range(18)]
            sx, sy = -math.sin(RAIN_SLANT), math.cos(RAIN_SLANT)
            frames = []
            for f in range(self.TORCH_FRAMES):
                s = pygame.Surface((bw, bh), pygame.SRCALPHA)
                shift = f / self.TORCH_FRAMES * bh
                for x, y, length, r in drops:
                    yy = (y + shift) % bh
                    xx = (x + sx * shift) % bw
                    colour = (255, 150, 60, 255) if r > 0.4 else (255, 140, 50, 190)
                    width = 2 if r > 0.75 else 1
                    for oy in (-bh, 0):
                        pygame.draw.line(s, colour, (xx, yy + oy), (xx + sx * length, yy + oy + sy * length), width)
                s.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                frames.append(s)
            return frames
        return _keep(kit.tag + ("torch", index, bw, bh, at), build), at

    def draw(self, backend, t):
        self._layer(backend, self.far, self.far_speed, t)
        self._layer(backend, self.near, self.near_speed, t)
        frame = int(t * self.FPS)
        for frames, at in self.torches:
            draw(backend, frames[frame % len(frames)], at)


def _oval(x, y):
    """Alpha of the torch light's oval at (x, y) in 0..1 of its box: full in the middle, 0.6 at
    35 % of the way out, nothing at the edge (the preview's radial mask)."""
    r = math.hypot(2 * x - 1, 2 * y - 1)
    if r < 0.35:
        return 1 - 0.4 * r / 0.35
    return max(0.0, 0.6 * (1 - (r - 0.35) / 0.65))


class Scene:
    """A backdrop painting covering the window, with rain when it is outdoors."""

    def __init__(self, kit, backdrop, rain=False, torches=()):
        self.kit = kit
        self.picture, self.at = kit.backdrop(backdrop)
        painting = self.picture.get_rect(topleft=self.at)
        self.rain = Rain(kit, painting, torches) if rain else None

    def draw(self, backend, t=None):
        draw(backend, self.picture, self.at)
        if self.rain:
            self.rain.draw(backend, now() if t is None else t)


# The gate painting's torches: two flames and the reflection under the left one, measured from
# the painting (ui_preview/PROCESS_ui_kit.md).
GATE_TORCHES = ((51, 56), (84, 54), (51, 80))


class Dais:
    """A hero standing on the shrine's dais in the light shaft, and stepping into it when picked:
    out of the dark, smaller and lower, up into the light over 1.1 s (the preview's step-in).
    The step is eight kept frames, so nothing is scaled per frame."""

    STEP, DELAY, FRAMES = 1.1, 0.3, 8

    def __init__(self, kit, scene):
        self.kit = kit
        painting = scene.picture.get_rect(topleft=scene.at)
        # Measured on the shrine painting: the dais's top at 79 % down, the shaft at 50 % across.
        self.feet = (painting.centerx, painting.y + round(painting.h * 0.79))
        self.height = round(painting.h * 0.52)
        self.picked_at = now()

    def pick(self):
        self.picked_at = now()

    def _frames(self, name):
        kit, height = self.kit, self.height

        def build():
            figure = kit.picture(name, height=height)
            frames = []
            for k in range(self.FRAMES):
                t = k / self.FRAMES
                e = 1 - (1 - t) ** 3
                scale = 0.88 + 0.12 * e
                size = (max(1, round(figure.get_width() * scale)), max(1, round(height * scale)))
                f = pygame.transform.smoothscale(figure, size)
                light = round(255 * (0.12 + 0.88 * e))
                f.fill((light, light, light, round(255 * min(1.0, t / 0.45))), special_flags=pygame.BLEND_RGBA_MULT)
                frames.append((f, round((1 - e) * 0.04 * height)))
            frames.append((figure, 0))
            return frames
        return _keep(kit.tag + ("dais", name, height), build)

    def _floor(self, width):
        def build():
            w, h = round(width * 1.24), max(2, round(self.height * 0.06))
            return [_gradient_alpha((w, h), lambda x, y: 0.8 * max(0.0, 1 - math.hypot(2 * x - 1, 2 * y - 1)))]
        return _keep(self.kit.tag + ("dais-floor", width), build)[0]

    def draw(self, backend, name):
        t = now() - self.picked_at - self.DELAY
        if t < 0:
            return
        frames = self._frames(name)
        k = min(len(frames) - 1, int(t / self.STEP * self.FRAMES))
        figure, drop = frames[k]
        if k == len(frames) - 1:
            floor = self._floor(figure.get_width())
            draw(backend, floor, (self.feet[0] - floor.get_width() / 2, self.feet[1] - floor.get_height() / 2))
        draw(backend, figure, (self.feet[0] - figure.get_width() / 2, self.feet[1] - figure.get_height() + drop))


def _fit(size, box, cover):
    """A rect of `size`'s shape centred on `box`: inside it, or covering it."""
    s = (max if cover else min)(box.w / size[0], box.h / size[1])
    r = pygame.Rect(0, 0, round(size[0] * s), round(size[1] * s))
    r.center = box.center
    return r


class Grow:
    """The chosen level's picture growing from its card until it covers the window (0.75 s),
    then held there while the level is built. It keeps its own shape all the way, from inside
    the card to covering the window. On the GPU backend blit_scaled with a cache key stretches
    a kept texture; the CPU backend smooth-scales it for those 0.75 s."""

    TIME = 0.75

    def __init__(self, kit, picture, card):
        self.kit, self.picture = kit, picture
        self.start = _fit(picture.get_size(), pygame.Rect(card), cover=False)
        self.end = _fit(picture.get_size(), pygame.Rect((0, 0), kit.size), cover=True)
        self.t0 = now()

    @property
    def done(self):
        return now() - self.t0 >= self.TIME

    def draw(self, backend):
        p = min(1.0, (now() - self.t0) / self.TIME)
        e = 1 - (1 - p) ** 3
        a, b = self.start, self.end
        r = pygame.Rect(round(a.x + (b.x - a.x) * e), round(a.y + (b.y - a.y) * e),
                        round(a.w + (b.w - a.w) * e), round(a.h + (b.h - a.h) * e))
        backend.blit_scaled(self.picture, r, cache_key=id(self.picture))


class Gate:
    """The painted gate between screens: when leaving the start menu, and after death.

    It closes over the old screen, which Main2 draws with no input (`behind`); slams, with a
    shudder, dust off the seam and the seal on its leaves kindling; runs the switch's heavy work
    (`at_slam`, such as building a level) while shut; holds; and opens over the new screen.
    Main2 calls update() and draw() every frame and passes no input while it is busy.
    """

    CLOSE, HOLD, OPEN = 0.86, 0.48, 1.05
    SHUDDER, DUST = 0.42, 0.9

    def __init__(self, backend):
        self.backend = backend
        self.kit = kit_for(backend)
        self.behind = None
        self.at_slam = None
        self.t0 = None      # closing began
        self.t_shut = None  # the leaves met and the switch's work was done

    @property
    def busy(self):
        return self.t0 is not None

    @property
    def closing(self):
        return self.busy and self.t_shut is None

    def start(self, behind, at_slam=None):
        """Close over `behind`, a call that draws the old screen. False if a gate is running."""
        if self.busy:
            return False
        self.behind, self.at_slam = behind, at_slam
        self.t0, self.t_shut = now(), None
        return True

    def update(self):
        if not self.busy:
            return
        if self.t_shut is None:
            if now() - self.t0 >= self.CLOSE:
                work, self.behind, self.at_slam = self.at_slam, None, None
                if work is not None:
                    work()
                self.t_shut = now()  # the hold starts once the work is done
        elif now() - self.t_shut >= self.HOLD + self.OPEN:
            self.t0 = self.t_shut = None

    # -- the pieces, kept --------------------------------------------------------------------

    def _leaves(self):
        kit = self.kit
        half = (kit.width + 1) // 2

        def leaf(name, keep_right):
            def build():
                src = ImageCache.load_image(KIT + name)
                sw, sh = src.get_size()
                s = max(half / sw, kit.height / sh)
                scaled = pygame.transform.smoothscale(src, (max(half, math.ceil(sw * s)), max(kit.height, math.ceil(sh * s))))
                # Keep the seam edge, so the seal's halves meet in the middle of the window.
                x = scaled.get_width() - half if keep_right else 0
                y = (scaled.get_height() - kit.height) // 2
                return [scaled.subsurface((x, y, half, kit.height)).copy()]
            return _keep(kit.tag + ("gate", name), build)[0]
        return leaf("gate_l.png", True), leaf("gate_r.png", False)

    def _glow(self):
        d = round(self.kit.height * 0.46)

        def build():
            def a(x, y):
                r = math.hypot(2 * x - 1, 2 * y - 1)
                return 0.6 * (1 - r / 0.42) + 0.18 * (r / 0.42) if r < 0.42 else max(0.0, 0.18 * (1 - (r - 0.42) / 0.26))
            return _strengths(_gradient_alpha((d, d), a, (255, 196, 110)))
        return _keep(self.kit.tag + ("gate-glow",), build)

    def _dust(self):
        kit = self.kit
        w, h = round(kit.width * 0.6), round(kit.height * 0.45)

        def build():
            def a(x, y):
                floor = max(0.0, 1 - math.hypot((x - 0.5) / 0.5, (1 - y) / 0.4)) * 0.55
                seam = max(0.0, 1 - abs(x - 0.5) / 0.03) * 0.35 * y
                return min(1.0, floor + seam)
            cloud = _gradient_alpha((w, h), a, (150, 138, 118))
            frames = []
            for i in range(8):  # grows and fades, as the preview's dust
                k = i / 7
                s = 0.6 + 0.9 * k
                size = (max(1, round(w * s)), max(1, round(h * s)))
                strength = min(1.0, k / 0.15) if k < 0.15 else 1 - (k - 0.15) / 0.85
                frame = pygame.transform.smoothscale(cloud, size)
                frame.fill((255, 255, 255, round(255 * max(0.0, strength))), special_flags=pygame.BLEND_RGBA_MULT)
                frames.append(frame)
            return frames
        return _keep(kit.tag + ("gate-dust",), build)

    def _seam(self):
        kit = self.kit
        w = kit.px(48)

        def build():
            def a(x, y):
                d = abs(2 * x - 1)
                return 0.95 if d < 0.05 else 0.55 * max(0.0, 1 - d) ** 2
            return _strengths(_gradient_alpha((w, kit.height), a, (255, 220, 160)))
        return _keep(kit.tag + ("gate-seam",), build)

    def _shudder(self, k):
        """Vertical shake after the slam: down 6, up 3, down 1 preview px, settling."""
        points = ((0.0, 0), (0.18, 6), (0.4, -3), (0.65, 1), (1.0, 0))
        for (k0, y0), (k1, y1) in zip(points, points[1:]):
            if k <= k1:
                return self.kit.u * (y0 + (y1 - y0) * (k - k0) / (k1 - k0))
        return 0

    def draw(self):
        if not self.busy:
            return
        backend, kit = self.backend, self.kit
        left, right = self._leaves()
        half = left.get_width()
        t, dy = now(), 0.0
        if self.t_shut is None:
            p = min(1.0, (t - self.t0) / self.CLOSE) ** 2.6  # gathering speed, as a heavy door
            off = (1 - p) * half * 1.05
        else:
            since = t - self.t_shut
            if since < self.SHUDDER:
                dy = self._shudder(since / self.SHUDDER)
            q = min(1.0, max(0.0, since - self.HOLD) / self.OPEN)
            off = (1 - (1 - q) ** 3.5) * half * 1.05
        draw(backend, left, (-off, dy))
        draw(backend, right, (kit.width - half + off, dy))
        if self.t_shut is None:
            return
        since = t - self.t_shut
        if since < self.DUST:
            dust = self._dust()
            frame = dust[min(len(dust) - 1, int(since / self.DUST * len(dust)))]
            draw(backend, frame, (kit.width / 2 - frame.get_width() / 2, kit.height - frame.get_height() + dy))
        # The seal kindles, holds, and goes as the leaves part.
        kindle = min(1.0, since / 0.175) if since < 0.175 else 1 - 0.25 * min(1.0, (since - 0.175) / 0.325)
        if since > self.HOLD:
            kindle *= max(0.0, 1 - (since - self.HOLD) / 0.25)
        glow = _pick(self._glow(), kindle)
        if glow is not None:
            draw(backend, glow, (kit.width / 2 - glow.get_width() / 2, kit.height / 2 - glow.get_height() / 2 + dy))
        # Light shows at the seam just before they part, and goes with the left leaf's edge.
        if since < self.HOLD:
            light = max(0.0, (since / self.HOLD - 0.55) / 0.45)
        else:
            light = max(0.0, 1 - (since - self.HOLD) / 0.5)
        strip = _pick(self._seam(), light)
        if strip is not None:
            draw(backend, strip, (half - off - strip.get_width() / 2, dy))
