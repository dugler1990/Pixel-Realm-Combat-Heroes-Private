"""Find every building in a level image, and pair each one with its entrance.

``from_sam3`` asks the same two questions this does, then throws away all but one answer: it
keeps the largest object hit and the *first* entrance in the response -- the first found
anywhere on the level, with nothing tying it to the building it was matched against. That is
survivable when the input is a crop of one known building, which is what it was written for.
Run it on a whole level and it silently returns one pyramid and somebody else's door.

So discovery returns the whole set, an entrance is matched to the building it actually
belongs to, and choosing between them is a decision you make from a table and an overlay
rather than one the code makes by area.

Nothing here spends money: one local SAM3 run, then mask arithmetic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import sam_local

Image.MAX_IMAGE_PIXELS = None

TILE = 150

# What SAM resizes every input to. Locate sends the whole map and gets a view this wide, so
# one model pixel covers `map_width / MODEL_EDGE` source pixels -- the size of the error in a
# located outline, and what the refine crop is padded by.
MODEL_EDGE = 560

# Smallest share of the level a building can occupy and still be worth an interior.
#
# Expressed against the map rather than in pixels because pixels mean nothing here: SAM3's own
# `min_polygon_area` is 50 SQUARE pixels of the input, a 7x7 speck on a 69 MP map, so it drops
# nothing. And its results arrive fragmented -- `mask_to_polygons` emits one record per
# disconnected blob in a mask, so a single instance can become dozens of slivers. Both are cut
# by one honest question: is this thing a real fraction of the level?
#
# Measured on sunspine: the four real pyramids are 0.19%, 0.21%, 0.31% and 2.01% of the map.
# The floor starts below all of them on purpose -- a first pass that hides a real building is
# worse than one showing a few extra, because you can see junk and tighten, but you cannot see
# what was never drawn.
MIN_AREA_FRACTION = 0.0005      # 0.05%

# And a ceiling, because the failure at the top end is real: SAM returned the whole landmass
# as a "pyramid" covering 48.7% of the map. Nothing that big is a building you enter.
MAX_AREA_FRACTION = 0.05        # 5%

# Score floor. SAM3's own `threshold` is 0.0, so it returns everything it can imagine.
#
# Measured on the first real locate pass over sunspine: of 685 polygons, 479 scored under
# 0.05 and 538 under 0.20, while the great_pyramid came back at 0.965. Between 0.25 and 0.85
# there was nothing at all -- the junk and the real building are not on a continuum, they are
# two separate populations, so the floor only has to land in the gap.
#
# Set below the gap rather than in it, for the same reason as the area floor: the first pass
# should over-show. Both junk shapes that survive at this setting score 0.21; every real
# pyramid scores 0.86+, so tightening to 0.5 is an obvious move once you have seen the table.
MIN_CONFIDENCE = 0.15

# The entrance gets its own floor, and against a different denominator. It is looked for in
# the refine crop, so its share is of one building, not of the level -- and a doorway is a
# small part of a pyramid where a pyramid is a large part of a map. One number could not mean
# both. 0.1% of a 4000x3400 crop is roughly a 115px doorway.
ENTRANCE_MIN_AREA_FRACTION = 0.001

# And a ceiling, for the same reason locate needed one -- the failure at the top end is the
# loud one. Asked for a "pyramid entrance" inside a pyramid's crop, SAM's best match in every
# single crop was the WHOLE PYRAMID: 43-47% of the frame at 0.65-0.87 confidence, because the
# phrase contains "pyramid". Its centroid is the building's centre, which is a door drawn in
# the middle of the room. A doorway is a small part of a building by definition.
ENTRANCE_MAX_AREA_FRACTION = 0.10

# How far outside a silhouette an entrance centroid may sit and still belong to it. A doorway
# is painted on the wall's outer face, so its centroid routinely lands just outside the
# traced edge -- but never by more than about a character, which is what TILE is.
ENTRANCE_SLACK = TILE


@dataclass
class Candidate:
    """One building SAM3 found, and everything cheap that can be said about it."""

    index: int
    name: str
    silhouette: tuple                # image px
    confidence: float = 0.0
    door_point: tuple = None         # image px, or None when no entrance was matched
    door_rule: str = ""              # how the entrance was matched, for the table
    door_polygon: tuple = None       # the matched doorway itself, level px -- what SAM found
    door_options: tuple = ()         # every match that landed on this building, best first
    door_choice: int = 0             # which of them is currently chosen
    door_size: tuple = None          # its bbox, for judging it at a glance
    door_confidence: float = 0.0
    entrance_candidates: int = 0     # how many landed on this building
    iou: float = None                # filled by identify.gate when the map has obstacles
    fragments: int = 0
    notes: tuple = ()
    approximate: bool = True         # located, not yet refined -- edges are coarse
    parent: str = ""                 # the located candidate this was refined out of
    # How far inside the wall the kept entrance sits, so a second candidate can be compared
    # against it. Bookkeeping for `pair_entrances`, not part of the record.
    door_distance: float = field(default=float("-inf"), repr=False)

    @property
    def area(self) -> float:
        return _area(self.silhouette)

    @property
    def bbox(self) -> tuple:
        return _bbox(self.silhouette)

    @property
    def size(self) -> tuple:
        left, top, right, bottom = self.bbox
        return (int(round(right - left)), int(round(bottom - top)))


def _area(polygon) -> float:
    """Shoelace."""
    total = 0.0
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _bbox(polygon) -> tuple:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _centroid(points) -> tuple:
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


def _points_of(polygon: dict, origin=(0, 0)) -> tuple:
    return tuple((float(x) + origin[0], float(y) + origin[1]) for x, y in polygon["points"])


def _matching(polygons, prompt: str) -> list:
    """Polygons SAM3 labelled with this prompt. Class and prompt are the same string here --
    the prompts file is written as bare strings, so the local runner sets both."""
    wanted = prompt.strip().lower()
    return [p for p in polygons
            if str(p.get("class", "")).strip().lower() == wanted]


def _signed_distance(polygon, point) -> float:
    """cv2's signed distance: positive inside, negative outside, in pixels."""
    contour = np.asarray([[int(round(x)), int(round(y))] for x, y in polygon], dtype=np.int32)
    return float(cv2.pointPolygonTest(contour, (float(point[0]), float(point[1])), True))


def pair_entrances(candidates: list, entrances: list) -> None:
    """Attach each entrance to the building it belongs to. Mutates the candidates.

    Containment first, then nearest-wall within a character's slack, because a doorway is
    painted on the outer face and its centroid lands outside the silhouette as often as in.
    An entrance matching nothing is dropped with a note; a building matching nothing keeps
    `door_point=None`, which the caller reports rather than treats as a failure.
    """
    landed = {id(c): [] for c in candidates}
    for entrance in entrances:
        point = _centroid(entrance["points"])
        scored = [(_signed_distance(c.silhouette, point), c) for c in candidates]
        distance, best = max(scored, key=lambda pair: pair[0])
        if distance < -ENTRANCE_SLACK:
            continue
        landed[id(best)].append((distance, entrance))
        best.entrance_candidates += 1
        # Several doorways on one building: keep the one furthest inside the wall, which is
        # the one actually cut into it rather than a shadow or a step beside it.
    # Ranked, not reduced to one. Deepest inside the wall first -- a doorway cut into a wall
    # beats a shadow beside it -- but every match is kept so the choice can be stepped through
    # rather than taken on trust.
    for candidate in candidates:
        options = sorted(landed[id(candidate)], key=lambda pair: -pair[0])
        candidate.door_options = tuple(entrance for _, entrance in options)
        candidate.door_distance = options[0][0] if options else float("-inf")
        select_door(candidate, 0)


def select_door(candidate: Candidate, choice: int) -> None:
    """Choose which of this building's matches is its door. Wraps, so stepping cycles.

    The default is index 0, the match deepest inside the wall. That is a good rule and not a
    reliable one -- with six matches on one building it is a guess wearing a ranking -- so the
    choice is steppable rather than final.
    """
    if not candidate.door_options:
        candidate.door_point = candidate.door_polygon = candidate.door_size = None
        candidate.door_confidence = 0.0
        candidate.door_rule = ""
        candidate.door_choice = 0
        return
    candidate.door_choice = choice % len(candidate.door_options)
    entrance = candidate.door_options[candidate.door_choice]
    point = _centroid(entrance["points"])
    left, top, right, bottom = _bbox(entrance["points"])
    distance = _signed_distance(candidate.silhouette, point)
    candidate.door_point = point
    candidate.door_polygon = tuple((float(x), float(y)) for x, y in entrance["points"])
    candidate.door_size = (int(round(right - left)), int(round(bottom - top)))
    candidate.door_confidence = float(entrance.get("confidence", 0.0))
    candidate.door_rule = "inside" if distance >= 0 else f"{abs(distance):.0f}px outside"
    if len(candidate.door_options) > 1:
        candidate.door_rule += f"  [{candidate.door_choice + 1}/{len(candidate.door_options)}]"


def locate_error(image_size) -> int:
    """Source pixels per model pixel when the whole image is sent untiled.

    SAM resizes anything to MODEL_EDGE, so this is how coarse a located outline is -- and the
    only number the padding below needs.
    """
    return max(1, math.ceil(max(image_size) / MODEL_EDGE))


def refine_pad(image_size) -> int:
    """How much to pad a located bbox before cropping it for refinement.

    Generous on purpose: over-padding costs a few extra tiles, under-padding clips the
    building and there is no way to notice from inside the crop.
    """
    return max(100, 4 * locate_error(image_size))


@dataclass
class Located:
    """What one whole-map SAM pass found, before any thresholds are applied.

    The pass is the expensive half and the thresholds are the half you will want to change
    your mind about, so they are separated: this holds the raw result, and `filtered()` is
    pure and instant. Re-deciding a threshold must never re-run the GPU.
    """

    hits: list                       # every match for the object prompt, unfiltered
    level_size: tuple
    prompt: str

    @property
    def level_area(self) -> float:
        return float(self.level_size[0] * self.level_size[1])

    def filtered(self, *, min_confidence: float = MIN_CONFIDENCE,
                 min_area_fraction: float = MIN_AREA_FRACTION,
                 max_area_fraction: float = MAX_AREA_FRACTION,
                 name_prefix: str = "") -> list:
        """Thresholds -> candidates. Pure, so the tuning loop costs nothing."""
        floor = min_area_fraction * self.level_area
        ceiling = max_area_fraction * self.level_area
        kept = [h for h in self.hits
                if float(h.get("confidence", 0.0)) >= min_confidence
                and floor <= _area(_points_of(h)) <= ceiling]

        prefix = (name_prefix or self.prompt).strip().lower().replace(" ", "_")
        # By score, not area: the junk and the real buildings separate on score, so this puts
        # the cut line where your eye already is.
        candidates = []
        for index, hit in enumerate(sorted(kept, key=lambda h: -float(h.get("confidence", 0))),
                                    start=1):
            candidates.append(Candidate(
                index=index,
                name=f"{prefix}_{index:02d}",
                silhouette=_points_of(hit),
                confidence=float(hit.get("confidence", 0.0)),
                approximate=True,
            ))
        return candidates

    def spread(self) -> str:
        """What the thresholds are choosing between, so a change is an informed one."""
        scores = sorted((float(h.get("confidence", 0.0)) for h in self.hits), reverse=True)
        areas = sorted((_area(_points_of(h)) / self.level_area for h in self.hits),
                       reverse=True)
        return (f"  {len(self.hits)} raw match(es).  scores "
                f"{scores[-1]:.2f}-{scores[0]:.2f}, sizes "
                f"{areas[-1]:.3%}-{areas[0]:.1%} of the map")


def locate(image_path: Path, object_prompt: str, work: Path,
           *, downscale: int = None, rescan: bool = False) -> Located:
    """Pass one: where are the buildings. The whole map, untiled -- one pass per prompt.

    Untiled means SAM sees the entire level squashed into MODEL_EDGE, so a building is tens of
    pixels: enough to find, nowhere near enough to trace. That is the whole point -- outlines
    from here are approximate by construction and get replaced by `refine`.

    Only the object prompt is asked. An entrance is a couple of pixels at this scale; asking
    for it here spends a pass to produce noise, and refine finds it properly inside the crop.

    Returns everything it found. Thresholding is `Located.filtered`, deliberately not done
    here: this is the part that costs GPU time and must run once.
    """
    image_path = Path(image_path)
    with Image.open(image_path) as level:
        level_size = level.size
        if downscale is None:
            downscale = sam_local.required_downscale(level_size)
    if downscale > 1:
        # Not a quality decision: SAM resizes to MODEL_EDGE whatever it is handed, so this
        # factor changes nothing it sees. It exists only so PIL will open the file.
        print(f"  locate: 1/{downscale} so the file opens; SAM resizes to {MODEL_EDGE} "
              f"either way, so this does not change what it sees")

    polygons = sam_local.segment(image_path, [object_prompt], Path(work),
                                 downscale=downscale, tile=False, chunk_id="locate",
                                 rescan=rescan)
    hits = _matching(polygons, object_prompt)
    if not hits:
        found = sorted({str(p.get("class")) for p in polygons})
        raise ValueError(
            f"SAM3 found nothing it called {object_prompt!r} in the whole map; it returned "
            f"{found}. Try wording the object differently.")
    return Located(hits=hits, level_size=level_size, prompt=object_prompt)


def _window(bbox, pad: int, image_size) -> tuple:
    """The padded crop box, clamped to the image."""
    left = max(0, int(bbox[0]) - pad)
    top = max(0, int(bbox[1]) - pad)
    right = min(image_size[0], int(math.ceil(bbox[2])) + pad)
    bottom = min(image_size[1], int(math.ceil(bbox[3])) + pad)
    return left, top, right, bottom


def _offset(polygons, origin) -> list:
    """Crop-local coordinates -> full-resolution level coordinates."""
    out = []
    for polygon in polygons:
        moved = dict(polygon)
        moved["points"] = [[float(x) + origin[0], float(y) + origin[1]]
                           for x, y in polygon["points"]]
        out.append(moved)
    return out


def _overlaps(polygon, other) -> bool:
    """Do these two outlines describe the same thing?

    Centroid containment rather than IoU: a duplicate detection of one building always has its
    centre inside the other's outline, whichever of the two is larger, and it costs one
    `pointPolygonTest` instead of rasterising both. Two genuinely adjacent buildings touch at
    their edges -- neither centre lands inside the other.
    """
    return (_signed_distance(other, _centroid(polygon)) >= 0
            or _signed_distance(polygon, _centroid(other)) >= 0)


def _suffixed(name: str, position: int) -> str:
    """First keeps the located name; the rest get a letter, so a fusion is visible in the
    names rather than silently renumbering everything under you."""
    return name if position == 0 else f"{name}{chr(ord('b') + position - 1)}"


def _crop(image_path: Path, window, out_path: Path) -> tuple:
    """Cut a window out of the full-resolution level. Returns (path, origin, size).

    Reused when it already exists at the right size, because the render pass asserts byte
    equality against the exterior and a re-crop that rounds differently would fail that.
    """
    size = (window[2] - window[0], window[3] - window[1])
    out_path = Path(out_path)
    if out_path.exists():
        with Image.open(out_path) as existing:
            if existing.size == size:
                return out_path, (window[0], window[1]), size
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as level:
        level.convert("RGB").crop(window).save(out_path)
    return out_path, (window[0], window[1]), size


def door_margin(size) -> int:
    """How far outside a boundary the door crop reaches.

    A doorway is painted on the wall's OUTER face and straddles the outline, so a crop taken
    exactly at the boundary cuts it in half and SAM is asked to find something that is only
    partly in the picture. Proportional to the building, floored so a small one still gets a
    usable margin.
    """
    return max(40, int(0.05 * min(size)))


@dataclass
class BuildingScan:
    """Stage A: one untiled pass over one located building's crop, before any threshold.

    Split from its thresholds for the same reason `Located` is: the pass costs GPU time, and
    the score floor is a thing you will want to change your mind about once you have seen the
    result. `filtered` is pure, so changing it costs nothing.
    """

    candidate: Candidate             # what `locate` handed over
    hits: list                       # every match for the object prompt, crop-local
    origin: tuple                    # the crop's top-left, in level coordinates
    crop_path: Path
    crop_size: tuple

    def best_score(self) -> float:
        return max((float(h.get("confidence", 0.0)) for h in self.hits), default=0.0)

    def filtered(self, min_confidence: float = MIN_CONFIDENCE) -> list:
        """Threshold -> buildings, in full-resolution level coordinates.

        Biggest first, and only a hit that is somewhere new. SAM returns the same building
        several times at different scores; without the overlap check every duplicate becomes
        its own building with its own spec, its own wall-thickness question and its own
        interior -- which is how four pyramids once became fourteen.
        """
        hits = [h for h in self.hits if float(h.get("confidence", 0.0)) >= min_confidence]
        # No area floor here. Inside its own crop a real building is most of the frame, and a
        # small hit is exactly the second building of a fusion -- what this pass is for.
        accepted = []
        for hit in sorted(hits, key=lambda h: _area(_points_of(h)), reverse=True):
            points = _points_of(hit, self.origin)
            if any(_overlaps(points, kept) for _, kept in accepted):
                continue
            accepted.append((hit, points))

        out = []
        for position, (hit, points) in enumerate(accepted):
            out.append(Candidate(
                index=self.candidate.index,
                name=_suffixed(self.candidate.name, position),
                silhouette=points,
                confidence=float(hit.get("confidence", 0.0)),
                approximate=False,
                parent=self.candidate.name,
            ))
        if len(out) > 1:
            for one in out:
                one.notes = one.notes + (
                    f"{self.candidate.name} was {len(out)} buildings touching at map scale",)
        return out


@dataclass
class DoorScan:
    """Stage B: one untiled pass over one building's crop, looking for its entrance."""

    building_name: str
    hits: list                       # every match for the entrance prompt, crop-local
    origin: tuple
    crop_path: Path
    crop_size: tuple
    prompt: str

    @property
    def crop_area(self) -> float:
        return float(self.crop_size[0] * self.crop_size[1])

    def filtered(self, min_confidence: float = MIN_CONFIDENCE,
                 min_area_fraction: float = ENTRANCE_MIN_AREA_FRACTION,
                 max_area_fraction: float = ENTRANCE_MAX_AREA_FRACTION) -> list:
        """Thresholds -> entrance polygons in level coordinates. Pure.

        The ceiling is not optional here: the highest-scoring match is reliably the whole
        building, and without it every door lands in the middle of its own room.
        """
        floor = min_area_fraction * self.crop_area
        ceiling = max_area_fraction * self.crop_area
        return _offset([e for e in self.hits
                        if float(e.get("confidence", 0.0)) >= min_confidence
                        and floor <= _area(_points_of(e)) <= ceiling], self.origin)

    def spread(self, min_confidence: float, min_area_fraction: float,
               max_area_fraction: float) -> str:
        """What the thresholds are choosing between, so a change is an informed one."""
        if not self.hits:
            return f"  {self.building_name}: no {self.prompt!r} matches at all"
        scored = [h for h in self.hits if float(h.get("confidence", 0.0)) >= min_confidence]
        biggest = max(_area(_points_of(h)) / self.crop_area for h in self.hits)
        return (f"  {self.building_name}: {len(self.hits)} raw, {len(scored)} above "
                f"{min_confidence}, biggest {biggest:.1%} of the crop")


def scan_building(candidate: Candidate, image_path: Path, object_prompt: str, work: Path,
                  *, tile: bool = False, rescan: bool = False) -> BuildingScan:
    """Stage A: crop this building at full resolution and segment it once, untiled.

    Untiled because tiling buys nothing at this size. SAM resizes whatever it is given to
    MODEL_EDGE, so a 4058 px crop sent whole comes back accurate to ~7 px -- 0.2% of a 3730 px
    pyramid, about a twentieth of a character. Tiling the same crop to hold 1:1 pixels costs
    63 tiles to recover 6 of those pixels.
    """
    image_path, work = Path(image_path), Path(work)
    with Image.open(image_path) as level:
        level_size = level.size
    window = _window(candidate.bbox, refine_pad(level_size), level_size)
    crop_path, origin, size = _crop(image_path, window, work / f"{candidate.name}_refine.png")

    polygons = sam_local.segment(crop_path, [object_prompt], work, tile=tile,
                                 chunk_id=f"refine_{candidate.name}", rescan=rescan)
    return BuildingScan(candidate=candidate, hits=_matching(polygons, object_prompt),
                        origin=origin, crop_path=crop_path, crop_size=size)


def scan_door(building: Candidate, image_path: Path, entrance_prompt: str, work: Path,
              *, tile: bool = False, rescan: bool = False) -> DoorScan:
    """Stage B: crop this one building and segment it once, for its entrance.

    Per building rather than per located blob: when a fusion comes apart in stage A, this is
    what stops a door being attributed to the neighbour it happened to sit nearer.
    """
    image_path, work = Path(image_path), Path(work)
    with Image.open(image_path) as level:
        level_size = level.size
    window = _window(building.bbox, door_margin(building.size), level_size)
    crop_path, origin, size = _crop(image_path, window, work / f"{building.name}_door.png")

    polygons = sam_local.segment(crop_path, [entrance_prompt], work, tile=tile,
                                 chunk_id=f"door_{building.name}", rescan=rescan)
    return DoorScan(building_name=building.name, hits=_matching(polygons, entrance_prompt),
                    origin=origin, crop_path=crop_path, crop_size=size,
                    prompt=entrance_prompt)


def attach_doors(buildings: list, scans: dict, *, min_confidence: float = MIN_CONFIDENCE,
                 min_area_fraction: float = ENTRANCE_MIN_AREA_FRACTION,
                 max_area_fraction: float = ENTRANCE_MAX_AREA_FRACTION) -> None:
    """Re-apply the door thresholds over cached scans and re-pair. Idempotent.

    Clears first, so raising a floor and lowering it again leaves no stale door behind. The
    loop this serves is expected to go both ways.
    """
    for building in buildings:
        building.door_point = None
        building.door_rule = ""
        building.door_polygon = None
        building.door_options = ()
        building.door_choice = 0
        building.door_size = None
        building.door_confidence = 0.0
        building.door_distance = float("-inf")
        building.entrance_candidates = 0
        building.notes = tuple(n for n in building.notes if "has to be placed by hand" not in n)
        scan = scans.get(building.name)
        if scan is None:
            continue
        pair_entrances([building], scan.filtered(min_confidence, min_area_fraction,
                                                 max_area_fraction))
        if building.door_point is None:
            building.notes = building.notes + (
                f"no {scan.prompt!r} found; the door has to be placed by hand",)


# ---------------------------------------------------------------- showing them to you

def table(candidates: list, doors: bool = True) -> str:
    """The validation gate, as text. Everything on it is free to compute.

    Sizes from `locate` are approximate and say so: they are what you choose from, not what
    gets built. `refine` replaces them with measured ones.
    """
    approximate = any(c.approximate for c in candidates)
    # `doors=False` means the door pass has not run yet, which is not the same as a door not
    # being found. Printing NOT FOUND before anything has looked is just a lie with a column
    # heading on it.
    header = ("(entrance found during refine)" if approximate else
              "entrance" if doors else "(doors not searched yet)")
    lines = [f"{'#':>3}  {'name':<16} {'size px':>13} {'area MP':>8} {'conf':>5}  {header}",
             f"{'':>3}  {'-' * 16} {'-' * 13:>13} {'-' * 8:>8} {'-' * 5:>5}  {'-' * 24}"]
    for c in candidates:
        w, h = c.size
        entrance = "" if (c.approximate or not doors) else (c.door_rule or "NOT FOUND")
        if c.door_point and c.door_size:
            entrance += f"  {c.door_size[0]}x{c.door_size[1]} @{c.door_confidence:.2f}"
        if c.entrance_candidates > 1:
            entrance += f"  ({c.entrance_candidates} matched)"
        about = "~" if c.approximate else " "
        lines.append(f"{c.index:>3}  {c.name:<16}{about}{w:>5} x {h:<4} {c.area / 1e6:>8.2f} "
                     f"{c.confidence:>5.2f}  {entrance}")
        if c.iou is not None:
            verdict = "agrees" if c.iou >= 0.8 else "DISAGREES"
            lines.append(f"{'':>3}  IoU {c.iou:.3f} vs {c.fragments} polygon(s) already on "
                         f"the map -- {verdict}")
        for note in c.notes:
            lines.append(f"{'':>3}  note: {note}")
    if approximate:
        lines.append("")
        lines.append("  ~ found from a whole-map view, so sizes are rough. Each one you pick "
                     "is re-segmented")
        lines.append("    at full resolution, which is where the exact outline and the "
                     "entrance come from.")
    return "\n".join(lines)


VIEW_WIDTH = 2600


def numbered_overlay(image_path: Path, candidates: list, out_path: Path,
                     view_width: int = VIEW_WIDTH) -> Path:
    """The table's picture: only the candidates, numbered to match the rows you choose from.

    Drawn on a shrunk copy, and that is the whole point. At full resolution this map is
    22473 px wide and 242 MB; an outline on it is a hair's width on screen and the file takes
    a minute to open, so the overlay looks empty and is useless for the one job it has. Lines
    are widened to match the shrink, so they read the same whatever the level's size.
    """
    from PIL import ImageDraw

    with Image.open(image_path) as source:
        scale = min(1.0, view_width / source.width)
        image = (source.convert("RGB") if scale == 1.0 else
                 source.convert("RGB").resize(
                     (int(source.width * scale), int(source.height * scale)), Image.LANCZOS))

    draw = ImageDraw.Draw(image)
    for c in candidates:
        points = [(x * scale, y * scale) for x, y in c.silhouette]
        draw.line(points + [points[0]], fill=(0, 255, 120), width=4)
        left = min(p[0] for p in points)
        top = min(p[1] for p in points)
        draw.text((left, max(0, top - 14)),
                  f"{c.index}  {c.confidence:.2f}", fill=(255, 255, 0))
        if c.door_point:
            x, y = c.door_point[0] * scale, c.door_point[1] * scale
            draw.ellipse([x - 10, y - 10, x + 10, y + 10], outline=(80, 220, 255), width=3)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # A viewer holding the previous copy open makes the same filename unwritable on Windows,
    # and re-using it also means the viewer may still be showing the old picture. A fresh name
    # per redraw sidesteps both -- these are scratch files in a work directory.
    try:
        image.save(out_path)
        return out_path
    except OSError:
        stem, suffix = out_path.stem, out_path.suffix
        for attempt in range(1, 100):
            alternative = out_path.with_name(f"{stem}_{attempt:02d}{suffix}")
            try:
                image.save(alternative)
                return alternative
            except OSError:
                continue
        raise


CELL = 520


def outline_image(candidate: Candidate, crop_path: Path, origin, cell: int = CELL):
    """One building, framed and drawn, scaled into a cell.

    Framed on the BUILDING, not on the crop it came from. A stage-A crop is cut around the
    located blob, so a small building inside it -- the second half of a fusion, or a sliver
    you are deciding whether to drop -- is a speck in a mostly empty frame, which is useless
    for the one judgement this picture exists to support.

    Crop-local drawing: the candidate's coordinates are in level space and the crop is a
    window onto it, so the origin comes off before anything is drawn. Getting that subtraction
    wrong puts the outline somewhere else entirely, which is why it happens in one place.
    """
    from PIL import ImageDraw

    left, top, right, bottom = candidate.bbox
    margin = max(20, int(0.15 * max(right - left, bottom - top)))
    with Image.open(crop_path) as source:
        window = (max(0, int(left - origin[0]) - margin),
                  max(0, int(top - origin[1]) - margin),
                  min(source.width, int(math.ceil(right - origin[0])) + margin),
                  min(source.height, int(math.ceil(bottom - origin[1])) + margin))
        framed = source.convert("RGB").crop(window)
    scale = min(cell / max(1, framed.width), cell / max(1, framed.height))
    image = framed.resize((max(1, int(framed.width * scale)),
                           max(1, int(framed.height * scale))), Image.LANCZOS)

    # Two shifts, applied in order: level -> crop, then crop -> framed window.
    def to_image(point):
        return ((point[0] - origin[0] - window[0]) * scale,
                (point[1] - origin[1] - window[1]) * scale)

    draw = ImageDraw.Draw(image)
    points = [to_image(p) for p in candidate.silhouette]
    draw.line(points + [points[0]], fill=(0, 255, 120), width=3)
    if candidate.door_polygon:
        # The doorway SAM found, drawn as the shape it is. A marker at its centroid says
        # nothing about whether the match was a doorway or the whole building.
        door = [to_image(p) for p in candidate.door_polygon]
        draw.line(door + [door[0]], fill=(80, 220, 255), width=3)
    elif candidate.door_point:
        x, y = to_image(candidate.door_point)
        draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(80, 220, 255), width=3)
    return image


def contact_sheet(buildings: list, crops: dict, out_path: Path, cell: int = CELL) -> Path:
    """Every building in one picture, so a review is one window rather than N.

    Each cell is that building's own crop, so a 128x42 sliver and a 3731x2945 pyramid are both
    legible -- which is the point, because the sliver is the one you are deciding to drop.
    """
    from PIL import ImageDraw

    if not buildings:
        raise ValueError("nothing to show")
    columns = min(4, len(buildings))
    rows = (len(buildings) + columns - 1) // columns
    label = 22
    sheet = Image.new("RGB", (columns * cell, rows * (cell + label)), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)

    for position, building in enumerate(buildings):
        crop_path, origin = crops[building.name]
        tile_image = outline_image(building, crop_path, origin, cell)
        left = (position % columns) * cell + (cell - tile_image.width) // 2
        top = (position // columns) * (cell + label) + label
        sheet.paste(tile_image, (left, top))
        # The door's own size and score, not just "found": a doorway the size of the building
        # is what a bad match looks like, and that is only visible as a number next to the
        # building's own size.
        if building.door_point and building.door_size:
            door = (f"door {building.door_size[0]}x{building.door_size[1]} "
                    f"@{building.door_confidence:.2f}")
        elif building.door_point:
            door = "door"
        else:
            door = "NO DOOR"
        draw.text(((position % columns) * cell + 4,
                   (position // columns) * (cell + label) + 6),
                  f"{position + 1}. {building.name} {building.confidence:.2f}  "
                  f"{building.size[0]}x{building.size[1]}   {door}",
                  fill=(255, 255, 0) if building.door_point else (255, 140, 140))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        sheet.save(out_path)
        return out_path
    except OSError:
        for attempt in range(1, 100):
            alternative = out_path.with_name(f"{out_path.stem}_{attempt:02d}{out_path.suffix}")
            try:
                sheet.save(alternative)
                return alternative
            except OSError:
                continue
        raise


def parse_selection(answer: str, candidates: list) -> list:
    """"1,3" or "all" or "" -> the candidates you picked."""
    answer = (answer or "").strip().lower()
    if not answer or answer == "all":
        return list(candidates)
    by_index = {c.index: c for c in candidates}
    picked = []
    for piece in answer.replace(" ", ",").split(","):
        if not piece:
            continue
        if not piece.isdigit() or int(piece) not in by_index:
            raise ValueError(f"{piece!r} is not one of the numbers listed")
        picked.append(by_index[int(piece)])
    return picked
