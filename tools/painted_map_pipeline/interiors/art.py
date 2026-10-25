"""A `BuildingArt` built from a discovered polygon instead of a TMX object.

`load_building` reads nine things off the map: the footprint, a second object carrying
`chamber_of`, the two image paths, the door point. On the sam3 path every one of those is
either known from the segmentation or follows from the building's own geometry, so requiring
them to be authored means drawing the building before asking SAM3 to find it.

This derives the same record. `load_building` is untouched and the tmx provider still uses
it -- a building genuinely drawn by hand in Tiled is a real case and stays supported.

The one judgement here is the chamber, and it is not made here: the wall thickness comes from
`ask_model`, and this only erodes by it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..building_interiors import BuildingArt, BuildingInteriorError
from ..world_levels.geometry import dilate_mask
from ..world_levels.masks import rasterize_polygon
from .runtime import building_geometry
from .trace import trace_boundaries

Image.MAX_IMAGE_PIXELS = None


def _polygon_area(polygon) -> float:
    """Shoelace."""
    total = 0.0
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def erode_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    """Shrink by `radius`. `dilate_mask` is the only morphology in the tree, and eroding is
    dilating the complement -- the same identity `checks.py` already leans on.

    The pad is not decoration. The canvas here IS the silhouette's bounding box, so the
    footprint touches all four borders by construction; without a border of background to
    dilate inward from, the complement is empty at the edges and the erosion silently does
    nothing on exactly the sides that matter.
    """
    if radius <= 0:
        return mask.astype(bool)
    padded = np.pad(mask.astype(bool), radius, constant_values=False)
    return (~dilate_mask(~padded, radius))[radius:-radius, radius:-radius]


# How far past the eroded wall the doorway passage reaches, as a multiple of the wall. The
# passage has to clear the eroded band with room to spare, or the floor meets the threshold at
# a single pixel and the trace treats it as noise.
PASSAGE_DEPTH = 2.0


def _passage(size, door_point, door_inward, door_gap: float, wall: int) -> np.ndarray:
    """A corridor-shaped hole cut from the door plane inward, as a mask.

    Same construction as the game's own `arch_quad` -- origin, inward, tangent, gap, depth --
    at a greater depth, so the shape the model may paint into and the shape the engine cuts
    for the arch are built by the same code rather than two that must be kept in step.
    """
    geometry = building_geometry()
    inward = np.array(door_inward, dtype=float)
    tangent = np.array([-inward[1], inward[0]])
    quad = geometry.arch_quad(tuple(door_point), tuple(inward), tuple(tangent),
                              door_gap, max(wall * PASSAGE_DEPTH, wall + 40))
    return np.asarray(rasterize_polygon(size, [tuple(p) for p in quad])) > 0


def chamber_from(footprint, size, wall: int, door_point=None, door_inward=None,
                 door_gap: float = 0) -> tuple:
    """The editable region: the footprint minus its walls, plus a way in.

    Only ever the *initial* region -- the spec calls the chamber "as authored (superseded by
    the trace)", and the real walls come from tracing what the plan pass paints.

    The passage is not a refinement. Eroding the footprint by the wall pulls the paintable
    region ~90 px away from a door that sits ON the silhouette edge, so the model is forbidden
    from painting anywhere near the threshold -- while the prompt tells it "FLOOR must start
    immediately behind it, not near it, AT it" and `floor_behind_door` then fails the gap it
    was never allowed to close. Every draw failed that check for this reason.

    The tmx path never hit it because its chamber was drawn by hand and reached the doorway.
    Deriving the chamber by erosion means carving the way in explicitly.
    """
    mask = np.asarray(rasterize_polygon(size, footprint)) > 0
    if not mask.any():
        raise BuildingInteriorError("the silhouette rasterised to nothing")

    # No backing off to a thinner wall when this one closes the building. That would be the
    # same silent substitution the wall thickness itself refuses: a chamber nobody chose,
    # written into the spec and trusted by every step after it. If a measured wall does not
    # leave an interior, the building is too small for one and that is the finding.
    eroded = erode_mask(mask, wall)
    if door_point is not None and door_inward is not None and door_gap > 0:
        # Clipped to the silhouette so the passage cannot reach outside the building.
        eroded = eroded | (_passage(size, door_point, door_inward, door_gap, wall) & mask)

    outers = [b for b in trace_boundaries(eroded) if not b.is_hole]
    if not outers:
        raise BuildingInteriorError(
            f"a {wall}px wall leaves no chamber inside this {size[0]}x{size[1]} silhouette")
    # Largest by area, not by vertex count: erosion can leave a ragged sliver with more
    # corners than the room it broke off.
    return max(outers, key=lambda b: _polygon_area(b.polygon)).polygon


def bbox_of(polygon) -> tuple:
    """(origin, size) of a world polygon, as ints. The canvas every local coord is relative
    to, and the crop the exterior comes from -- so the two cannot disagree."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    origin = (int(min(xs)), int(min(ys)))
    return origin, (int(round(max(xs))) - origin[0], int(round(max(ys))) - origin[1])


def crop_exterior(image_path: Path, origin, size, out_path: Path) -> Path:
    """The building's own exterior art, cut out of the level image.

    This is the render pass's input image and the thing `check_border` asserts byte equality
    against outside the chamber, so it is written once and read from disk afterwards -- not
    re-cropped per step, where a one-pixel difference in rounding would fail the gate. An
    existing crop of the right size is therefore kept, not overwritten.

    `image_path` must be the FULL-RESOLUTION level image. Discovery may show SAM3 a downscaled
    copy (`sam_local.segment(downscale=...)`), but that copy exists only to find buildings and
    its coordinates are scaled back before anything reaches here. Cropping from the small copy
    would ship a blurred exterior and break the byte-equality gate, and it would do it quietly.
    """
    out_path = Path(out_path)
    if out_path.exists():
        with Image.open(out_path) as existing:
            if existing.size == tuple(size):
                return out_path
    left, top = origin
    with Image.open(image_path) as level:
        crop = level.convert("RGBA").crop((left, top, left + size[0], top + size[1]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out_path)
    return out_path


# Depth bands, in px, when measuring how wide the opening is at each distance into the wall.
DOOR_BAND = 3.0


def door_opening_from_art(footprint, door_point, door_polygon, image_path: Path,
                          origin=(0, 0)) -> float:
    """The width of the WALKABLE GAP, not of the doorway feature.

    What SAM returns for "pyramid entrance" is the whole architectural feature: the lintel
    above, a stone jamb either side, and the dark opening between them. Measuring that gives a
    threshold 30-45% wider than the hole you can actually walk through -- 301 px where the
    opening is 218, 174 where it is 124.

    The opening is the dark part, and it separates cleanly: inside the entrance polygon the
    luminance is strongly bimodal (lit stone against a void), so Otsu finds the cut without a
    threshold being chosen here.

    Width is the MEDIAN across depth bands, and both alternatives are wrong in a way worth
    recording. The convex hull spans the shadow under the lintel, which is dark but is not a
    way in. The minimum band catches the far end of the recess, where the art simply fades to
    black rather than narrowing -- that reported `pyramid_04` at 23 px, half a player, for a
    doorway a player walks through comfortably.

    Returns 0 when no dark core separates -- a doorway painted flat, or one already in shadow
    -- and the caller falls back to the polygon's own extent.
    """
    import cv2

    polygon = np.array([[int(round(x - origin[0])), int(round(y - origin[1]))]
                        for x, y in door_polygon], dtype=np.int32)
    with Image.open(image_path) as source:
        grey = np.asarray(source.convert("L"))

    inside = np.zeros(grey.shape, np.uint8)
    cv2.fillPoly(inside, [polygon], 1)
    if inside.sum() < 16:
        return 0.0
    threshold, _ = cv2.threshold(grey[inside > 0].astype(np.uint8), 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = ((grey < threshold) & (inside > 0)).astype(np.uint8)

    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(dark, 8)
    if count < 2:
        return 0.0
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    rows, columns = np.where(labels == largest)
    if len(columns) < 16:
        return 0.0

    geometry = building_geometry()
    _index, projection = geometry.nearest_edge(list(footprint), tuple(door_point))
    tx, ty = projection.tangent
    along = columns * tx + rows * ty
    deep = columns * -ty + rows * tx

    widths = []
    low, high = deep.min(), deep.max()
    for start in np.arange(low, high, DOOR_BAND):
        band = along[(deep >= start) & (deep < start + DOOR_BAND)]
        if len(band) > 5:
            widths.append(float(band.max() - band.min()))
    return float(np.median(widths)) if widths else 0.0


def door_gap_from_polygon(footprint, door_point, door_polygon) -> float:
    """How wide the painted doorway is ALONG THE WALL it sits on, floored at passable.

    Not its bounding box. A doorway on a slanted face -- which is every face of a pyramid --
    has a bbox wider than the opening, by up to ~1.4x at 45 degrees, and the gap the game cuts
    is measured along the wall. Using the bbox would install a subtler version of the bug this
    replaces.

    `nearest_edge` already decides which wall the door belongs to and hands back that edge's
    tangent, so the projection reuses the same edge the arch quad will be built on rather than
    picking one independently and disagreeing with it.

    """
    geometry = building_geometry()
    _index, projection = geometry.nearest_edge(list(footprint), tuple(door_point))
    tx, ty = projection.tangent
    along = [x * tx + y * ty for x, y in door_polygon]
    return float(max(along) - min(along))


def _door_gap(footprint, door_point, door_polygon, exterior: Path) -> float:
    """The walkable opening when the art shows one, the doorway feature when it does not."""
    opening = 0.0
    try:
        opening = door_opening_from_art(footprint, door_point, door_polygon, exterior)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  could not read the opening out of the art ({type(exc).__name__}: {exc})")
    feature = door_gap_from_polygon(footprint, door_point, door_polygon)
    if opening <= 0:
        print(f"  no dark opening separates inside the doorway; using the whole feature "
              f"({feature:.0f} px), which is wider than the gap you walk through")
        return feature
    print(f"  doorway: feature {feature:.0f} px, walkable opening {opening:.0f} px")
    return opening


def art_from_polygon(name: str, silhouette_world, level_image: Path, work: Path,
                     *, wall: int, door_point_world=None, door_polygon_world=None,
                     level_dir: Path = None) -> BuildingArt:
    """Everything `load_building` reads off the map, derived from one polygon."""
    origin, size = bbox_of(silhouette_world)
    if size[0] < 2 or size[1] < 2:
        raise BuildingInteriorError(f"{name}: silhouette is {size[0]}x{size[1]}px")

    def to_local(polygon):
        return tuple((x - origin[0], y - origin[1]) for x, y in polygon)

    footprint = to_local(silhouette_world)
    door_point = to_local([door_point_world])[0] if door_point_world else None
    level_dir = Path(level_dir) if level_dir else Path(level_image).parent

    # The exterior crop has to exist before the opening can be read out of it, and the door
    # has to be measured before the chamber, because the chamber needs a way in cut to it.
    exterior = crop_exterior(Path(level_image), origin, size,
                             Path(work) / f"{name}_exterior.png")
    door_gap = (_door_gap(footprint, door_point, to_local(door_polygon_world), exterior)
                if (door_polygon_world and door_point) else None)
    door_plane = (building_geometry().door_plane_from_polygon(
        footprint, door_point, door_gap=door_gap) if (door_point and door_gap) else None)

    return BuildingArt(
        name=name,
        origin=origin,
        size=size,
        footprint=footprint,
        chamber=chamber_from(footprint, size, wall,
                             door_point=door_plane[0] if door_plane else None,
                             door_inward=door_plane[1] if door_plane else None,
                             door_gap=door_gap or 0),
        # The painted door is SAM's entrance polygon. Held out of the editable region like
        # a hand-drawn `door_of`, restored over the render, and -- once written to the map at
        # accept -- the overhead area the engine hides a body under. The carved passage above
        # is the way in; the hold-out is the frame it passes under. Not in conflict.
        doors=(to_local(door_polygon_world),) if door_polygon_world else (),
        roof_path=exterior,
        interior_path=level_dir / "buildings" / f"{name}_interior.png",
        door_point=door_point,
        door_gap=door_gap,
    )
