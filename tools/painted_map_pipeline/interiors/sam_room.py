"""The room as painted: local SAM3 finds the walls in the accepted painting.

The walls you collide with and the sight lines used to be built from the plan, and the render
never paints the plan exactly, so they stood off the painted walls. Now the painting defines
them, through the same path the level obstacles take: SAM3 polygons -> confidence floor,
`tag_polygon`, speck and containment culls -> `_polygon_to_tmx_object`.

SAM runs on `interior_crop`, the painting with everything outside the chamber blacked out, in
two passes. The coarse pass sees the whole crop, untiled -- the wrapper's tiling is for whole
levels, and on one interior it cut the walls into tile-sized scraps and took 56 passes -- and
says which things are walls. SAM shrinks anything to 560 px, so on a 3700 px crop each mask
pixel is about 7 painting pixels and the edges are blocks. The refine pass runs the same
prompt on windows twice that size, only where the coarse walls are, and says where exactly
their edges are: its masks are kept only on the coarse walls, OR-ed into one picture, and cut
into map polygons once, so a wall that crosses two windows is one wall.

Every piece SAM drew touching the door is dropped, in both passes, before anything is merged.
The model paints the top of a thick wall straight over the passage through it, so SAM finds
stone right behind the opening and the entrance is shut (INTERIORS_WORKFLOW.md). SAM returns
many overlapping masks for the same stone, so dropping a long band that touches the door only
opens what no other piece covers: the strip at the door.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..collision.sam3.containment_cull import filter_contained_polygons
from ..collision.sam3.isolation_cull import filter_specks_by_size_openness
from ..collision.sam3.merge_polygon_obstacles import _polygon_to_tmx_object
from ..collision.sam3.polygon_filters import tag_polygon
from ..world_levels.geometry import dilate_mask
from . import sam_local
from .emit import _pieces, shell_pieces, walk_in, walkable_mask
from .plan import door_mask, geometry_masks
from .trace import save_image

# Found by trying words on great_pyramid's painting (2026-10-26): "wall" finds the outer
# walls only, "stone border" at 0.2 finds every room and corridor wall.
WALL_PROMPTS = ("stone border",)
MIN_WALL_CONFIDENCE = 0.2
# A polygon with less than this share of its area inside the building outline is not one of
# its walls.
MIN_INSIDE_FRACTION = 0.5
# The refine pass: painting px per window (SAM sees it at 560, so twice the coarse detail), how
# much neighbours overlap, how far a refined edge may move off the coarse wall (about two
# coarse mask pixels), and how much of a refined mask must sit on the coarse walls to count.
REFINE_WINDOW = 1120
REFINE_OVERLAP = 0.15
REFINE_GROW_PX = 14
MIN_ON_COARSE = 0.5
# A piece within this many px of the door polygon touches the door and is dropped. On
# great_pyramid (2026-10-31) that was 18 pieces, and only the strip at the door opened; within
# 60 px it was 33, and the whole wall face went.
DOOR_TOUCH_PX = 10


def interior_crop(spec, painting: Path, work: Path) -> tuple:
    """(crop path, (x, y) offset): the painting with everything outside the chamber blacked
    out, cropped to the chamber plus a tile. SAM sees only the inside of the building;
    `offset` puts its polygons back on the painting."""
    _silhouette, chamber, _editable = geometry_masks(spec)
    image = np.asarray(Image.open(painting).convert("RGB")).copy()
    if image.shape[:2] != chamber.shape:
        raise ValueError(f"{Path(painting).name} is {image.shape[1]}x{image.shape[0]}, the "
                         f"building's canvas is {spec.size[0]}x{spec.size[1]}")
    image[~chamber] = 0
    ys, xs = np.nonzero(chamber)
    pad = int(spec.tile)
    x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
    x1, y1 = min(image.shape[1], int(xs.max()) + pad), min(image.shape[0], int(ys.max()) + pad)
    out = Path(work) / "interior_crop.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image[y0:y1, x0:x1]).save(out)
    return out, (x0, y0)


def _chunk_id(spec, painting: Path) -> str:
    """New bytes or a new chamber -> a new id: the wrapper's cache is keyed on the crop's path,
    which is the same file every time."""
    digest = hashlib.sha1(Path(painting).read_bytes())
    digest.update(json.dumps(spec.chamber).encode("utf-8"))
    return f"walls_{digest.hexdigest()[:12]}"


def _inside_fraction(points, silhouette) -> float:
    contour = np.round(np.asarray(points, dtype=np.float64)).astype(np.int32)
    x0, y0 = contour.min(axis=0)
    x1, y1 = contour.max(axis=0) + 1
    local = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(local, [contour - (x0, y0)], 1)
    area = int(local.sum())
    if not area:
        return 0.0
    h, w = silhouette.shape
    cx0, cy0, cx1, cy1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if cx0 >= cx1 or cy0 >= cy1:
        return 0.0
    inside = local[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0] & silhouette[cy0:cy1, cx0:cx1]
    return float(inside.sum()) / area


def _filtered(polygons, size) -> list:
    """The level obstacles' culls: confidence floor, `tag_polygon`, specks, contained."""
    kept = [tag_polygon(p) for p in polygons
            if float(p.get("confidence", 0.0)) >= MIN_WALL_CONFIDENCE]
    if kept:
        kept, _stats = filter_specks_by_size_openness(kept, image_size=size)
    if kept:
        kept, _stats = filter_contained_polygons(kept, image_size=size)
    return kept


def _fill(shape, points, offset=(0, 0)) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(np.asarray(points, dtype=np.float64) + offset)
                        .astype(np.int32)], 1)
    return mask > 0


def _touches(points, near, offset=(0, 0)) -> bool:
    """Does the polygon cover any pixel of `near`? Filled within its own box, not the crop."""
    contour = np.round(np.asarray(points, dtype=np.float64) + offset).astype(np.int32)
    x0, y0 = np.maximum(contour.min(axis=0), 0)
    x1, y1 = np.minimum(contour.max(axis=0) + 1, (near.shape[1], near.shape[0]))
    if x0 >= x1 or y0 >= y1 or not near[y0:y1, x0:x1].any():
        return False
    local = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(local, [contour - (x0, y0)], 1)
    return bool(((local > 0) & near[y0:y1, x0:x1]).any())


def _windows(size, coarse) -> list:
    """(x0, y0, x1, y1) refine windows over a crop of `size`, only those with coarse walls."""
    width, height = size
    stride = int(REFINE_WINDOW * (1 - REFINE_OVERLAP))
    starts = lambda edge: sorted({min(s, max(0, edge - REFINE_WINDOW))
                                  for s in range(0, max(1, edge - REFINE_WINDOW) + stride, stride)})
    boxes = []
    for y0 in starts(height):
        for x0 in starts(width):
            box = (x0, y0, min(width, x0 + REFINE_WINDOW), min(height, y0 + REFINE_WINDOW))
            if coarse[box[1]:box[3], box[0]:box[2]].any():
                boxes.append(box)
    return boxes


def _refined(crop: Path, coarse, way_in, near_door, chunk_id: str, work: Path) -> tuple:
    """(polygons, dropped): the coarse walls (crop px) redrawn from the refine pass, as
    polygons in crop px, with `way_in` (crop px) cut out of them, and how many refined pieces
    were dropped for touching `near_door`."""
    image = Image.open(crop)
    shape = (image.height, image.width)
    allowed = dilate_mask(coarse, REFINE_GROW_PX)
    wall = np.zeros(shape, dtype=bool)
    score = np.zeros(shape, dtype=np.float32)
    boxes = _windows(image.size, coarse)
    dropped = 0
    print(f"  refining the walls: {len(boxes)} window(s) of {REFINE_WINDOW} px")
    for x0, y0, x1, y1 in boxes:
        path = Path(work) / "windows" / f"w_{x0}_{y0}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.crop((x0, y0, x1, y1)).save(path)
        found = sam_local.segment(path, list(WALL_PROMPTS), Path(work) / "sam",
                                  chunk_id=f"{chunk_id}_w_{x0}_{y0}", tile=False)
        for polygon in found:
            confidence = float(polygon.get("confidence", 0.0))
            if confidence < MIN_WALL_CONFIDENCE:
                continue
            if _touches(polygon["points"], near_door, (x0, y0)):
                dropped += 1
                continue
            piece = _fill(shape, polygon["points"], (x0, y0))
            area = int(piece.sum())
            if area and (piece & allowed).sum() / area >= MIN_ON_COARSE:
                wall |= piece
                score[piece] = np.maximum(score[piece], confidence)
    wall &= allowed & ~way_in
    out = []
    for points in _pieces(wall, np.ones_like(wall), (0, 0)):
        piece = _fill(shape, points)
        out.append({"class": WALL_PROMPTS[0], "prompt": WALL_PROMPTS[0],
                    "confidence": float(score[piece].max()) if piece.any() else 0.0,
                    "points": [[float(x), float(y)] for x, y in points]})
    return out, dropped


def sam_walls(plan, painting: Path, work: Path) -> list:
    """The walls SAM finds in `painting`, in canvas px: [{points, confidence, sam3_class,
    collision_mode, chunk_id, ...}]. Raises `sam_local.SamLocalError` when SAM cannot run.

    Every piece touching the door is dropped first, in both passes: the wall's painted top
    runs straight over the passage behind the opening (see the module docstring). The way in
    -- the door dragged inward to the floor -- is still cut out of what is left, as it is out
    of the shell (`walkable_mask`)."""
    spec = plan.spec
    chunk_id = _chunk_id(spec, painting)
    crop, (x0, y0) = interior_crop(spec, painting, work)
    with Image.open(crop) as probe:
        size = probe.size
    in_crop = (slice(y0, y0 + size[1]), slice(x0, x0 + size[0]))
    near_door = dilate_mask(door_mask(spec)[in_crop], DOOR_TOUCH_PX)
    found = [p for p in sam_local.segment(crop, list(WALL_PROMPTS), Path(work) / "sam",
                                          chunk_id=chunk_id, tile=False)
             if float(p.get("confidence", 0.0)) >= MIN_WALL_CONFIDENCE]
    away = [p for p in found if not _touches(p["points"], near_door)]
    silhouette = geometry_masks(spec)[0].astype(np.uint8)
    coarse = [p for p in _filtered(away, size)
              if _inside_fraction([[x + x0, y + y0] for x, y in p["points"]],
                                  silhouette) >= MIN_INSIDE_FRACTION]
    if not coarse:
        return []
    coarse_mask = np.zeros((size[1], size[0]), dtype=bool)
    for polygon in coarse:
        coarse_mask |= _fill(coarse_mask.shape, polygon["points"])
    way_in = (walkable_mask(plan) & ~plan.floor)[in_crop]
    refined, dropped = _refined(crop, coarse_mask, way_in, near_door, chunk_id, work)
    print(f"  dropped {len(found) - len(away)} coarse and {dropped} refined piece(s) "
          f"touching the door")
    walls = []
    for polygon in _filtered(refined, size):
        points = [[float(x) + x0, float(y) + y0] for x, y in polygon["points"]]
        if len(points) >= 3 and _inside_fraction(points, silhouette) >= MIN_INSIDE_FRACTION:
            walls.append(dict(polygon, points=points, chunk_id=chunk_id))
    return walls


def world_walls(spec, walls) -> list:
    """`walls` as world-coordinate point tuples, the form the emitter's checks take."""
    ox, oy = spec.origin
    return [tuple((x + ox, y + oy) for x, y in wall["points"]) for wall in walls]


def wall_objects(spec, walls, first_id: int) -> tuple:
    """(xml, next id): each wall as a map object named `<building>_wall_NN`.

    `_polygon_to_tmx_object` as the level merge uses it, so the game loads these exactly as
    it loads the level's SAM obstacles. Every object ends in a newline: the emitter's
    name-prefix strip only removes objects that do, and without it re-accepted walls pile up.
    """
    xml, obj_id = "", first_id
    for index, wall in enumerate(walls):
        obj = _polygon_to_tmx_object(
            wall["points"], world_x=spec.origin[0], world_y=spec.origin[1], object_id=obj_id,
            chunk_id=wall.get("chunk_id", ""), sam3_class=wall["sam3_class"],
            sam3_confidence=wall.get("confidence"), collision_mode=wall["collision_mode"])
        if obj is None:
            continue
        obj.set("name", f"{spec.building}_wall_{index:02d}")
        xml += "  " + ET.tostring(obj, encoding="unicode") + "\n"
        obj_id += 1
    return xml, obj_id


def walls_path(spec) -> Path:
    """Where the accepted walls are kept: beside the interior image, so they go into git with
    it and later steps need no SAM run."""
    return Path(spec.interior_image).with_name(f"{spec.building}_walls.json")


def save_walls(spec, walls) -> Path:
    path = walls_path(spec)
    path.write_text(json.dumps({"walls": walls}) + "\n", encoding="utf-8")
    return path


def overlay(painting: Path, walls, out: Path, plan=None) -> Path:
    """The painting with the walls filled and outlined in red, for the accept screen.

    Given the plan, green is where a body from outside can walk through these walls and the
    shell (`emit.walk_in`): it runs on into the rooms, or stops where the entrance is shut."""
    image = Image.open(painting).convert("RGB")
    marked = np.asarray(image).copy()
    fill = np.zeros(marked.shape[:2], dtype=np.uint8)
    for wall in walls:
        cv2.fillPoly(fill, [np.round(np.asarray(wall["points"])).astype(np.int32)], 1)
    marked[fill > 0] = (255, 0, 0)
    if plan is not None:
        reach, _open = walk_in(plan, world_walls(plan.spec, walls) + shell_pieces(plan))
        marked[reach & plan.silhouette & (fill == 0)] = (0, 255, 90)
    shown = Image.blend(image, Image.fromarray(marked), 0.45)
    edges = np.asarray(shown).copy()
    for wall in walls:
        cv2.polylines(edges, [np.round(np.asarray(wall["points"])).astype(np.int32)], True,
                      (255, 0, 0), 3)
    # `save_image`: a viewer still open on the last run's overlay makes the name unwritable.
    return save_image(Image.fromarray(edges), out)
