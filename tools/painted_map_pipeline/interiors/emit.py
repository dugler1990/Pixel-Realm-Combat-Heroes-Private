"""An accepted interior -> its objects in the shipped map.

The room walls are the ones SAM3 found in the painting (`sam_room.sam_walls`), and the same
polygons are what sight stops at. The shell -- a strip `spec.wall` wide inside the building's
outline, minus the walkable ground -- the chamber and the door frame still come from the plan.

The shell pieces are as big as a map polygon allows, not cut short. The engine pushes a body
away from a piece's bounding-box centre, which on a big piece can sit inside a room; that is a
known cost, left for now.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..world_levels.geometry import mask_to_polygon
from .plan import door_mask, geometry_masks
from .player_size import player_size
from .trace import to_world

# Every shell piece and the chamber are outlined to within a pixel of their mask.
PIECE_TOLERANCE_PX = 1.0
CHAMBER_TOLERANCE_PX = 1.0
# A piece smaller than this is a speck of the mask, not a wall anyone could meet.
MIN_PIECE_PX = 16
# A pocket of walkable ground smaller than this (20 x 20 px) is a speck nobody can stand in,
# so it is filled rather than cut around. On pyramid_01 a 2 px one at the door frame's jagged
# edge split the outer wall into 17 pieces.
MIN_POCKET_PX = 400


def chamber_mask_from_plan(plan) -> np.ndarray:
    """The room, as a mask in plan-local pixels: floor and walls, never the door.

    This is the hole in the roof, the trigger for "inside", and the shape the interior
    art is clipped to, so it is what you SEE of the painting. Floor: where you walk. Wall:
    stone that is part of the room picture -- for a request plan the partitions
    `derive_art_classes` grew from the floor, for the traced plan the walls the model
    painted, named as such by the floor pass. The blue class, the building's outside
    face, is never in it: wherever the render repainted the pyramid, the map shows.

    The door is subtracted here and nowhere else. In play its exterior pixels are drawn
    over the player as a canopy, so a hole there would show the model's own doorway
    underneath the map's -- two doors.
    """
    return (plan.classes["floor"] | plan.classes["wall"]) & ~door_mask(plan.spec)


def chamber_from_plan(plan) -> tuple:
    """The chamber as one world polygon. See `chamber_mask_from_plan`.

    Outlined to within a pixel. It was 0.4% of the perimeter -- 60 px on a three-room plan
    -- and this is the roof hole and the trigger for "inside", so the room you saw and the
    room you were in disagreed by that much, and the hole reached over the painted door.
    Following the edge that closely costs thousands of vertices; the engine turns the
    polygon into a mask once at load, so only the map file grows.
    """
    occupied = chamber_mask_from_plan(plan)
    if not occupied.any():
        raise ValueError("plan has no floor: nothing to derive a chamber from")
    contours, _ = cv2.findContours(np.ascontiguousarray(occupied.astype(np.uint8)),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    points = cv2.approxPolyDP(contour, CHAMBER_TOLERANCE_PX, True).reshape(-1, 2)
    if len(points) < 3:
        raise ValueError("the chamber outline collapsed to fewer than three points")
    return to_world([(int(x), int(y)) for x, y in points], plan.spec.origin)


def _grow(mask, radius) -> np.ndarray:
    """`mask` grown outward by `radius` px: every pixel within that distance of it."""
    distance = cv2.distanceTransform(np.ascontiguousarray((~mask).astype(np.uint8)),
                                     cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return distance <= radius


def _shrink(mask, radius) -> np.ndarray:
    """`mask` shrunk inward by `radius` px. Padded so the canvas edge counts as outside: the
    canvas is the silhouette's bounding box, so the silhouette touches all four sides."""
    padded = np.pad(mask.astype(np.uint8), 1)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[1:-1, 1:-1]
    return distance > radius


def _sweep_length(plan, door) -> int:
    """Px from the door polygon's inner edge to the first floor pixel, along the door line.
    0 when there is no floor on the line, or no door on it before the floor."""
    first = _first_floor(plan)
    if first is None:
        return 0
    ox, oy = plan.spec.door_origin
    ix, iy = plan.spec.door_inward
    last = None
    for step in range(first[0]):
        if door[int(round(oy + iy * step)), int(round(ox + ix * step))]:
            last = step
    return 0 if last is None else first[0] - last


def walkable_mask(plan) -> np.ndarray:
    """Where a body may stand inside the building: the floor, and the way in to it.

    The way in is the door polygon dragged inward along the door line until it meets the
    floor, so it is door-wide the whole way. It replaces a disc: every wall within the gate's
    gap plus 8 px of the door used to be dropped -- ~385 px on a floor that stops short --
    which opened the pyramid's face on either side of the frame.
    """
    door = door_mask(plan.spec)
    if not plan.spec.door_origin or not door.any():
        return plan.floor.copy()
    return plan.floor | _dragged(door, plan.spec.door_inward, _sweep_length(plan, door))


def _dragged(mask, direction, length) -> np.ndarray:
    """`mask` dragged `length` px along `direction`: every place it passes through."""
    out = mask.copy()
    ys, xs = np.nonzero(mask)
    h, w = mask.shape
    for t in range(1, int(length) + 1):
        nx, ny = xs + int(round(direction[0] * t)), ys + int(round(direction[1] * t))
        inside = (nx >= 0) & (nx < w) & (ny >= 0) & (ny < h)
        out[ny[inside], nx[inside]] = True
    return out


# How far the door's frame -- lintel and jambs -- reaches past the opening, in canvas px.
# A starting guess at a jamb's width on pyramid_01's art; tune it on the walkthrough strip.
DOOR_FRAME_PX = 48


def door_frame_mask(spec) -> np.ndarray:
    """The door's frame: the stone round the opening, drawn over a body passing under it.

    This is what the map's door object is, and the game draws it over the player once his
    feet are past the door line. It used to be SAM's door shape itself -- the dark opening
    and its floor -- so a body standing in the doorway vanished, and the lintel, which was
    not in it, never covered anyone. The opening is left out, and so is everything in front
    of it (the opening dragged outward), which is ground the body has not reached yet.
    """
    opening = door_mask(spec)
    if not opening.any():
        return opening
    silhouette = geometry_masks(spec)[0]
    frame = _grow(opening, DOOR_FRAME_PX) & ~opening & silhouette
    if spec.door_inward:
        outward = (-spec.door_inward[0], -spec.door_inward[1])
        frame &= ~_dragged(opening, outward, DOOR_FRAME_PX + 2)
    return frame


def shell_mask(plan, walkable=None) -> np.ndarray:
    """The building's own wall: a strip `spec.wall` wide inside the outline, minus the
    walkable ground, so its one opening is the way in, exactly door-wide. (The floor does
    reach into this strip: the chamber carves a passage through the shell to the door.)

    Without it the pyramid's face was walkable ground as far as the engine knew, and the
    player strolled a shell's thickness up it before meeting a room wall from the wrong side.
    """
    walkable = walkable_mask(plan) if walkable is None else walkable
    thickness = plan.spec.wall or plan.spec.partition
    return plan.silhouette & ~_shrink(plan.silhouette, thickness) & ~walkable


def shell_pieces(plan, walkable=None) -> list:
    """`shell_mask` as world polygons the map can hold."""
    walkable = walkable_mask(plan) if walkable is None else walkable
    return _pieces(shell_mask(plan, walkable), walkable, plan.spec.origin)


def _filled(mask, walkable) -> np.ndarray:
    """`mask` with every pocket it encloses filled in, unless there is ground to stand on in
    it. Stone nobody can reach is solid anyway, and filling it saves cutting round it."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        np.ascontiguousarray((~mask).astype(np.uint8)), connectivity=4)
    keep_open = np.zeros(count, dtype=bool)
    keep_open[np.unique(labels[walkable & ~mask])] = True
    keep_open &= stats[:, cv2.CC_STAT_AREA] >= MIN_POCKET_PX
    keep_open[np.unique(np.concatenate(
        [labels[0], labels[-1], labels[:, 0], labels[:, -1]]))] = True
    keep_open[0] = True                                   # label 0 is the mask itself
    return mask | ~keep_open[labels]


def _pieces(mask, walkable, origin) -> list:
    """`mask` as world polygons with no holes: every component, each to within a pixel.

    A map polygon cannot have a hole, and a wall right round a room is a ring. So once the
    unreachable pockets are filled, any piece still enclosing something is cut in half, and
    the halves again only where that was not enough. Every piece in a cut is kept, not just
    the largest. The two halves share the column (or row) they are cut on: meeting edge to
    edge, a polygon fill leaves a one-pixel seam between them.
    """
    mask = _filled(mask, walkable)
    out = []
    boxes = [(0, 0, mask.shape[1], mask.shape[0])]
    while boxes:
        x0, y0, x1, y1 = boxes.pop()
        crop = np.ascontiguousarray(mask[y0:y1, x0:x1].astype(np.uint8))
        if not crop.any():
            continue
        contours, hierarchy = cv2.findContours(crop, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        holed = any(parent != -1 for _next, _prev, _child, parent in hierarchy[0])
        if holed and max(x1 - x0, y1 - y0) > 2:
            if x1 - x0 >= y1 - y0:
                mid = (x0 + x1) // 2
                boxes += [(x0, y0, mid + 1, y1), (mid, y0, x1, y1)]
            else:
                mid = (y0 + y1) // 2
                boxes += [(x0, y0, x1, mid + 1), (x0, mid, x1, y1)]
            continue
        for contour, (_next, _prev, _child, parent) in zip(contours, hierarchy[0]):
            if parent != -1 or cv2.contourArea(contour) < MIN_PIECE_PX:
                continue
            points = cv2.approxPolyDP(contour, PIECE_TOLERANCE_PX, True).reshape(-1, 2)
            if len(points) >= 3:
                out.append(tuple((int(x) + x0 + origin[0], int(y) + y0 + origin[1])
                                 for x, y in points))
    return out


def _first_floor(plan):
    """(step, x, y) of the first floor pixel on the door line, or None."""
    spec = plan.spec
    h, w = plan.floor.shape
    ox, oy = spec.door_origin
    ix, iy = spec.door_inward
    for step in range(int(10 * spec.tile)):
        x, y = int(round(ox + ix * step)), int(round(oy + iy * step))
        if not (0 <= x < w and 0 <= y < h):
            return None
        if plan.floor[y, x]:
            return step, x, y
    return None


def _body_width(spec) -> int:
    """The widest character on the roster, in this building's canvas px."""
    return int(player_size(scale=spec.world_scale).width)


def walk_in(plan, pieces) -> tuple:
    """(reach, open): where a body's centre can get to from outside the building, in canvas
    px, and whether that takes in the biggest open stretch of floor.

    `pieces` are world polygons the body cannot cross -- SAM's walls and the shell. The body
    is `_body_width` across, so a gap narrower than that is shut. It starts anywhere outside:
    the canvas is padded first, because the canvas is the silhouette's bounding box and a door
    on its edge would otherwise have no ground in front of it.

    The biggest open stretch, not every floor pixel: a pocket walled off elsewhere is not the
    doorway's business, and a sliver of floor between the door and a wall across it is not
    the room.
    """
    spec = plan.spec
    half = _body_width(spec) / 2.0
    pad = int(np.ceil(half)) + 4
    # One canvas, one rasteriser: the same PIL fill `rasterize_polygon` uses, without an
    # 11 MP image per piece.
    canvas = Image.new("L", (spec.size[0] + 2 * pad, spec.size[1] + 2 * pad), 0)
    draw = ImageDraw.Draw(canvas)
    for piece in pieces:
        draw.polygon([(x - spec.origin[0] + pad, y - spec.origin[1] + pad) for x, y in piece],
                     fill=255)
    free = _shrink(np.asarray(canvas) == 0, half)
    count, labels = cv2.connectedComponents(free.astype(np.uint8), connectivity=8)
    margin = np.ones(labels.shape, dtype=bool)
    margin[pad:-pad, pad:-pad] = False
    outside = np.unique(labels[margin & free])
    reach = np.isin(labels, outside)[pad:-pad, pad:-pad]
    floor = np.pad(plan.floor, pad) & free
    per_label = np.bincount(labels[floor], minlength=count)
    return reach, bool(per_label.any() and per_label.argmax() in outside)


def assert_passage_open(plan, pieces) -> None:
    """Raise unless a body from outside can walk past `pieces` into the room (`walk_in`).

    `pieces` are the world polygons the map will collide with: SAM's walls and the shell. A
    wall that shuts the way in is an invisible wall in the doorway; better to refuse the write.

    This used to check one 1 px line from the door point to the first floor pixel, and stopped
    there. On great_pyramid (2026-10-31) the floor started 182 px in, SAM's wall lay across
    the floor just past it, and the check passed a doorway nobody could walk through.
    """
    spec = plan.spec
    if not spec.door_origin or not pieces or not plan.floor.any():
        return
    _reach, open_ = walk_in(plan, pieces)
    if not open_:
        raise ValueError(
            f"the collision closes the doorway of {spec.building}: a body "
            f"{_body_width(spec)} px wide starting outside cannot reach the biggest open "
            f"stretch of floor -- the green on the walls overlay is how far it gets. "
            f"Nothing was written.")


def problem(plan, walls=()) -> str:
    """Why `write_plan` would refuse this plan and these walls, or "" when it would write them.

    Every geometric refusal `write_plan` can raise, computed the same way and with no I/O,
    so a gate can ask before it hands a plan on -- and stay where it is when the answer is
    no, instead of the whole session dying on a traceback with paid draws behind it.
    `walls` are `sam_room.sam_walls`' polygons, in canvas px.
    """
    from .sam_room import world_walls

    try:
        assert_passage_open(plan, world_walls(plan.spec, walls) + shell_pieces(plan))
        chamber_from_plan(plan)
    except ValueError as exc:
        return str(exc)
    return ""


# ---------------------------------------------------------------- TMX writing

_OBJECT_RE = re.compile(r"[ \t]*<object\b[^>]*\bname=\"(?P<name>[^\"]*)\"[^>]*?"
                        r"(?:/>|>.*?</object>)\s*\n", re.S)


def _strip_prefixed(xml, prefix):
    return _OBJECT_RE.sub(lambda m: "" if m.group("name").startswith(prefix) else m.group(0), xml)


def _next_object_id(xml) -> int:
    ids = [int(m) for m in re.findall(r"<object\b[^>]*\bid=\"(\d+)\"", xml)]
    return (max(ids) + 1) if ids else 1


def _object_xml(obj_id, name, points, props=None) -> str:
    ox = int(round(min(p[0] for p in points)))
    oy = int(round(min(p[1] for p in points)))
    rel = " ".join("%d,%d" % (int(round(x)) - ox, int(round(y)) - oy) for x, y in points)
    lines = ['  <object id="%d" name="%s" x="%d" y="%d">' % (obj_id, name, ox, oy),
             '   <polygon points="%s"/>' % rel]
    if props:
        lines.append("   <properties>")
        for key, value in props.items():
            lines.append('    <property name="%s" value="%s"/>' % (key, value))
        lines.append("   </properties>")
    lines.append("  </object>")
    return "\n".join(lines) + "\n"


def _relative(path, folder) -> str:
    """Art paths go into the map the way the map reads them: relative to its own folder."""
    try:
        return Path(path).resolve().relative_to(Path(folder).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _building_object_xml(spec, xml: str, obj_id: int, folder: Path) -> str:
    """The building itself: silhouette, art paths, door anchor. Not its door -- that is the
    door's frame, generated on every accept by `write_plan`.

    Only written when the map has no object by that name. On the tmx path there already is
    one -- it is where the silhouette came from -- and it may carry properties authored by
    hand that nothing here knows about, so it is left alone. On the sam3 path there is none,
    and this is the step that puts the discovered building on the map.

    Written at accept and nowhere earlier: until an interior has been rendered and kept,
    there is nothing for the map to point at.
    """
    if re.search(r'<object\b[^>]*\bname="%s"' % re.escape(spec.building), xml):
        return ""
    props = {
        "roof_image": _relative(spec.roof_image, folder),
        "interior_image": _relative(spec.interior_image, folder),
    }
    if spec.door_origin:
        door_x, door_y = spec.world([spec.door_origin])[0]
        props["door_x"] = int(round(door_x))
        props["door_y"] = int(round(door_y))
    return _object_xml(obj_id, spec.building, spec.world(spec.silhouette), props)


def _insert_into_layer(xml, layer, block) -> str:
    match = re.search(r'[ \t]*<objectgroup\b[^>]*\bname="%s"[^>]*>\n' % re.escape(layer), xml)
    if not match:
        raise ValueError(f"no {layer!r} object layer in the map")
    return xml[:match.end()] + block + xml[match.end():]


def _ensure_layer(xml, layer) -> str:
    """The map with an (empty) object layer named `layer`, added if it has none.

    Written as an open/close pair, not `<objectgroup .../>`: `_insert_into_layer` splices
    after the opening tag's newline, and a self-closing tag would leave the objects
    outside the group. Takes the map's `nextlayerid` and bumps it, as Tiled would.
    """
    if re.search(r'<objectgroup\b[^>]*\bname="%s"' % re.escape(layer), xml):
        return xml
    match = re.search(r'nextlayerid="(\d+)"', xml)
    layer_id = int(match.group(1)) if match else 1
    block = ' <objectgroup id="%d" name="%s">\n </objectgroup>\n' % (layer_id, layer)
    xml = xml.replace("</map>", block + "</map>", 1)
    if match:
        xml = re.sub(r'nextlayerid="\d+"', 'nextlayerid="%d"' % (layer_id + 1), xml, count=1)
    return xml


PROPS_LAYER = "Props"


def _tileset_span(element: str, map_dir: Path) -> int:
    """How many gids a `<tileset>` element claims: its tilecount, or past its highest tile id.

    An image-collection tileset numbers its tiles sparsely (a struck prop leaves a gap), so
    the count alone undersells it. An external tileset is read from its .tsx.
    """
    source = re.search(r'\bsource="([^"]*)"', element)
    text = element
    if source and source.group(1).lower().endswith(".tsx"):
        try:
            text = (Path(map_dir) / source.group(1)).read_text(encoding="utf-8")
        except OSError:
            text = ""
    count = re.search(r'<tileset\b[^>]*\btilecount="(\d+)"', text)
    ids = [int(i) for i in re.findall(r'<tile\b[^>]*\bid="(\d+)"', text)]
    return max(int(count.group(1)) if count else 1, (max(ids) + 1) if ids else 0, 1)


def ensure_tileset(xml: str, map_dir: Path, tsx: Path, span: int) -> tuple:
    """(xml, firstgid): the map referencing `tsx`, added after every other tileset if missing.

    Last, because a prop set grows -- every sheet cut adds tile ids -- and only the last
    tileset can grow without running into the next one's gids. `span` is how many gids the
    set needs now (its `next_tile_id`); a tileset placed after it in Tiled since, inside that
    range, is refused rather than overlapped.
    """
    # Relative to the map, climbing out of its folder if need be: the prop sets live under
    # Graphics/, shared by every level, and Tiled and pytmx both resolve from the map.
    source = Path(os.path.relpath(Path(tsx).resolve(), Path(map_dir).resolve())).as_posix()
    elements = re.findall(r"[ \t]*<tileset\b[^>]*?(?:/>|>.*?</tileset>)", xml, re.S)
    mine = next((e for e in elements if f'source="{source}"' in e), None)
    if mine is not None:
        firstgid = int(re.search(r'firstgid="(\d+)"', mine).group(1))
        for element in elements:
            other = int(re.search(r'firstgid="(\d+)"', element).group(1))
            if element is not mine and firstgid < other < firstgid + span:
                raise ValueError(
                    f"the tileset at firstgid {other} sits inside the prop set's gids "
                    f"{firstgid}-{firstgid + span - 1}: move it after the props in Tiled")
        return xml, firstgid
    firstgid = max([int(re.search(r'firstgid="(\d+)"', e).group(1)) + _tileset_span(e, map_dir)
                    for e in elements] + [1])
    line = f' <tileset firstgid="{firstgid}" source="{source}"/>\n'
    if elements:
        last = elements[-1]
        at = xml.index(last) + len(last)
        newline = xml.find("\n", at)
        at = len(xml) if newline < 0 else newline + 1
        xml = xml[:at] + line + xml[at:]
    else:
        opening = re.search(r"<map\b[^>]*>\n?", xml)
        xml = xml[:opening.end()] + line + xml[opening.end():]
    return xml, firstgid


def _tile_object_xml(obj_id, name, gid, x, y, width, height, props) -> str:
    lines = ['  <object id="%d" name="%s" gid="%d" x="%d" y="%d" width="%d" height="%d">'
             % (obj_id, name, gid, round(x), round(y), max(1, round(width)), max(1, round(height))),
             "   <properties>"]
    for key, value in props.items():
        lines.append('    <property name="%s" value="%s"/>' % (key, value))
    lines += ["   </properties>", "  </object>"]
    return "\n".join(lines) + "\n"


def write_props(spec, variants, map_path: Path, tsx: Path, span: int,
                layer: str = PROPS_LAYER) -> dict:
    """Replace this building's furnishing in `map_path` with `variants`' placements.

    `variants` is [(tag, placements)] with placements as `locate` writes them: feet x, y and
    w, h in the building's canvas px. Each becomes a Tiled tile object from the prop set's
    tileset -- anchored at its bottom, which is how Tiled stores one -- named
    `<building>_prop_<tag>_NN` and carrying `building` and `variant`, so the game can load
    one variant per building. Idempotent by that name prefix, like `write_plan`.
    """
    building = spec.building
    map_path = Path(map_path)
    xml = map_path.read_text(encoding="utf-8")
    xml = _strip_prefixed(xml, f"{building}_prop_")
    xml = _ensure_layer(xml, layer)
    xml, firstgid = ensure_tileset(xml, map_path.parent, tsx, span)
    obj_id = _next_object_id(xml)
    block, count = "", 0
    for tag, placements in variants:
        for index, placed in enumerate(placements):
            left = spec.origin[0] + placed["x"] - placed["w"] / 2
            bottom = spec.origin[1] + placed["y"]
            block += _tile_object_xml(obj_id, f"{building}_prop_{tag}_{index:02d}",
                                      firstgid + int(placed["tile_id"]), left, bottom,
                                      placed["w"], placed["h"],
                                      {"building": building, "variant": tag})
            obj_id += 1
            count += 1
    if block:
        xml = _insert_into_layer(xml, layer, block)
    xml = re.sub(r'nextobjectid="\d+"', 'nextobjectid="%d"' % obj_id, xml, count=1)
    map_path.write_text(xml, encoding="utf-8")
    return {"map": str(map_path), "props": count, "variants": len(variants), "firstgid": firstgid}


def write_plan(plan, map_path: Path, walls, *, obstacle_layer="BuildingWalls",
               building_layer="Buildings") -> dict:
    """Replace this building's generated geometry in `map_path`: `walls` (SAM's, canvas px)
    and the shell as obstacles, the chamber, door frame and sight loops as building shapes.

    Idempotent by name prefix: every object this writes is named `<building>_wall_NN`,
    `<building>_shell_NN`, `<building>_chamber`, `<building>_sight_NN` or `<building>_door*`,
    and re-running replaces exactly those, in any layer, and leaves the building object alone.

    The obstacles go to their own layer, created if the map has none: the level SAM merge
    deletes and rebuilds `ObstaclePolygons` on every run.

    The door is the door's frame (`door_frame_mask`), not the opening: it is what the game
    draws over a body passing under it. The opening itself stays in `interior.json`.
    """
    from .sam_room import wall_objects, world_walls

    building = plan.spec.building
    xml = Path(map_path).read_text(encoding="utf-8")
    for prefix in (f"{building}_wall", f"{building}_shell", f"{building}_chamber",
                   f"{building}_door", f"{building}_sight"):
        xml = _strip_prefixed(xml, prefix)
    xml = _ensure_layer(xml, obstacle_layer)

    obj_id = _next_object_id(xml)
    shell = shell_pieces(plan)
    wall_polygons = world_walls(plan.spec, walls)
    assert_passage_open(plan, wall_polygons + shell)
    walls_xml, obj_id = wall_objects(plan.spec, walls, obj_id)
    for index, piece in enumerate(shell):
        walls_xml += _object_xml(obj_id, "%s_shell_%02d" % (building, index), piece)
        obj_id += 1

    chamber = chamber_from_plan(plan)
    chamber_xml = _object_xml(obj_id, f"{building}_chamber", chamber,
                              {"chamber_of": building})
    obj_id += 1

    # The opening counts as ground for `_pieces`, so a frame that closes round it is cut
    # rather than filled -- a filled frame would be the opening again.
    doors = _pieces(door_frame_mask(plan.spec), door_mask(plan.spec), plan.spec.origin)
    doors_xml = ""
    for index, piece in enumerate(doors):
        name = f"{building}_door" if index == 0 else f"{building}_door_{index}"
        doors_xml += _object_xml(obj_id, name, piece, {"door_of": building})
        obj_id += 1

    # What the game casts sight against: the walls you collide with, so sight stops where
    # feet do. `band` is how far past a wall's face sight reaches: the partition, the wall
    # band the render was shown.
    loops = wall_polygons + shell
    sight_xml = ""
    for index, loop in enumerate(loops):
        sight_xml += _object_xml(obj_id, "%s_sight_%02d" % (building, index), loop,
                                 {"sight_of": building, "band": int(plan.spec.partition)})
        obj_id += 1

    building_xml = _building_object_xml(plan.spec, xml, obj_id, Path(map_path).parent)
    if building_xml:
        obj_id += 1

    xml = _insert_into_layer(xml, obstacle_layer, walls_xml)
    xml = _insert_into_layer(xml, building_layer, chamber_xml + doors_xml + sight_xml)
    if building_xml:
        xml = _insert_into_layer(xml, building_layer, building_xml)
    xml = re.sub(r'nextobjectid="\d+"', 'nextobjectid="%d"' % obj_id, xml, count=1)
    Path(map_path).write_text(xml, encoding="utf-8")

    return {
        "map": str(map_path),
        "walls": len(wall_polygons),
        "shell": len(shell),
        "chamber": [(int(x), int(y)) for x, y in chamber],
        "doors": len(doors),
        "sight": len(loops),
        "building_object": bool(building_xml),
    }
