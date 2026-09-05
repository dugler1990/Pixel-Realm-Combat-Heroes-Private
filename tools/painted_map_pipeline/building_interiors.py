"""Building interiors, painted INTO the exterior rather than alongside it.

An interior generated independently of its roof cannot be composited with it. Measured on
great_pyramid: normalised cross-correlation between interior and roof over the rim is 0.040
at the best offset within +-160 px, where two renders of one building score 0.5-0.9. No
translation registers them, so every boundary between the two is a mismatch -- and the
renderer then grows machinery (chamber punches, arch quads, half-plane splits) trying to
hide a seam that cannot be hidden.

So the roof IS the input image. The chamber is the only editable region, and after every
pass the original roof is written back over everything outside it. Outside the chamber the
two files end up byte-identical, which `check_border` asserts rather than hopes for. That
leaves the engine nothing to composite: inside -> interior, outside -> roof.

gpt-image-2 will not take the full 3600x3140 canvas (11.3 MP against an 8.3 MP cap, and
3140 is not divisible by 16), so generation runs as a downscaled layout pass followed by
native-resolution tile refinements. Every pass is written to the work dir so a bad draw can
be looked at instead of guessed about.

  python -m tools.painted_map_pipeline.building_interiors \
      --map levels/Frostreach/sunspine_7x6_play/map.tmx --building great_pyramid \
      --config tools/painted_map_pipeline/openai.gpt-image-2.json

  # gate an asset that is already on disk, no API calls:
  python -m tools.painted_map_pipeline.building_interiors \
      --map levels/Frostreach/sunspine_7x6_play/map.tmx --building great_pyramid --check-only
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .image_client import make_image_client
from .openai_api import validate_size
from .world_levels.masks import rasterize_polygon

Image.MAX_IMAGE_PIXELS = None

# Largest uniform fit under gpt-image-2's 8.3 MP cap for a 3600x3140 canvas, both edges
# divisible by 16. Layout only -- the detail comes back at 1:1 in the tile pass.
LAYOUT_MAX_PIXELS = 8_300_000
EDGE_MULTIPLE = 16
TILE_HEIGHT = 1600
TILE_OVERLAP = 64


class BuildingInteriorError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildingArt:
    name: str
    origin: tuple[int, int]          # world px of the footprint bounding box
    size: tuple[int, int]
    footprint: tuple                 # canvas-local polygon
    chamber: tuple                   # canvas-local polygon
    doors: tuple                     # canvas-local polygons held out of the mask
    roof_path: Path
    interior_path: Path
    door_point: tuple = None         # canvas-local door_x/door_y, or None if unauthored


# ---------------------------------------------------------------- TMX

def _properties(obj: ET.Element) -> dict:
    return {p.get("name"): p.get("value") for p in obj.findall("properties/property")}


def _world_polygon(obj: ET.Element) -> tuple:
    """Object shape in world px. Polygon points are relative to the object's x/y."""
    ox, oy = float(obj.get("x", 0)), float(obj.get("y", 0))
    node = obj.find("polygon")
    if node is not None:
        pairs = (point.split(",") for point in node.get("points").split())
        return tuple((ox + float(px), oy + float(py)) for px, py in pairs)
    width, height = float(obj.get("width", 0)), float(obj.get("height", 0))
    if not width or not height:
        raise BuildingInteriorError(f"object {obj.get('name')!r} has neither polygon nor size")
    return ((ox, oy), (ox + width, oy), (ox + width, oy + height), (ox, oy + height))


def load_building(map_path: Path, name: str) -> BuildingArt:
    """Footprint, chamber and art paths for one building, straight out of the TMX.

    Deliberately parses the XML rather than importing the game's layout manager: that pulls
    in pygame and a display, and this runs headless in the pipeline.
    """
    root = ET.parse(map_path).getroot()
    objects = [obj for group in root.iter("objectgroup") for obj in group.findall("object")]

    building = next((o for o in objects if o.get("name") == name), None)
    if building is None:
        raise BuildingInteriorError(f"no object named {name!r} in {map_path}")
    chamber = next(
        (o for o in objects if _properties(o).get("chamber_of", "").strip() == name), None)
    if chamber is None:
        raise BuildingInteriorError(
            f"{name!r} has no chamber: expected an object carrying chamber_of={name!r}. "
            "The chamber is the editable region, so there is nothing to generate without it."
        )

    props = _properties(building)
    for key in ("roof_image", "interior_image"):
        if not props.get(key):
            raise BuildingInteriorError(f"{name!r} is missing the {key} property")

    footprint_world = _world_polygon(building)
    xs = [p[0] for p in footprint_world]
    ys = [p[1] for p in footprint_world]
    origin = (int(min(xs)), int(min(ys)))
    size = (int(round(max(xs))) - origin[0], int(round(max(ys))) - origin[1])
    to_local = lambda poly: tuple((x - origin[0], y - origin[1]) for x, y in poly)  # noqa: E731

    # The door plane's anchor, authored beside the art because the door polygon is a
    # rectangle around the arch while the plane needs a single point to project.
    door_point = None
    if props.get("door_x") and props.get("door_y"):
        door_point = (float(props["door_x"]) - origin[0], float(props["door_y"]) - origin[1])

    folder = map_path.parent
    return BuildingArt(
        name=name,
        origin=origin,
        size=size,
        footprint=to_local(footprint_world),
        chamber=to_local(_world_polygon(chamber)),
        doors=tuple(
            to_local(_world_polygon(o)) for o in objects
            if _properties(o).get("door_of", "").strip() == name
        ),
        roof_path=folder / props["roof_image"],
        interior_path=folder / props["interior_image"],
        door_point=door_point,
    )


# ---------------------------------------------------------------- masks and the gate

def build_masks(art: BuildingArt) -> tuple[np.ndarray, np.ndarray]:
    """(footprint, editable) boolean masks on the canvas.

    Editable is the chamber MINUS every `door_of` polygon. A doorway painted on the
    exterior straddles the chamber boundary -- it stands on the wall, so part of it is
    inside and part out -- and a mask that cuts through it asks the model to reinvent
    half an arch. It never does: the first run replaced the pyramid's lintel and upper
    opening with plain masonry and left the kept threshold opening into a wall. Holding
    the whole door out keeps it byte-identical in both views, and the model paints the
    corridor behind it instead of through it.
    """
    footprint = np.asarray(rasterize_polygon(art.size, art.footprint)) > 0
    chamber = np.asarray(rasterize_polygon(art.size, art.chamber)) > 0
    if not chamber.any():
        raise BuildingInteriorError(f"{art.name}: chamber polygon rasterised to nothing")
    if (chamber & ~footprint).any():
        raise BuildingInteriorError(f"{art.name}: chamber is not contained by the footprint")

    editable = chamber
    for door in art.doors:
        editable = editable & ~(np.asarray(rasterize_polygon(art.size, door)) > 0)
    if not editable.any():
        raise BuildingInteriorError(f"{art.name}: doors cover the whole chamber")
    return footprint, editable


def check_border(interior: Image.Image, roof: Image.Image, keep: np.ndarray) -> None:
    """The gate: colour outside the chamber must be the roof's own pixels, exactly.

    Byte equality, not a similarity score. A draw that drifts at the border cannot land,
    which is the whole reason this pipeline exists.
    """
    a = np.asarray(interior.convert("RGB"))[keep]
    b = np.asarray(roof.convert("RGB"))[keep]
    differing = np.any(a != b, axis=-1)
    if differing.any():
        count = int(differing.sum())
        raise BuildingInteriorError(
            f"border check failed: {count} of {keep.sum()} kept pixels "
            f"({100.0 * count / max(int(keep.sum()), 1):.2f}%) differ from the roof. "
            "The interior does not register with its exterior."
        )


def paste_back(generated: Image.Image, roof: Image.Image, editable: np.ndarray) -> Image.Image:
    """Model output inside the editable region, the untouched roof everywhere else."""
    out = np.asarray(roof.convert("RGBA")).copy()
    out[editable] = np.asarray(generated.convert("RGBA").resize(roof.size, Image.LANCZOS))[editable]
    return Image.fromarray(out, mode="RGBA")


def cut_alpha(image: Image.Image, footprint: np.ndarray) -> Image.Image:
    """Alpha 0 outside the silhouette, matching how the engine clips the roof at load."""
    out = np.asarray(image.convert("RGBA")).copy()
    out[..., 3] = np.where(footprint, 255, 0).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


# ---------------------------------------------------------------- generation

def layout_size(size: tuple[int, int]) -> tuple[int, int]:
    """Largest legal uniform downscale of `size` for a single edit call."""
    width, height = size
    scale = min(1.0, (LAYOUT_MAX_PIXELS / float(width * height)) ** 0.5)
    fit = lambda v: max(EDGE_MULTIPLE, int(v * scale) // EDGE_MULTIPLE * EDGE_MULTIPLE)  # noqa: E731
    return fit(width), fit(height)


def tile_rows(height: int) -> list[tuple[int, int]]:
    """Overlapping row bands, each a legal canvas on its own."""
    if height <= TILE_HEIGHT:
        return [(0, height // EDGE_MULTIPLE * EDGE_MULTIPLE)]
    rows, top = [], 0
    while True:
        bottom = min(top + TILE_HEIGHT, height // EDGE_MULTIPLE * EDGE_MULTIPLE)
        rows.append((top, bottom))
        if bottom >= height // EDGE_MULTIPLE * EDGE_MULTIPLE:
            return rows
        top = bottom - TILE_OVERLAP


def _mask_image(mask: np.ndarray) -> Image.Image:
    """Canonical pending mask: white means repaint. Clients flip polarity themselves."""
    return Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L")


def _run_edit(client, config, prompt, image, mask, work: Path, tag: str,
              extra_images=None) -> Image.Image:
    """One edit call, with every input written to the work dir so a bad draw can be looked at.

    `extra_images` ride along after the edited image in roster order -- the render pass sends
    the traced floor plan that way, so the prompt can name it as image 2.
    """
    size = image.size
    validate_size(size[0], size[1], source=str(config.get("config_source") or ""))
    image_path = work / f"{tag}_input.png"
    mask_path = work / f"{tag}_mask.png"
    out_path = work / f"{tag}_raw.png"
    image.save(image_path)
    _mask_image(mask).save(mask_path)
    roster = [str(image_path)] + [str(p) for p in (extra_images or [])]
    print(f"  {tag}: {size[0]}x{size[1]} ({size[0] * size[1] / 1e6:.2f} MP), "
          f"editable {100.0 * mask.mean():.1f}%, {len(roster)} image(s)")
    client.generate(prompt, roster, str(out_path), mask=str(mask_path))
    if not out_path.exists():
        raise BuildingInteriorError(f"{tag}: backend produced no image at {out_path}")
    return Image.open(out_path).convert("RGBA")


def contact_sheet(images: list[Path], out_path: Path, width: int = 520) -> Path:
    """Draws side by side with their index, so a layout can be chosen by eye.

    The sampler is unseeded: identical prompt and input give materially different layouts
    run to run. Picking the best of N is the cheapest quality lever there is, and it needs
    the draws next to each other rather than one at a time.
    """
    from PIL import ImageDraw

    thumbs = []
    for path in images:
        thumb = Image.open(path).convert("RGB")
        thumb.thumbnail((width, width))
        thumbs.append(thumb)
    height = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (sum(t.width for t in thumbs) + 10 * (len(thumbs) - 1), height + 24),
                      (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    x = 0
    for index, thumb in enumerate(thumbs, start=1):
        sheet.paste(thumb, (x, 24))
        draw.text((x + 6, 6), f"draw {index}", fill=(255, 220, 90))
        x += thumb.width + 10
    sheet.save(out_path)
    return out_path


def generate_interior(art: BuildingArt, config: dict, prompt: str, work: Path,
                      layout_only: bool = False, draws: int = 1,
                      start_from: Path | None = None) -> Image.Image:
    footprint, editable = build_masks(art)
    keep = footprint & ~editable
    roof = Image.open(art.roof_path).convert("RGBA")
    if roof.size != art.size:
        raise BuildingInteriorError(
            f"roof is {roof.size[0]}x{roof.size[1]} but the footprint is "
            f"{art.size[0]}x{art.size[1]}; they are composited 1:1 and must agree")

    work.mkdir(parents=True, exist_ok=True)
    client = make_image_client(config)

    if start_from is not None:
        # Resuming from a layout that was already drawn and chosen: skip the spend.
        candidate = Image.open(start_from).convert("RGBA")
        candidate = paste_back(candidate, roof, editable)
        check_border(candidate, roof, keep)
        print(f"  resuming from {start_from}")
    else:
        # Pass 1 -- where the corridor and chambers go, at the largest size one call allows.
        small = layout_size(art.size)
        small_mask = np.asarray(_mask_image(editable).resize(small, Image.NEAREST)) > 0
        small_roof = roof.resize(small, Image.LANCZOS)
        drawn = []
        for draw_index in range(1, draws + 1):
            tag = "pass1_layout" if draws == 1 else f"pass1_layout_draw{draw_index}"
            result = _run_edit(client, config, prompt, small_roof, small_mask, work, tag)
            candidate = paste_back(result, roof, editable)
            check_border(candidate, roof, keep)
            path = work / f"{tag}_composited.png"
            candidate.save(path)
            drawn.append(path)
            print(f"  {tag}: border check passed -> {path}")
        if draws > 1:
            sheet = contact_sheet(drawn, work / "layout_draws.png")
            print(f"\n  {draws} layouts drawn. Compare them: {sheet}\n"
                  f"  Then continue with the one you want:\n"
                  f"    --continue-from {drawn[0].parent}/pass1_layout_draw<N>_composited.png")
            return cut_alpha(Image.open(drawn[0]).convert("RGBA"), footprint)

    if layout_only:
        return cut_alpha(candidate, footprint)

    # Pass 2 -- the same picture again at 1:1, band by band, each seeing the last band's
    # output so the two halves continue each other rather than meeting at a seam.
    tile_prompt = (prompt + "\n\nThis is a detail pass at full resolution. Keep the layout "
                   "that is already here and sharpen it to match the surrounding stonework.")
    for index, (top, bottom) in enumerate(tile_rows(art.size[1])):
        band = editable[top:bottom]
        if not band.any():
            continue
        tag = f"pass2_tile{index}_{top}_{bottom}"
        tile = candidate.crop((0, top, art.size[0], bottom))
        result = _run_edit(client, config, tile_prompt, tile, band, work, tag)
        merged = np.asarray(candidate).copy()
        rows = merged[top:bottom]
        rows[band] = np.asarray(result.convert("RGBA").resize(tile.size, Image.LANCZOS))[band]
        merged[top:bottom] = rows
        candidate = Image.fromarray(merged, mode="RGBA")
        check_border(candidate, roof, keep)
        print(f"  {tag}: border check passed")

    candidate.save(work / "final_composited.png")
    return cut_alpha(candidate, footprint)


# ---------------------------------------------------------------- CLI

def check_only(art: BuildingArt) -> int:
    footprint, editable = build_masks(art)
    roof = Image.open(art.roof_path).convert("RGBA")
    if not art.interior_path.exists():
        print(f"FAIL {art.name}: no interior at {art.interior_path}")
        return 1
    interior = Image.open(art.interior_path).convert("RGBA")
    if interior.size != roof.size:
        print(f"FAIL {art.name}: interior {interior.size} != roof {roof.size}")
        return 1
    try:
        check_border(interior, roof, footprint & ~editable)
    except BuildingInteriorError as exc:
        print(f"FAIL {art.name}: {exc}")
        return 1
    print(f"OK   {art.name}: interior matches the roof outside the chamber, byte for byte")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--building", required=True)
    parser.add_argument("--config", type=Path,
                        help="image backend config json, e.g. openai.gpt-image-2.json")
    parser.add_argument("--prompt", type=Path,
                        help="prompt file (default: world_levels/prompts/<building>_interior.txt)")
    parser.add_argument("--work", type=Path,
                        help="pass-by-pass output dir (default: generated/building_interiors/<building>)")
    parser.add_argument("--check-only", action="store_true",
                        help="gate the interior already on disk; no API calls")
    parser.add_argument("--layout-only", action="store_true",
                        help="stop after the downscaled layout pass")
    parser.add_argument("--draws", type=int, default=1, metavar="N",
                        help="draw the layout N times and write a contact sheet to pick from; "
                             "each draw is one API call")
    parser.add_argument("--continue-from", type=Path, metavar="PNG",
                        help="skip the layout pass and run the detail tiles on this "
                             "already-drawn layout (a *_composited.png from --draws)")
    parser.add_argument("--dry-run", action="store_true",
                        help="force the copy backend: every pass, paste-back and gate runs "
                             "for real on the roof's own pixels, no spend")
    args = parser.parse_args(argv)

    try:
        art = load_building(args.map, args.building)
    except BuildingInteriorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{art.name}: canvas {art.size[0]}x{art.size[1]} at world {art.origin}")

    if args.check_only:
        return check_only(art)

    if not args.config:
        print("error: --config is required unless --check-only", file=sys.stderr)
        return 2
    config = json.loads(args.config.read_text())
    config.setdefault("config_source", args.config.name)
    if args.dry_run:
        # Copy, not manifest: manifest writes request json and no image, so the paste-back
        # and the gate would never run. Copy returns the input, which exercises every step
        # and must leave the border exact by construction.
        config["provider"] = "copy"

    here = Path(__file__).parent
    prompt_path = args.prompt or here / "world_levels/prompts" / f"{args.building}_interior.txt"
    if not prompt_path.exists():
        print(f"error: no prompt file at {prompt_path}", file=sys.stderr)
        return 2
    prompt = prompt_path.read_text()
    if not prompt.isascii():
        offender = next(c for c in prompt if not c.isascii())
        print(f"error: {prompt_path} contains the non-ASCII character {offender!r}; "
              "gpt-image-2 rejects the whole call", file=sys.stderr)
        return 2

    work = args.work or Path("generated/building_interiors") / args.building
    try:
        if args.draws < 1:
            print("error: --draws must be at least 1", file=sys.stderr)
            return 2
        if args.continue_from and not args.continue_from.exists():
            print(f"error: no such layout: {args.continue_from}", file=sys.stderr)
            return 2
        interior = generate_interior(art, config, prompt, work,
                                     layout_only=args.layout_only, draws=args.draws,
                                     start_from=args.continue_from)
    except BuildingInteriorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        # A rehearsal must never stand on the deliverable: the copy backend's "interior" is
        # just the roof, and writing it would quietly destroy the real asset.
        rehearsal = work / "dry_run_interior.png"
        interior.save(rehearsal)
        print(f"dry run: wrote {rehearsal}, left {art.interior_path} untouched")
        return 0

    interior.save(art.interior_path)
    print(f"wrote {art.interior_path}")
    return check_only(art)


if __name__ == "__main__":
    raise SystemExit(main())
