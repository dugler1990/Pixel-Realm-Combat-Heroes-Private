"""Traced floor plan -> chamber polygon and wall polygons, written to a scratch TMX.

The walls are not laid along a traced line. They are strips: one a partition wide right
round the walkable ground (the floor and the way in from the door), one a shell wide inside
the building's outline, each minus the walkable ground. So they hug the painted floor to the
pixel and are solid by construction. Laying blocks along a simplified outline instead put
walls across pyramid_01's rooms and its entrance (the outline was 145 px off), and even at
3 px left threads of wall and wedge-shaped gaps.

The pieces are as big as a map polygon allows, not cut short. The engine pushes a body away
from a piece's bounding-box centre, which on a big piece can sit inside a room; that is a
known cost, left for now.

Why a scratch TMX: writing is regex string surgery on the shipped map, idempotent only by
name prefix, so a half-failed write leaves it partly stripped. The preview loads whatever
path it is handed, so it stays honest against a copy.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..world_levels.geometry import mask_to_polygon
from .plan import door_mask, geometry_masks
from .trace import to_world

# Every wall piece and the chamber are outlined to within a pixel of their mask.
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


def wall_mask(plan, walkable=None) -> np.ndarray:
    """The room walls: a strip `spec.partition` wide right round the walkable ground, inside
    the building. The same number the render pass is shown as a wall band, so what you see
    and what you walk into are one thickness."""
    walkable = walkable_mask(plan) if walkable is None else walkable
    return _grow(walkable, plan.spec.partition) & ~walkable & plan.silhouette


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


def wall_pieces(plan, walkable=None) -> list:
    """`wall_mask` as world polygons the map can hold."""
    walkable = walkable_mask(plan) if walkable is None else walkable
    return _pieces(wall_mask(plan, walkable), walkable, plan.spec.origin)


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


def assert_passage_open(plan, pieces) -> None:
    """Raise if any wall piece sits on the walk from the door to the floor.

    The same line `floor_behind_door` walks: from the door point on the silhouette edge,
    inward, to the first floor pixel. It does not ask anything of the painting -- the door
    polygon is held out of the mask, and nothing here wants floor in it. It asks that the
    walls derived from the painting leave that stretch open, because a wall there is an
    invisible wall in the doorway. Better to refuse the write.
    No floor on that line means the gate already failed this plan; nothing to assert.

    The walls are built round the walkable ground, the way in included, so this fires only
    when the door line leaves it -- a door point outside its own door polygon. It caught
    pyramid_01 when walls were laid along a 145 px outline, one of them across the entrance.
    """
    spec = plan.spec
    if not spec.door_origin or not pieces:
        return
    first = _first_floor(plan)
    if first is None:
        return
    # One canvas, one rasteriser: the same PIL fill `rasterize_polygon` uses, without an
    # 11 MP image per piece.
    canvas = Image.new("L", tuple(spec.size), 0)
    draw = ImageDraw.Draw(canvas)
    local = [tuple((x - spec.origin[0], y - spec.origin[1]) for x, y in piece)
             for piece in pieces]
    for polygon in local:
        draw.polygon(polygon, fill=255)
    blocked = np.asarray(canvas) > 0
    ox, oy = spec.door_origin
    ix, iy = spec.door_inward
    for step in range(first[0]):
        x, y = int(round(ox + ix * step)), int(round(oy + iy * step))
        if not blocked[y, x]:
            continue
        culprit = next((piece for piece, polygon in zip(pieces, local)
                        if _covers(polygon, (x, y))), None)
        where = ""
        if culprit:
            xs, ys = [p[0] for p in culprit], [p[1] for p in culprit]
            where = (f" (the wall piece spanning world ({int(min(xs))}, {int(min(ys))}) "
                     f"to ({int(max(xs))}, {int(max(ys))}))")
        raise ValueError(
            f"the collision closes the doorway of {spec.building}: a wall crosses the walk "
            f"in from the door {step} px from the door point, at world "
            f"({int(x + spec.origin[0])}, {int(y + spec.origin[1])}), and the floor only "
            f"starts {first[0]} px in{where}. Nothing was written.")


def _covers(polygon, point) -> bool:
    """Is `point` inside or on `polygon`? For naming the piece that closed the doorway."""
    contour = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(contour, (float(point[0]), float(point[1])), True) >= -1.0


def problem(plan) -> str:
    """Why `write_plan` would refuse this plan, or "" when it would write it.

    Every geometric refusal `write_plan` can raise, computed the same way and with no I/O,
    so a gate can ask before it hands a plan on -- and stay where it is when the answer is
    no, instead of the whole session dying on a traceback with paid draws behind it.
    """
    try:
        walkable = walkable_mask(plan)
        assert_passage_open(plan, wall_pieces(plan, walkable) + shell_pieces(plan, walkable))
        chamber_from_plan(plan)
    except ValueError as exc:
        return str(exc)
    return ""


def rooms(plan, radius=None) -> list:
    """Eroded floor components as world polygons: one per room.

    Rooms are the natural unit for spawning, and this is the same erosion `room_count`
    measures, so what gets a spawn area is exactly what was counted.
    """
    from . import checks as layout_checks
    from .trace import component_report

    radius = radius or layout_checks.CORRIDOR_HALF_TILES * plan.spec.tile
    eroded = layout_checks.erode(plan.floor, radius)
    minimum = int(layout_checks.MIN_ROOM_TILES_SQ * plan.spec.tile * plan.spec.tile)
    out = []
    number, labels = cv2.connectedComponents(
        np.ascontiguousarray(eroded.astype(np.uint8)), connectivity=8)
    for label in range(1, number):
        component = labels == label
        if int(component.sum()) < minimum:
            continue
        try:
            out.append(to_world(mask_to_polygon(component, epsilon_frac=0.02), plan.spec.origin))
        except ValueError:
            continue
    return out


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


def _shadow(source: Path, target: Path) -> None:
    """Point `target` at `source` as cheaply as this machine allows.

    A symlink is the cheapest and needs a privilege Windows does not grant by default --
    `OSError 1314` -- so a plain checkout hits it on the first preview. A directory junction
    needs no privilege and behaves the same for reading, and a hard link does the job for a
    file. Copying is the last resort: correct everywhere, and the reason the fallbacks are
    worth having is that a level folder can hold hundreds of megabytes of art.
    """
    try:
        target.symlink_to(source)
        return
    except (OSError, NotImplementedError):
        pass

    if source.is_dir():
        try:                                     # junction: no privilege required
            subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)],
                           check=True, capture_output=True)
            return
        except (OSError, subprocess.SubprocessError):
            pass
        shutil.copytree(source, target)
        return

    try:
        os.link(source, target)                  # hard link: same file, no copy
    except (OSError, NotImplementedError):
        shutil.copyfile(source, target)


def scratch_level(spec) -> Path:
    """A shadow of the level folder whose map.tmx is the one plans are written into.

    A whole folder rather than a stray file because the engine takes a layout DIRECTORY and
    loads `map.tmx` from it, and because tilesets and building art resolve relative to the
    map. Everything but the map is symlinked, so shadowing a level with a 242 MB background
    costs nothing.

    The shipped map is never written until accept. That matters more than churn: writing is
    regex surgery, idempotent only by name prefix, so a half-failed write leaves the real
    map partly stripped.
    """
    source_dir = Path(spec.map_path).resolve().parent
    scratch_dir = source_dir.parent / f"{source_dir.name}.plan"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    for entry in source_dir.iterdir():
        target = scratch_dir / entry.name
        if entry.name == "map.tmx":
            shutil.copyfile(entry, target)
            continue
        if entry.name == "initial_layout_name.txt":
            continue
        if target.is_symlink() or target.exists():
            continue
        _shadow(entry.resolve(), target)

    # The engine reads this as a path relative to Code/, so the shadow has to name itself.
    code_dir = Path(__file__).resolve().parents[3] / "Code"
    (scratch_dir / "initial_layout_name.txt").write_text(
        os.path.relpath(scratch_dir, code_dir) + "\n", encoding="utf-8")
    return scratch_dir


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


def write_plan(plan, map_path: Path, *, obstacle_layer="ObstaclePolygons",
               building_layer="Buildings", spawn_layer="spawner") -> dict:
    """Replace this building's generated geometry in `map_path` with the plan's.

    Idempotent by name prefix, like building_walls: every object this writes is named
    `<building>_wall_NN`, `<building>_shell_NN`, `<building>_chamber`, `<building>_room_NN`
    or `<building>_door*`, and re-running replaces exactly those and leaves the building
    object alone. (`<building>_hole` was written by an earlier emitter; it is stripped so a
    re-emit cleans it up, and can leave this list once every map has been re-emitted.)

    The door is the door's frame (`door_frame_mask`), not the opening: it is what the game
    draws over a body passing under it. The opening itself stays in `interior.json`.

    Rooms go to the `spawner` layer, created if the map has none: they are the unit for
    spawning, and the engine's spawner reader skips any object without a `spawner_config`,
    so they sit inert until one is given a spawn config. Never the Buildings layer -- a
    room there loads as a second building with a placeholder roof.
    """
    building = plan.spec.building
    xml = Path(map_path).read_text(encoding="utf-8")
    for prefix in (f"{building}_wall", f"{building}_shell", f"{building}_chamber",
                   f"{building}_hole", f"{building}_room", f"{building}_door"):
        xml = _strip_prefixed(xml, prefix)
    xml = _ensure_layer(xml, spawn_layer)

    obj_id = _next_object_id(xml)
    walkable = walkable_mask(plan)
    walls = wall_pieces(plan, walkable)
    shell = shell_pieces(plan, walkable)
    assert_passage_open(plan, walls + shell)
    walls_xml = ""
    for index, piece in enumerate(walls):
        walls_xml += _object_xml(obj_id, "%s_wall_%02d" % (building, index), piece)
        obj_id += 1
    for index, piece in enumerate(shell):
        walls_xml += _object_xml(obj_id, "%s_shell_%02d" % (building, index), piece)
        obj_id += 1

    chamber = chamber_from_plan(plan)
    chamber_xml = _object_xml(obj_id, f"{building}_chamber", chamber,
                              {"chamber_of": building})
    obj_id += 1

    room_polygons = rooms(plan)
    rooms_xml = ""
    for index, polygon in enumerate(room_polygons):
        rooms_xml += _object_xml(obj_id, "%s_room_%02d" % (building, index), polygon,
                                 {"room_of": building})
        obj_id += 1

    # The opening counts as ground for `_pieces`, so a frame that closes round it is cut
    # rather than filled -- a filled frame would be the opening again.
    doors = _pieces(door_frame_mask(plan.spec), door_mask(plan.spec), plan.spec.origin)
    doors_xml = ""
    for index, piece in enumerate(doors):
        name = f"{building}_door" if index == 0 else f"{building}_door_{index}"
        doors_xml += _object_xml(obj_id, name, piece, {"door_of": building})
        obj_id += 1

    building_xml = _building_object_xml(plan.spec, xml, obj_id, Path(map_path).parent)
    if building_xml:
        obj_id += 1

    xml = _insert_into_layer(xml, obstacle_layer, walls_xml)
    xml = _insert_into_layer(xml, building_layer, chamber_xml + doors_xml)
    if building_xml:
        xml = _insert_into_layer(xml, building_layer, building_xml)
    if rooms_xml:
        xml = _insert_into_layer(xml, spawn_layer, rooms_xml)
    xml = re.sub(r'nextobjectid="\d+"', 'nextobjectid="%d"' % obj_id, xml, count=1)
    Path(map_path).write_text(xml, encoding="utf-8")

    return {
        "map": str(map_path),
        "walls": len(walls),
        "shell": len(shell),
        "chamber": [(int(x), int(y)) for x, y in chamber],
        "rooms": len(room_polygons),
        "doors": len(doors),
        "building_object": bool(building_xml),
    }
