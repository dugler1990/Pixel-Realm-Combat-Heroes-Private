"""Which body region a hit landed on (damage chunk 4): the contact pixel -> a defence_profile slot.

Only bodies that wear layers need it (the hero); a body with its hide only has the same layer
everywhere. Run once per landed hit, never per frame.

- Mesh hero (player_mesh.PlayerMesh, draw-only: hits land on his sprite mask): his posed body
  capsules on screen at the frame, yaw and size the camera draws him with, feet where the camera
  puts them (mesh_feet_world). Of the capsules under the contact, the one whose front is nearest
  the camera (what you see there); under none, the one whose edge is nearest. Its bone -> region
  from the pack's regions.json. The sprite pose is not the mesh pose, so a hit can come out a
  region off.
- Sprite hero: height bands on his hitbox (the barb's rest heights), side from his facing.
- "torso" is chest when the attack comes at his front (its travel against his facing), else back.

The projection is kept on the skin per (frame, yaw, size): hits in one frame share it.
"""
from __future__ import annotations

import json
import math
import os

import defence_profile

REGIONS_FILE = "regions.json"
REGIONS_VERSION = 1

# Sprite hero: (top of band as a share of his height from the feet, region). From the barb's rest
# capsules (feet 0, top of head 1).
BANDS = ((0.06, "foot"), (0.25, "shin"), (0.43, "thigh"), (0.50, "waist"), (0.62, "torso"),
         (0.68, "neck"), (1.01, "head"))

_BONE_SLOTS = {}


class RegionsError(ValueError):
    """A regions.json is wrong; the message names the file."""


def load_bone_regions(pack):
    """{bone index: (region, side)} from <pack root>/regions.json. Every capsule bone must have
    one; regions are item regions or "torso"; arms and legs need a side."""
    path = os.path.join(pack.root, REGIONS_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RegionsError(f"{path}: {exc}") from exc
    if data.get("version") != REGIONS_VERSION:
        raise RegionsError(f"{path}: version must be {REGIONS_VERSION}")
    bones = {}
    for key, value in (data.get("bones") or {}).items():
        region, side = value
        if region != "torso" and (region, side if region in defence_profile.SIDED else None) not in defence_profile.SLOT:
            raise RegionsError(f"{path}: bone {key}: no region slot {region!r} side {side!r}")
        bones[int(key)] = (region, side)
    missing = sorted({c["bone"] for c in pack.capsules} - set(bones))
    if missing:
        raise RegionsError(f"{path}: capsule bones without a region: {missing}")
    return bones


def _bone_slots(pack):
    """{bone: slot, or "torso"} for a pack, read once."""
    slots = _BONE_SLOTS.get(pack.name)
    if slots is None:
        slots = {
            bone: "torso" if region == "torso" else defence_profile.region_slot(region, side)
            for bone, (region, side) in load_bone_regions(pack).items()
        }
        _BONE_SLOTS[pack.name] = slots
    return slots


def _torso(toward, facing_deg):
    """Chest if the attack travels against his facing (comes at his front), else back."""
    if toward is None:
        return defence_profile.region_slot("chest")
    rad = math.radians(facing_deg)
    ahead = toward[0] * math.cos(rad) + toward[1] * math.sin(rad)
    return defence_profile.region_slot("chest" if ahead <= 0 else "back")


def _projection(skin):
    """(A, B, depth A, depth B, radii, bones) of the mesh hero's capsules on screen from his feet,
    cached on the skin per (frame, yaw, size)."""
    from mesh_boss import projected_capsules

    body = skin.skin
    pack = body.pack
    yaw = round(skin.yaw_deg()) % 360
    key = (body.frame_index, yaw, round(skin.height_px, 3))
    cached = getattr(skin, "_region_projection", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    scale = skin.height_px / max(pack.height_units, 1e-6)
    xy, depth, radii, bones = projected_capsules(pack, body.frame_index, yaw, scale)
    value = ([tuple(p) for p in xy[0::2]], [tuple(p) for p in xy[1::2]],
             [float(d) for d in depth[0::2]], [float(d) for d in depth[1::2]],
             [float(r) for r in radii], bones)
    skin._region_projection = (key, value)
    return value


def bone_at(a_ends, b_ends, a_depth, b_depth, radii, bones, x, y):
    """The bone seen at screen point (x, y): of the capsules (x, y) is inside, the one whose front
    surface there is nearest the camera; inside none, the one whose edge is nearest."""
    front, front_bone = -math.inf, None
    edge, edge_bone = math.inf, bones[0]
    for (ax, ay), (bx, by), da, db, r, bone in zip(a_ends, b_ends, a_depth, b_depth, radii, bones):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = ((x - ax) * dx + (y - ay) * dy) / length if length > 1e-9 else 0.0
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        ex, ey = ax + dx * t - x, ay + dy * t - y
        dist2 = ex * ex + ey * ey
        if dist2 <= r * r:
            surface = da + (db - da) * t + math.sqrt(r * r - dist2)
            if surface > front:
                front, front_bone = surface, bone
        elif front_bone is None:
            d = math.sqrt(dist2) - r
            if d < edge:
                edge, edge_bone = d, bone
    return front_bone if front_bone is not None else edge_bone


def mesh_slot(skin, feet, contact, toward=None):
    """The region slot under world pixel `contact` on a mesh hero drawn with `skin` at world `feet`."""
    bone = bone_at(*_projection(skin), contact[0] - feet[0], contact[1] - feet[1])
    slot = _bone_slots(skin.skin.pack)[bone]
    return _torso(toward, skin.facing_deg) if slot == "torso" else slot


FACING_DEG = {"right": 0.0, "down": 90.0, "left": 180.0, "up": 270.0}


def sprite_slot(hitbox, figure_px, contact, status, toward=None):
    """The region slot under `contact` on a sprite hero: height bands from his feet
    (hitbox.midbottom), `figure_px` tall. Facing from his status ("left_idle" -> left). Limb
    side: facing down, his left is on screen right; up, the reverse; left / right, the side that
    faces the camera (facing right, his right)."""
    fx, fy = hitbox.midbottom
    share = (fy - contact[1]) / max(float(figure_px), 1.0)
    region = next(name for top, name in BANDS if share < top)
    facing = str(status).split("_")[0]
    if region == "torso":
        return _torso(toward, FACING_DEG.get(facing, 90.0))
    if region not in defence_profile.SIDED:
        return defence_profile.region_slot(region)
    if facing == "right":
        side = "r"
    elif facing == "left":
        side = "l"
    else:
        on_right = contact[0] >= fx
        side = ("l" if on_right else "r") if facing != "up" else ("r" if on_right else "l")
    return defence_profile.region_slot(region, side)


def _point_slot(skin, outline, point, toward):
    slot = _bone_slots(skin.skin.pack).get(int(outline.owner[point]), "torso")
    return _torso(toward, skin.facing_deg) if slot == "torso" else slot


def points_slot(skin, outline, feet, contact, toward=None):
    """The region slot under `contact` on a mesh hero hit on his points: the point in front at that
    pixel (mesh_points.Outline) -> its bone -> region. None if no point is within 2 px."""
    point = outline.point_at(contact[0] - int(feet[0]), contact[1] - int(feet[1]))
    if point is None:
        return None
    return _point_slot(skin, outline, point, toward)


class HitSpot:
    """What a hit at one pixel meets. layers: outer first, the hide last. piece: the worn mesh piece in
    front there (None: skin, or not known). point: the mesh point in front (None: not the points
    path); with the outline's source, where a stuck arrow would sit (chunk 11)."""

    __slots__ = ("slot", "layers", "piece", "point")

    def __init__(self, slot, layers, piece=None, point=None):
        self.slot = slot
        self.layers = layers
        self.piece = piece
        self.point = point


def hit_layers(hero, contact, toward=None):
    """What a hit at world `contact` on `hero` meets. Mesh hero on his points: what is drawn in front
    at that pixel, a worn piece (its item's layer, then the hide) or skin (the hide only). Otherwise
    (sprite hero, capsules): the region's layers from his defence profile."""
    natural = hero.body_def.natural
    found = hero.hit_outline() if hasattr(hero, "hit_outline") else None
    if found is not None:
        outline, feet = found
        point = outline.point_at(contact[0] - int(feet[0]), contact[1] - int(feet[1]))
        if point is not None:
            slot = _point_slot(hero.mesh_skin, outline, point, toward)
            piece = outline.piece_of(point)
            layer = getattr(hero, "piece_layers", {}).get(piece) if piece else None
            return HitSpot(slot, (layer, natural) if layer is not None else (natural,), piece, point)
    slot = hero_slot(hero, contact, toward)
    return HitSpot(slot, hero.defence.layers_at(slot))


def hero_slot(hero, contact, toward=None):
    """The region slot a hit at world `contact` lands on, for a hero (mesh points, mesh capsules or
    sprite)."""
    from Support import mesh_feet_world

    skin = hero._drawn_skin() if hasattr(hero, "_drawn_skin") else getattr(hero, "mesh_skin", None)
    if skin is not None:
        found = hero.hit_outline() if hasattr(hero, "hit_outline") else None
        if found is not None:
            outline, feet = found
            slot = points_slot(skin, outline, feet, contact, toward)
            if slot is not None:
                return slot
        return mesh_slot(skin, mesh_feet_world(hero), contact, toward)
    figure = hero.image.get_bounding_rect().height if getattr(hero, "image", None) is not None else hero.hitbox.height
    return sprite_slot(hero.hitbox, figure, contact, getattr(hero, "status", "down"), toward)
