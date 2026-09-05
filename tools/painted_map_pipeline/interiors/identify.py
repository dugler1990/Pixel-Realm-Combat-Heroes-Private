"""The two interviewed answers -> silhouette polygon and threshold segment.

You say what the object is and how its entrance looks; this turns those two sentences into
the only two pieces of geometry the rest of the pipeline reads. Everything else -- the
canvas, the scale, the door's inward normal, the arch quad -- follows from them.

Keyed on a provider like `image_client.make_image_client` and `region_proposer`, with an
offline default so the whole command surface runs with no API key:

  tmx    read the polygon and door already authored on the map. The calibration case, and
         the right answer whenever a building has been drawn by hand in Tiled.
  sam3   segment them out of the exterior art with the two text prompts, through the
         Roboflow workflow the collision pass already uses -- `sam3_prompts` in
         `sam3.<level>.json` already carries "pyramid".

SAM3's own gate is the interesting part. Where the collision pass has already run, every
building it caught is a polygon on the map carrying `sam3_class`, so a new silhouette can be
scored against the union of matching obstacles. That number alone is not enough: the culls
can drop a building or split it, so the fragment count is reported beside the IoU. A
building coming back as five polygons is itself the finding.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..world_levels.geometry import largest_connected_component, mask_to_polygon
from ..world_levels.masks import rasterize_polygon
from .runtime import building_geometry


@dataclass(frozen=True)
class Identified:
    """What the two answers resolved to, plus how much to trust it."""

    silhouette: tuple           # world px
    door_point: tuple = None    # world px, projected onto the silhouette by the caller
    source: str = "tmx"
    iou: float = None           # against SAM3 obstacles of the same class, when available
    fragments: int = 0          # how many polygons that reference came back as
    notes: tuple = ()

    def report(self) -> str:
        lines = [f"  source      {self.source}",
                 f"  silhouette  {len(self.silhouette)} vertices"]
        if self.door_point:
            lines.append(f"  entrance    world {tuple(int(v) for v in self.door_point)}")
        else:
            lines.append("  entrance    NOT FOUND -- re-prompt, or click it yourself")
        if self.iou is not None:
            verdict = "agrees" if self.iou >= 0.8 else "DISAGREES"
            lines.append(f"  agreement   IoU {self.iou:.3f} vs {self.fragments} "
                         f"{'polygon' if self.fragments == 1 else 'polygons'} "
                         f"already on the map -- {verdict}")
            if self.fragments > 1:
                lines.append("              the reference is fragmented; the culls split it, "
                             "so treat the IoU as a hint, not a verdict")
        for note in self.notes:
            lines.append(f"  note        {note}")
        return "\n".join(lines)


# ---------------------------------------------------------------- providers

def _properties(obj):
    return {p.get("name"): p.get("value") for p in obj.findall("properties/property")}


def _world_polygon(obj):
    ox, oy = float(obj.get("x", 0)), float(obj.get("y", 0))
    node = obj.find("polygon")
    if node is not None:
        pairs = (point.split(",") for point in node.get("points").split())
        return tuple((ox + float(px), oy + float(py)) for px, py in pairs)
    w, h = float(obj.get("width", 0)), float(obj.get("height", 0))
    return ((ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h))


def from_tmx(map_path: Path, building: str) -> Identified:
    """The authored polygon and door. No model, no key."""
    root = ET.parse(map_path).getroot()
    objects = [o for group in root.iter("objectgroup") for o in group.findall("object")]
    target = next((o for o in objects if o.get("name") == building), None)
    if target is None:
        raise ValueError(f"no object named {building!r} in {map_path}")
    props = _properties(target)
    door = None
    if props.get("door_x") and props.get("door_y"):
        door = (float(props["door_x"]), float(props["door_y"]))
    return Identified(silhouette=_world_polygon(target), door_point=door, source="tmx")


def sam3_reference(map_path: Path, sam3_class: str, near) -> tuple:
    """Obstacles already on the map that SAM3 gave this class, near `near`.

    `merge_polygon_obstacles` writes `sam3_class` onto everything it merges, so wherever the
    collision pass has run there is a second, independent opinion about where this building
    is -- and it costs nothing to ask.
    """
    root = ET.parse(map_path).getroot()
    left, top, right, bottom = _bbox(near)
    matches = []
    for group in root.iter("objectgroup"):
        for obj in group.findall("object"):
            if _properties(obj).get("sam3_class", "").strip().lower() != sam3_class.lower():
                continue
            polygon = _world_polygon(obj)
            l, t, r, b = _bbox(polygon)
            if r < left or l > right or b < top or t > bottom:
                continue
            matches.append(polygon)
    return tuple(matches)


def _bbox(polygon):
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_iou(a, polygons, scale=8) -> float:
    """IoU of one polygon against the union of several, rasterised at 1/scale.

    Coarse on purpose: this decides whether two outlines describe the same building, which
    does not need pixel accuracy and should not cost a 3600 px raster to answer.
    """
    if not polygons:
        return None
    every = [a] + list(polygons)
    left = min(_bbox(p)[0] for p in every)
    top = min(_bbox(p)[1] for p in every)
    right = max(_bbox(p)[2] for p in every)
    bottom = max(_bbox(p)[3] for p in every)
    size = (max(1, int((right - left) / scale)), max(1, int((bottom - top) / scale)))
    shift = lambda p: tuple(((x - left) / scale, (y - top) / scale) for x, y in p)  # noqa: E731

    mine = np.asarray(rasterize_polygon(size, shift(a))) > 0
    theirs = np.zeros_like(mine)
    for polygon in polygons:
        theirs |= np.asarray(rasterize_polygon(size, shift(polygon))) > 0
    union = int((mine | theirs).sum())
    return float((mine & theirs).sum()) / union if union else 0.0


def from_sam3(roof_path: Path, origin, object_prompt: str, entrance_prompt: str,
              config: dict, work: Path) -> Identified:
    """Segment the silhouette and the entrance out of the exterior art.

    The workflow is prompt-driven and its prompt list lives in the level's sam3 config, so
    adding an entrance is a config line rather than code. What comes back is masks; the
    silhouette is the largest component of the object's, and the entrance is the centroid of
    its own -- a point, because the caller projects it onto the silhouette edge to get a
    threshold, and a blob cannot be projected.
    """
    from ..collision.sam3.roboflow_workflow import extract_polygons, run_workflow

    notes = []
    result = run_workflow(Path(roof_path), config)
    polygons = extract_polygons(result)
    if not polygons:
        raise ValueError(
            f"SAM3 returned no polygons for {roof_path.name}. Check that {object_prompt!r} "
            f"is in this level's sam3_prompts.")

    def _for(prompt):
        return [p for p in polygons
                if str(p.get("class", "")).strip().lower() == prompt.strip().lower()]

    object_hits = _for(object_prompt)
    if not object_hits:
        raise ValueError(f"SAM3 found nothing it called {object_prompt!r}; it returned "
                         f"{sorted({str(p.get('class')) for p in polygons})}")
    if len(object_hits) > 1:
        notes.append(f"{len(object_hits)} matches for {object_prompt!r}; kept the largest")
    silhouette = max((tuple((float(x) + origin[0], float(y) + origin[1])
                            for x, y in hit["points"]) for hit in object_hits),
                     key=_area)

    door_point = None
    entrance_hits = _for(entrance_prompt) if entrance_prompt else []
    if entrance_hits:
        points = [(float(x) + origin[0], float(y) + origin[1])
                  for x, y in entrance_hits[0]["points"]]
        door_point = (sum(p[0] for p in points) / len(points),
                      sum(p[1] for p in points) / len(points))
        if len(entrance_hits) > 1:
            notes.append(f"{len(entrance_hits)} entrances found; kept the first")
    else:
        notes.append(f"no match for {entrance_prompt!r} -- SAM3 did not find the entrance")

    return Identified(silhouette=silhouette, door_point=door_point, source="sam3",
                      notes=tuple(notes))


def _area(polygon) -> float:
    """Shoelace. Only used to pick the biggest of several matches."""
    total = 0.0
    for i in range(len(polygon)):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def gate(identified: Identified, map_path: Path, object_prompt: str) -> Identified:
    """Score a silhouette against SAM3 obstacles of the same class, when there are any."""
    reference = sam3_reference(Path(map_path), object_prompt, identified.silhouette)
    if not reference:
        return Identified(
            **{**identified.__dict__,
               "notes": identified.notes + (
                   "no SAM3 obstacles of this class on the map to check against; "
                   "the intrinsic checks and your eye are the gate",)})
    return Identified(
        **{**identified.__dict__,
           "iou": polygon_iou(identified.silhouette, reference),
           "fragments": len(reference)})


def door_plane(silhouette, door_point):
    """Threshold origin, inward normal and arch quad -- the same call the game makes."""
    if door_point is None:
        return None, None, ()
    return building_geometry().door_plane_from_polygon(silhouette, door_point)


def identify(map_path: Path, building: str, object_prompt: str = "", entrance_prompt: str = "",
             provider: str = "tmx", **kwargs) -> Identified:
    if provider in {"", "tmx", "authored"}:
        found = from_tmx(Path(map_path), building)
    elif provider == "sam3":
        found = from_sam3(entrance_prompt=entrance_prompt, object_prompt=object_prompt, **kwargs)
    else:
        raise ValueError(
            f"identify provider {provider!r} is not implemented. Use 'tmx' (offline default) "
            f"or 'sam3', or add a new provider here.")
    return gate(found, map_path, object_prompt) if object_prompt else found
