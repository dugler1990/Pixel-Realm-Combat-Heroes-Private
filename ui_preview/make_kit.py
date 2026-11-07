"""Paint the Legion UI kit with gpt-image-2 and cut it into lossless pieces for the preview.

    python ui_preview/make_kit.py               paint every piece that has no painting yet, then cut
    python ui_preview/make_kit.py logo bar_on   repaint just these, then cut
    python ui_preview/make_kit.py --cut         re-cut the saved paintings, no API calls

Paintings go to generated/ui_kit/<piece>.png (kept out of git); the cut pieces go to
Graphics/UI/kit/, where both the game and the preview load them, with the measured numbers in
kit.json (the game) and kit.css (the preview). Every call is appended to
generated/ui_kit/calls.jsonl.
gpt-image-2 cannot paint a transparent background, so cut-out pieces are painted on flat
green and keyed here with a soft edge.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.painted_map_pipeline.openai_api import edit_image, generate_image  # noqa: E402

RAW = ROOT / "generated" / "ui_kit"
KIT = ROOT / "Graphics" / "UI" / "kit"
# The slot frame (slot.jpg) is 9-sliced 112 px in from each edge of its 1024 px square.
SLOT_SLICE = 112
CONFIG = {"model": "gpt-image-2", "quality": "high"}
ART = ROOT / "Graphics"

STYLE = (
    "Dark fantasy game interface art with the weight and finish of a classic Warcraft menu, "
    "painterly but crisp, antique and occult rather than generic medieval. "
)
GREEN = (
    " Everything around the subject is one flat, even, pure chroma green (#00FF00): "
    "no shading, gradient, texture, floor, cast shadow or glow on the green."
)

# Pieces are painted in this order; a ref that names another piece waits for its painting.
PIECES: dict[str, dict] = {
    "sigil": {
        "size": (1024, 1024),
        "prompt": STYLE + (
            "A single occult sigil, the recurring emblem of this game: one strange, ancient mark "
            "that feels wrong and very old, like a glyph cut into a temple door by a forgotten cult. "
            "Asymmetric but balanced, made of a few deliberate strokes. Not a pentagram, not a cross, "
            "not a skull, not a letter or a known rune. Inlaid antique gold in a thin bevel, slightly "
            "worn, with dark engraved grooves. Centered, filling about 70 percent of the frame, seen "
            "straight on." + GREEN
        ),
    },
    "bar": {
        "size": (2400, 800),
        "prompt": STYLE + (
            "Menu button art: one long horizontal bar of blackened forged steel, about eight times "
            "wider than it is tall, centered and spanning about 90 percent of the width. Each end has "
            "a forged end cap, slightly taller than the bar, with a beveled edge and two small dark "
            "rivets; the two caps are mirror images. Between the caps the bar is plain brushed steel "
            "with fine horizontal grain, a soft highlight along the top edge and a dark lower lip, "
            "exactly even along its whole length so it can be repeated. No text, no symbols, no gold, "
            "no gems. Straight-on front view, no perspective, lit from above." + GREEN
        ),
    },
    "bar_on": {
        "size": (2400, 800),
        "refs": ["bar", "sigil"],
        "prompt": STYLE + (
            "Image 1 is a menu button bar. Paint its selected state: the exact same shape, size, "
            "position, end caps and steel, with gold worked into the metal: a thin gilded inlay line "
            "along the top and bottom edges of the plain middle, gilded bevels on both end caps, and "
            "the mark from image 2 inlaid in gold on the face of the left end cap only. The middle "
            "stays exactly even along its length so it can be repeated. No text." + GREEN
        ),
    },
    "logo": {
        "size": (2048, 1024),
        "refs": ["sigil"],
        "prompt": STYLE + (
            "Title logo that reads exactly COMBAT HEROES on two lines, COMBAT above HEROES, in heavy "
            "carved serif capitals like letters cut into a fortress gate. The letters are cast antique "
            "gold with a deep dark cut and a bevel painted into every stroke, worn edges, a faint "
            "hammered texture and a thin dark outline; not a smooth digital gradient. The mark from "
            "image 1 sits small and centered between the two lines, in the same gold. No other text." + GREEN
        ),
    },
    "wizard": {
        "size": (1024, 1536),
        "refs": [ART / "Orange_Wizard" / "selection_screen" / "0.png"],
        "prompt": STYLE + (
            "Image 1 is the Orange Wizard, a hero of this game. Paint him again as a full-length "
            "figure, head to feet, standing upright with both feet flat and fully visible, turned "
            "three-quarters toward the viewer, holding a gnarled wooden staff. Same painted style, "
            "face, white beard, orange hat and robe. The only light on him is a narrow shaft of warm "
            "golden light from directly overhead: light on the hat brim, the shoulders and the top of "
            "the robe, his face half shadowed under the brim, the lower robe falling into darkness. "
            "No glowing orbs, no magic effects, no rim light, no other light. A small margin below the "
            "feet; nothing cut off." + GREEN
        ),
    },
    "barbarian": {
        "size": (1024, 1536),
        "refs": [
            ART / "barb" / "selection_screen" / "0.png",
            ART / "barb" / "down_idle" / "0.png",
            ART / "Orange_Wizard" / "selection_screen" / "0.png",
        ],
        "prompt": STYLE + (
            "Images 1 and 2 are the Barbarian, a hero of this game: a close-up of his face and a "
            "small sprite of his whole body. Paint him as a full-length figure in the painted style "
            "of image 3 (use image 3 only for style): head to feet, standing upright with both feet "
            "flat and fully visible, turned three-quarters toward the viewer, fists at his sides. "
            "Long red-brown hair and beard, fierce face, bare muscular chest crossed by two leather "
            "straps with brass buckles, leather kilt, leather bracers, fur-topped boots. The only "
            "light on him is a narrow shaft of warm golden light from directly overhead, the lower "
            "body falling into darkness. No rim light, no other light. A small margin below the "
            "feet; nothing cut off." + GREEN
        ),
    },
    "slab": {
        "size": (1600, 1280),
        "prompt": STYLE + (
            "Background for an inventory panel, seen straight on and filling the whole image edge to "
            "edge: one slab of dark, cold carved stone set in a frame of blackened forged iron with "
            "heavy corner brackets. Inside the frame the stone is plain, even and dark, with faint "
            "carving only near the frame, so items and a figure can be laid on top. Lit softly from "
            "above. No niches, no slots, no grid, no text, no symbols."
        ),
    },
    "items": {
        "size": (1024, 1024),
        "prompt": STYLE + (
            "Four small inventory item icons in one consistent painted style, in a 2 by 2 grid, each "
            "centered in its own quarter with wide empty space between them: top left a rolled linen "
            "bandage, top right a wooden torch with an unlit pitch-soaked head, bottom left a trail "
            "ration wrapped in cloth and tied with twine, bottom right an old iron key with an ornate "
            "bow. Strong, readable silhouettes, lit from the upper left, each filling about 60 percent "
            "of its quarter. No text, no frames, no slots." + GREEN
        ),
    },
    "doll": {
        "size": (1024, 1536),
        "refs": [ART / "Orange_Wizard" / "selection_screen" / "0.png"],
        "prompt": STYLE + (
            "Image 1 is the Orange Wizard. Paint him as the equipment figure of an inventory screen: "
            "full length head to feet, facing straight toward the viewer, symmetrical stance, feet a "
            "little apart, arms held slightly away from the body with open hands at hip height, so the "
            "head, chest, belt, both hands and both feet are separate and unobstructed. No staff, no "
            "orbs, no effects. Cold rim light from behind on both sides and only a dim front light, so "
            "the silhouette glows at its edges. Same painted style, face, beard, hat and robe. A small "
            "margin below the feet; nothing cut off." + GREEN
        ),
    },
    "gate": {
        "size": (2048, 1152),
        "refs": ["sigil"],
        "prompt": STYLE + (
            "Image 1 is this game's sigil. Paint a pair of massive closed fortress gate doors seen "
            "straight on, filling the entire image edge to edge, with no wall, arch, floor or sky "
            "visible. Two tall door leaves of black oak bound with heavy forged iron bands and hinge "
            "straps, scarred and old, meeting at one perfectly straight vertical seam exactly down the "
            "center of the image. Across the seam at the center, a large round iron seal bearing the "
            "mark from image 1 in antique gold, split exactly in half by the seam. No rows of studs. "
            "Cold light from below, the tops of the doors falling into shadow. The two leaves mirror "
            "each other."
        ),
    },
    "frame": {
        "size": (1024, 1024),
        "prompt": STYLE + (
            "A square ornate panel frame seen straight on: a border of blackened forged iron about 6 "
            "percent of the image wide on every side, with a thin antique gold line along its inner "
            "edge. The four corners carry identical sculpted corner pieces, the same design rotated, a "
            "little heavier than the border. Between the corners each side is a plain straight bar, "
            "exactly the same along its whole length so it can be stretched, with no ornaments, rivets "
            "or studs along the sides. The frame reaches the edges of the image. The entire area inside "
            "the frame is flat, even, pure chroma green (#00FF00) with no shading or shadow."
        ),
    },
    "gauge": {
        "size": (2400, 800),
        "prompt": STYLE + (
            "Game interface meter: one long horizontal empty gauge, about ten times wider than it is "
            "tall, centered and spanning about 90 percent of the width. A trough of blackened forged "
            "iron with a thin antique gold inner lip, closed at each end by a small forged end cap; the "
            "two caps are mirror images. The inside of the trough is empty and is flat pure chroma "
            "green (#00FF00), exactly like the background. The trough is plain and exactly even along "
            "its length so it can be repeated. No rivets, studs, text or markings. Straight-on front "
            "view." + GREEN
        ),
    },
    "fills": {
        "size": (2048, 1024),
        "prompt": STYLE + (
            "Two horizontal bands for filling game meters, each spanning the full width of the image "
            "edge to edge, one above the other, separated by a thin black gap. The top band is glowing "
            "molten gold, like liquid light seen through glass, with slow swirls and a bright highlight "
            "along its top edge. The bottom band is the same in deep blood red with darker clots. Each "
            "band is even along its length so it can be repeated, with no ends, frames or text."
        ),
    },
    "fill_energy": {
        "size": (1536, 512),
        "prompt": STYLE + (
            "One horizontal band for filling a game meter, spanning the full width of the image edge "
            "to edge, with a thin black margin above and below it. The band is cold blue-white arcane "
            "energy, like lightning held in glass, with slow swirls and a bright highlight along its top "
            "edge, in the same painted finish as a molten-gold meter fill. Even along its length so it "
            "can be repeated, with no ends, frames or text."
        ),
    },
    "icons": {
        "size": (1920, 768),
        "prompt": STYLE + (
            "Ten small stat icons in one consistent painted style, in a grid of 5 columns and 2 rows, "
            "each centered in its own cell with wide empty space between them. Top row from left: "
            "health, a red heart-shaped crystal; energy, a blue-white flame; attack, a short sword with "
            "a notched blade; magic, an eye inside a violet orb; speed, a winged boot. Bottom row from "
            "left: strength, a clenched iron gauntlet; vitality, a green sprouting vine knot; agility, a "
            "grey feather; charisma, a gold crown; experience, a small glowing amber soul gem. Strong, "
            "readable silhouettes, lit from the upper left, each filling about 60 percent of its cell. "
            "No text, no frames." + GREEN
        ),
    },
}
ICONS = ("health", "energy", "attack", "magic", "speed", "strength", "vitality", "agility", "charisma", "exp")


def load_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        os.environ["OPENAI_API_KEY"] = winreg.QueryValueEx(key, "OPENAI_API_KEY")[0]


def ref_path(ref) -> Path:
    """A piece name means that piece's painting. Tiny sprites are enlarged so the model sees them."""
    if isinstance(ref, str):
        return RAW / f"{ref}.png"
    image = Image.open(ref)
    if max(image.size) >= 256:
        return Path(ref)
    scale = 512 // max(image.size)
    big = RAW / "refs" / f"{Path(ref).parent.parent.name}_{Path(ref).parent.name}.png"
    big.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").resize((image.width * scale, image.height * scale), Image.NEAREST).save(big)
    return big


def paint(name: str) -> None:
    piece = PIECES[name]
    width, height = piece["size"]
    out = RAW / f"{name}.png"
    started = time.time()
    if piece.get("refs"):
        info = edit_image(
            prompt=piece["prompt"], input_images=[ref_path(r) for r in piece["refs"]], mask=None,
            output_path=out, width=width, height=height, config=CONFIG,
        )
    else:
        info = generate_image(prompt=piece["prompt"], output_path=out, width=width, height=height, config=CONFIG)
    info.update(piece=name, seconds=round(time.time() - started, 1), at=time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(RAW / "calls.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(info, default=str) + "\n")
    print(f"painted {name} in {info['seconds']}s")


def key_out_green(image: Image.Image) -> Image.Image:
    """Soft chroma key: alpha from how much greener than red and blue a pixel is, then despill."""
    rgb = np.asarray(image.convert("RGB")).astype(np.float32)
    spill = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
    alpha = np.clip(1 - (spill - 40) / 100, 0, 1)
    rgb[..., 1] = np.where(spill > 0, np.maximum(rgb[..., 0], rgb[..., 2]), rgb[..., 1])
    # Specks the model left on the green: drop anything far smaller than the subject.
    solid = alpha > 0.5
    labels, count = ndimage.label(solid)
    if count > 1:
        sizes = ndimage.sum(solid, labels, index=np.arange(1, count + 1))
        for index, size in enumerate(sizes, start=1):
            if size < 0.002 * solid.size:
                alpha[labels == index] = 0
    rgba = np.dstack([rgb, alpha * 255]).round().clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def shaft_light(image: Image.Image) -> Image.Image:
    """Light a standing hero the way the shrine's shaft does: warm from above, dark at the feet."""
    rgba = np.asarray(image).astype(np.float32) / 255
    y = np.linspace(0, 1, rgba.shape[0])[:, None, None]
    shade = np.clip((y - 0.28) / 0.72, 0, 1) * 0.72
    warm = np.clip(1 - y / 0.32, 0, 1) * 0.35 * np.array([1.0, 0.78, 0.48])
    rgb = 1 - (1 - rgba[..., :3]) * (1 - warm)
    rgb = rgb * (1 - shade)
    out = np.dstack([rgb, rgba[..., 3:]]) * 255
    return Image.fromarray(out.round().clip(0, 255).astype(np.uint8), "RGBA")


def trim(image: Image.Image, pad: int = 4) -> Image.Image:
    alpha = np.asarray(image)[..., 3]
    ys, xs = np.nonzero(alpha > 8)
    box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0),
           min(xs.max() + pad + 1, image.width), min(ys.max() + pad + 1, image.height))
    return image.crop(box)


def keep(image: Image.Image, name: str) -> None:
    """Write a kit piece as a PNG, compressed as far as PNG goes without losing a pixel."""
    image.save(KIT / f"{name}.png", optimize=True)


def split_bar(bar: Image.Image, prefix: str) -> float:
    """Cut a bar into left cap, repeatable centre and right cap. Returns cap width / bar height."""
    alpha = np.asarray(bar)[..., 3] > 128
    heights = alpha.sum(axis=0).astype(float)
    width = bar.width
    middle = np.median(heights[int(width * 0.3):int(width * 0.7)])

    def cap_edge(columns) -> int:
        for x in columns:
            if abs(heights[x] - middle) > 0.04 * middle:
                return x
        return columns[-1]

    left = min(cap_edge(range(width // 2, 0, -1)) + 6, width // 3)
    right = max(cap_edge(range(width // 2, width - 1)) - 6, 2 * width // 3)
    keep(bar.crop((0, 0, left, bar.height)), f"{prefix}_l")
    keep(bar.crop((right, 0, width, bar.height)), f"{prefix}_r")
    run, fade = bar.height * 2, bar.height // 2
    start = (left + right) // 2 - run // 2
    strip = np.asarray(bar).astype(np.float32)[:, start:start + run + fade]
    keep(Image.fromarray(seamless_x(strip, fade).round().astype(np.uint8), "RGBA"), f"{prefix}_c")
    return max(left, width - right) / bar.height


def seamless_x(strip: np.ndarray, fade: int) -> np.ndarray:
    """Cross-fade a strip's last `fade` columns into its first, so it repeats left to right."""
    tile = strip[:, :strip.shape[1] - fade].copy()
    t = np.linspace(0, 1, fade)[None, :, None]
    tile[:, :fade] = strip[:, -fade:] * (1 - t) + strip[:, :fade] * t
    return tile


def band_strip(rows: np.ndarray) -> Image.Image:
    """The meter band in a painting of one, cut to its rows and made to repeat left to right."""
    # Rows of the band, by their strongest channel: a deep red band is dark in luminance, and
    # its bright top highlight would otherwise be all that passes. The longest unbroken run, so
    # a bright line in a rim around it is left out.
    glow = rows.max(axis=2).mean(axis=1)
    labels, count = ndimage.label(glow > 0.45 * np.percentile(glow, 90))
    sizes = ndimage.sum(labels > 0, labels, index=np.arange(1, count + 1))
    band = np.nonzero(labels == 1 + int(np.argmax(sizes)))[0]
    strip = rows[band.min() + 6:band.max() - 5]
    return Image.fromarray(seamless_x(strip, strip.shape[1] // 8).round().astype(np.uint8), "RGB")


def frame_slices(frame: Image.Image) -> tuple[int, float]:
    """A square frame's 9-slice: corner size in source pixels, and the plain edge's depth over it."""
    alpha = np.asarray(frame)[..., 3] > 128
    half_h, half_w = alpha.shape[0] // 2, alpha.shape[1] // 2
    sides = (alpha.T[:, :half_h], alpha.T[:, ::-1][:, :half_h], alpha[:, :half_w], alpha[:, ::-1][:, :half_w])
    corner, edges = 0, []
    for side in sides:
        # How far in the iron reaches, at every point along this side.
        depth = np.where(side.all(axis=1), side.shape[1], np.argmin(side, axis=1)).astype(float)
        n = len(depth)
        edge = float(np.median(depth[int(n * 0.35):int(n * 0.65)]))
        edges.append(edge)
        off = np.abs(depth - edge) > max(3.0, 0.15 * edge)
        # The corner piece starts where the depth leaves the plain edge's, walking out from the middle.
        for x in range(n // 2, 0, -1):
            if off[x]:
                corner = max(corner, x + 1)
                break
        for x in range(n // 2, n):
            if off[x]:
                corner = max(corner, n - x)
                break
    edge = float(np.median(edges))
    size = int(max(corner, edge)) + 4
    return size, edge / size


def cut() -> None:
    KIT.mkdir(parents=True, exist_ok=True)
    have = {name for name in PIECES if (RAW / f"{name}.png").exists()}
    css: dict[str, str] = {}

    def cutout(name: str, pad: int = 4) -> Image.Image:
        return trim(key_out_green(Image.open(RAW / f"{name}.png")), pad=pad)

    for name in ("sigil", "logo", "wizard", "barbarian", "doll"):
        if name in have:
            piece = cutout(name)
            keep(shaft_light(piece) if name in ("wizard", "barbarian") else piece, name)
    for name in ("bar", "bar_on", "gauge"):
        if name in have:
            css[f"{name.replace('_', '-')}-cap"] = f"{split_bar(cutout(name, pad=0), name):.4f}"
    if "gauge" in have:
        # The meter's opening: transparent rows between the iron rims, as shares of its height.
        solid = np.asarray(Image.open(KIT / "gauge_c.png"))[..., 3].mean(axis=1) > 128
        rows = np.nonzero(~solid)[0]
        top, bottom = np.argmax(solid), len(solid) - np.argmax(solid[::-1])
        inner = rows[(rows > top) & (rows < bottom)]
        if len(inner):
            css["gauge-in-top"] = f"{inner.min() / len(solid):.4f}"
            css["gauge-in-bottom"] = f"{1 - (inner.max() + 1) / len(solid):.4f}"
        else:
            print("gauge: no opening found inside the trough; it was painted solid")
    if "frame" in have:
        frame = cutout("frame", pad=0)
        keep(frame, "frame")
        size, edge = frame_slices(frame)
        css["frame-slice"], css["frame-edge"] = str(size), f"{edge:.4f}"
    if "slab" in have:
        slab = Image.open(RAW / "slab.png").convert("RGB")
        keep(slab, "slab")
        # Plain stone from inside the slab's carved border, the fill for every framed panel.
        keep(slab.crop((int(slab.width * 0.15), int(slab.height * 0.17),
                        int(slab.width * 0.85), int(slab.height * 0.83))), "stone")
    if "gate" in have:
        gate = Image.open(RAW / "gate.png").convert("RGB")
        lum = np.asarray(gate.convert("L")).astype(float)
        lo, hi = int(gate.width * 0.46), int(gate.width * 0.54)
        seam = lo + int(np.argmin(lum[:, lo:hi].mean(axis=0)))
        # Equal halves about the seam, so the seal's two halves meet at the same scale.
        half = min(seam, gate.width - seam)
        keep(gate.crop((seam - half, 0, seam, gate.height)), "gate_l")
        keep(gate.crop((seam, 0, seam + half, gate.height)), "gate_r")
    if "fills" in have:
        sheet = np.asarray(Image.open(RAW / "fills.png").convert("RGB")).astype(np.float32)
        h = sheet.shape[0]
        for index, name in enumerate(("fill_gold", "fill_blood")):
            keep(band_strip(sheet[index * h // 2:(index + 1) * h // 2]), name)
    if "fill_energy" in have:
        keep(band_strip(np.asarray(Image.open(RAW / "fill_energy.png").convert("RGB")).astype(np.float32)),
             "fill_energy")
    if "items" in have:
        sheet = key_out_green(Image.open(RAW / "items.png"))
        half_w, half_h = sheet.width // 2, sheet.height // 2
        for index, item in enumerate(("bandage", "torch", "ration", "key")):
            x, y = (index % 2) * half_w, (index // 2) * half_h
            keep(trim(sheet.crop((x, y, x + half_w, y + half_h))), item)
    if "icons" in have:
        sheet = key_out_green(Image.open(RAW / "icons.png"))
        cell_w, cell_h = sheet.width // 5, sheet.height // 2
        for index, name in enumerate(ICONS):
            x, y = (index % 5) * cell_w, (index // 5) * cell_h
            keep(trim(sheet.crop((x, y, x + cell_w, y + cell_h))), f"icon_{name}")
    if css:
        (KIT / "kit.css").write_text(
            "/* Written by make_kit.py from the paintings: end caps as a share of height, the meter's\n"
            "   opening as shares of its height, the frame's 9-slice in source pixels. */\n"
            ":root {\n" + "".join(f"  --{k}: {v};\n" for k, v in css.items()) + "}\n", encoding="utf-8")
        # The same numbers for the game, plus the slot frame's fixed slice.
        numbers = {k: float(v) if "." in v else int(v) for k, v in css.items()}
        numbers["slot-slice"] = SLOT_SLICE
        (KIT / "kit.json").write_text(json.dumps(numbers, indent=2) + "\n", encoding="utf-8")
    print("cut:", ", ".join(sorted(have)) or "nothing painted yet")
    print("measured:", css)


def main(args: list[str]) -> None:
    if "--cut" not in args:
        load_key()
        RAW.mkdir(parents=True, exist_ok=True)
        wanted = [a for a in args if a in PIECES] or [n for n in PIECES if not (RAW / f"{n}.png").exists()]
        unknown = [a for a in args if a not in PIECES and a != "--cut"]
        if unknown:
            raise SystemExit(f"unknown pieces: {unknown}; known: {list(PIECES)}")
        pending = list(wanted)
        while pending:
            # Paint in waves: everything whose piece refs are already painted goes together.
            ready = [n for n in pending
                     if all(not isinstance(r, str) or r not in pending for r in PIECES[n].get("refs", []))]
            with cf.ThreadPoolExecutor(max_workers=4) as pool:
                for future in [pool.submit(paint, n) for n in ready]:
                    future.result()
            pending = [n for n in pending if n not in ready]
    cut()


if __name__ == "__main__":
    main(sys.argv[1:])
