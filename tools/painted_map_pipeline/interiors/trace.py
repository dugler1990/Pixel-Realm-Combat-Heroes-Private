"""Flat-class plan painting -> geometry.

The plan pass paints two classes over the exterior art: walkable FLOOR and the solid mass
around it. Everything downstream reads the trace of that painting rather than the painting
itself, so the collision quads, the chamber and the render pass's control image are all the
same few polygons.

Two departures from ``world_levels.region_proposer``, which traces the same way for map
chunks:

``_partition_masks`` there assigns every non-black pixel to its NEAREST palette colour with
no tolerance gate. That is right for a chunk painted on black, where every pixel is meant to
be repainted. Here the model paints on top of finished masonry, so an area it simply left
alone would be silently classified as floor or solid by whichever palette colour its browns
happen to sit closer to -- a model that ignored the instruction would score as a valid plan.
``partition_with_reject`` gates on distance-to-nearest instead, and what falls outside is
reported as unpainted rather than assigned.

``mask_to_polygon`` there returns the largest external contour of the largest component. The
collision emitter needs every boundary, holes included: a solid pillar standing in a room is
a hole in the floor and has to stop the player. ``trace_boundaries`` keeps the hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..world_levels.geometry import dilate_mask

# Two classes, both drawn from the palette region_proposer already paints and names, so the
# prompt vocabulary stays "magenta"/"green" across the project. Chosen far from masonry: an
# unrepainted sandstone pixel sits ~140 away from either, well outside REJECT_DISTANCE.
FLOOR_RGB = (200, 70, 210)
SOLID_RGB = (50, 200, 80)
CLASS_COLOURS = {"floor": FLOOR_RGB, "solid": SOLID_RGB}
CLASS_NAMES = {"floor": "magenta", "solid": "green"}

# Euclidean RGB distance beyond which a pixel counts as "not repainted". Sandstone measures
# ~137-141 from the nearer class colour; a flat fill that has been through PNG and a resize
# stays within ~40. 100 separates them with room either side.
REJECT_DISTANCE = 100.0


@dataclass(frozen=True)
class Partition:
    """Class masks over the region the model was asked to repaint, plus what it didn't."""

    masks: dict          # class name -> boolean mask
    reject: np.ndarray   # asked-for but not repainted
    considered: np.ndarray

    @property
    def unpainted_fraction(self) -> float:
        """Share of the asked-for region the model left alone. The first thing to check:
        a high number means the plan is not a plan, whatever else measures well."""
        asked = int(self.considered.sum())
        return float(self.reject.sum()) / asked if asked else 0.0


@dataclass(frozen=True)
class ComponentReport:
    """Connected components of a mask, keeping what ``largest_connected_component`` drops.

    That helper takes the biggest and discards the rest silently, so "exactly one region"
    can only ever be asserted, never measured. ``runner_up_ratio`` makes it a number: 0.0 is
    a single clean component, 0.4 is a plan with a second room floating unattached.
    """

    count: int
    largest: np.ndarray
    largest_area: int
    runner_up_ratio: float


def partition_with_reject(painted, considered, palette=None, max_distance=REJECT_DISTANCE):
    """Classify `considered` pixels of `painted` by nearest palette colour, with a gate.

    `painted` is RGB uint8, `considered` the boolean mask of what the model was asked to
    repaint (the editable region). Pixels further than `max_distance` from every class
    colour land in `reject` and in no class mask, so the masks are disjoint but -- unlike
    region_proposer's -- do not necessarily cover.
    """
    palette = palette or CLASS_COLOURS
    pixels = np.asarray(painted)[:, :, :3].astype(np.int32)
    names = list(palette)
    distances = np.stack(
        [((pixels - np.asarray(palette[name], dtype=np.int32)) ** 2).sum(axis=2)
         for name in names],
        axis=0,
    )
    nearest = distances.argmin(axis=0)
    closest = np.sqrt(distances.min(axis=0))
    painted_enough = considered & (closest <= max_distance)
    return Partition(
        masks={name: painted_enough & (nearest == index) for index, name in enumerate(names)},
        reject=considered & ~painted_enough,
        considered=considered,
    )


def component_report(mask, min_area: int = 0) -> ComponentReport:
    """Component count, the largest one, and how big the runner-up is relative to it.

    `min_area` drops specks before counting. Erosion needs it: a corridor junction has a
    locally larger inscribed disk than either arm, so it leaves a handful of pixels behind
    when both arms have been eaten away -- and an unfiltered count reports every junction in
    the dungeon as a room.
    """
    u8 = np.ascontiguousarray(mask.astype(np.uint8))
    number, labels = cv2.connectedComponents(u8, connectivity=8)
    sizes = sorted(
        ((int(np.count_nonzero(labels == label)), label) for label in range(1, number)),
        reverse=True,
    )
    sizes = [item for item in sizes if item[0] >= min_area]
    if not sizes:
        empty = np.zeros_like(mask, dtype=bool)
        return ComponentReport(0, empty, 0, 0.0)
    largest_area, largest_label = sizes[0]
    runner_up = sizes[1][0] if len(sizes) > 1 else 0
    return ComponentReport(
        count=len(sizes),
        largest=labels == largest_label,
        largest_area=largest_area,
        runner_up_ratio=runner_up / largest_area if largest_area else 0.0,
    )


def derive_art_classes(floor, chamber, thickness):
    """floor / wall / solid from the floor mask alone.

    Only floor has a meaning that can be checked, so only floor is worth painting. Wall is
    the band the emitter will lay collision quads along, so deriving it by the same dilation
    the emitter uses for its thickness makes the control image's wall band identical by
    construction to where the collision actually is -- rather than something the render pass
    is asked to match and re-prompted when it doesn't.
    """
    floor = floor & chamber
    wall = dilate_mask(floor, int(thickness)) & ~floor & chamber
    return {"floor": floor, "wall": wall, "solid": chamber & ~floor & ~wall}


@dataclass(frozen=True)
class Boundary:
    polygon: tuple  # canvas-local px
    is_hole: bool


def trace_boundaries(mask, epsilon_frac: float = 0.01, min_area: int = 64) -> list[Boundary]:
    """Every contour of `mask` as a simplified polygon, outers and holes alike.

    Douglas-Peucker tolerance is a fraction of each contour's own perimeter, matching
    ``mask_to_polygon``, so a small side room is not simplified by a corridor's yardstick.
    """
    u8 = np.ascontiguousarray(mask.astype(np.uint8) * 255)
    contours, hierarchy = cv2.findContours(u8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if not contours or hierarchy is None:
        return []
    out: list[Boundary] = []
    for index, contour in enumerate(contours):
        if cv2.contourArea(contour) < min_area:
            continue
        epsilon = max(1.0, epsilon_frac * cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        points: list[tuple[int, int]] = []
        for x, y in approx:
            point = (int(x), int(y))
            if not points or points[-1] != point:
                points.append(point)
        if len(points) >= 2 and points[0] == points[-1]:
            points.pop()
        if len(points) < 3:
            continue
        # RETR_CCOMP is two-level: parent -1 is an outer boundary, anything else is a hole.
        out.append(Boundary(tuple(points), is_hole=int(hierarchy[0][index][3]) != -1))
    return out


def to_world(polygon, origin):
    """Canvas-local polygon -> world px."""
    return tuple((x + origin[0], y + origin[1]) for x, y in polygon)
