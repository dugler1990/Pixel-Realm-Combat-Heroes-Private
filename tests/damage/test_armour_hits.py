"""Plate or skin where it is drawn (damage chunk 4b): body_regions.hit_layers on the mesh hero's points,
worn pieces in his outline. Truth: the full-resolution body and pieces, posed and projected like the camera."""
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

import body_regions as br  # noqa: E402
import defence_profile as dp  # noqa: E402
import hit_core  # noqa: E402
import Player as player_module  # noqa: E402
from body_contact import ground_to_screen, model_to_ground  # noqa: E402
from damage_data import attack, body  # noqa: E402
from Level4_tmxdev import Level4  # noqa: E402
from Player import BasePlayer  # noqa: E402
from player_mesh import PlayerMesh  # noqa: E402
from Settings import VIEW_ELEVATION_DEG  # noqa: E402
from Support import mesh_feet_world  # noqa: E402

SPRITE = ROOT / "Graphics" / "barb" / "down_idle" / "0.png"
ROWS = json.loads((ROOT / "Graphics" / "Standard_Items" / "outfit_items.json").read_text(encoding="utf-8"))
BARB = body("barb")


@pytest.fixture(autouse=True)
def on_points(monkeypatch):
    monkeypatch.setattr(player_module, "MESH_HERO_HIT_BODY", "points")


def _items(prefix):
    return [SimpleNamespace(item_id=r["item_id"], effect_type=r["effect_type"], effect=r["effect"], base=r.get("base"))
            for r in ROWS if r["item_id"].startswith(prefix)]


def _hero(worn, action="idle", step=0, facing=90.0):
    image = pygame.image.load(str(SPRITE)).convert_alpha()
    hero = BasePlayer.__new__(BasePlayer)
    hero.image = image
    hero.rect = image.get_rect(topleft=(500, 500))
    hero.mask = pygame.mask.from_surface(image)
    hero.hitbox = hero.rect.inflate(-6, -20)
    hero.team_id = "player"
    hero.body_def = BARB
    skin = PlayerMesh("barb", image.get_bounding_rect().height)
    skin.set_pieces([it.effect["mesh_piece"] for it in worn])
    skin.skin.set_action(action)
    skin.skin.frame = float(step)
    skin.facing_deg = facing
    hero.mesh_skin = skin
    hero._mesh_drew = True
    hero.piece_layers = dp.piece_layers(worn)
    hero.defence = dp.build_profile(BARB, dp.worn_from_items(worn))
    hit_core.reaches_past_rect(hero)
    return hero


def _point_of(hero, piece=None, region=None):
    """A world pixel whose front point is `piece` (None: the body) on `region`."""
    outline, feet = hero.hit_outline()
    ys, xs = np.nonzero(outline.labels >= 0)
    for x, y in zip(xs, ys):
        pt = outline.labels[y, x]
        if outline.piece_of(pt) != piece:
            continue
        world = (feet[0] + outline.dx + x + 0.5, feet[1] + outline.dy + y + 0.5)
        if region is None or dp.SLOTS[br.hit_layers(hero, world).slot][0] == region:
            return world
    return None


def test_plate_where_plate_is_drawn():
    hero = _hero(_items("barb_fullplate_"))
    spot = br.hit_layers(hero, _point_of(hero, "barb_fullplate/chest"))
    assert spot.piece == "barb_fullplate/chest"
    assert [layer.name for layer in spot.layers] == ["plate_chest", "barb"]
    assert spot.layers[0].stopping_power == 40


def test_skin_where_skin_is_drawn():
    hero = _hero(_items("barb_fullplate_"))
    spot = br.hit_layers(hero, _point_of(hero, None, "head"))       # no helmet item
    assert spot.piece is None and [layer.name for layer in spot.layers] == ["barb"]


def test_loincloth_at_the_waist_skin_on_the_chest():
    hero = _hero(_items("barb_loincloth_"))
    assert br.hit_layers(hero, _point_of(hero, "barb_loincloth/loincloth")).layers[0].name == "loincloth"
    spot = br.hit_layers(hero, _point_of(hero, None, "chest"))
    assert [layer.name for layer in spot.layers] == ["barb"]


def test_pieces_are_in_his_hit_outline():
    bare = _hero([])
    plated = _hero(_items("barb_fullplate_"))
    assert len(plated.hit_outline()[0].owner) > len(bare.hit_outline()[0].owner)
    assert set(plated.hit_outline()[0].names) == {None} | {it.effect["mesh_piece"] for it in _items("barb_fullplate_")}


def test_sprite_hero_uses_the_region_profile(monkeypatch):
    hero = _hero(_items("barb_fullplate_"))
    hero.mesh_skin = None
    spot = br.hit_layers(hero, (hero.hitbox.centerx, hero.hitbox.bottom - 35))
    assert spot.point is None and spot.layers == hero.defence.layers_at(spot.slot)


# --- arrows land on plate or skin as drawn --------------------------------------------------

def _truth(hero):
    """{world pixel: piece or None} of the full-resolution body and pieces, nearest vertex per pixel."""
    skin = hero.mesh_skin
    pack = skin.skin.pack
    yaw = round(skin.yaw_deg()) % 360
    scale = skin.height_px / pack.height_units
    parts = [(None, pack, skin.skin.frame_index)] + [(n, p.pack, f) for n, p, f in skin.piece_frames()]
    gs, src = [], []
    for k, (_, part, frame) in enumerate(parts):
        z = np.load(os.path.join(part.root, "skin.npz"))
        rest = np.hstack([np.asarray(z["rest_pos"], dtype=np.float64), np.ones((len(z["rest_pos"]), 1))])
        joints = np.asarray(z["joints"]).astype(np.int64)
        weights = np.asarray(z["weights"], dtype=np.float64)
        mats = np.asarray(part.skin_mats[frame], dtype=np.float64)
        posed = sum(weights[:, i:i + 1] * np.einsum("vij,vj->vi", mats[joints[:, i]], rest)[:, :3] for i in range(4))
        gs.append(model_to_ground(posed, pack.pivot, yaw, scale))
        src.append(np.full(len(posed), k))
    g, src = np.concatenate(gs), np.concatenate(src)
    sxy = ground_to_screen(g, VIEW_ELEVATION_DEG)
    e = math.radians(VIEW_ELEVATION_DEG)
    depth = g[:, 1] * math.cos(e) + g[:, 2] * math.sin(e)
    fx, fy = mesh_feet_world(hero)
    px = np.floor(sxy[:, 0]).astype(int) + int(fx)
    py = np.floor(sxy[:, 1]).astype(int) + int(fy)
    out = {}
    for i in np.argsort(depth):
        out[(int(px[i]), int(py[i]))] = parts[src[i]][0]
    return out


def _arrow_contacts(hero, n=16):
    shape = hero.hit_shape()
    cx, cy = shape.rect.center
    found = []
    for ang in np.linspace(0, 360, n, endpoint=False):
        a = math.radians(ang)
        ux, uy = -math.cos(a), -math.sin(a)
        for d in range(80, -80, -1):
            tip = (cx - ux * d, cy - uy * d)
            if hit_core.touching(hit_core.Shape(pygame.mask.Mask((2, 2), fill=True), *tip), shape):
                break
        tip = (tip[0] + ux * 6, tip[1] + uy * 6)
        surf = pygame.Surface((20, 20), pygame.SRCALPHA)
        pygame.draw.line(surf, (255, 255, 255), (10 - ux * 9, 10 - uy * 9), (10 + ux * 9, 10 + uy * 9), 2)
        arrow = SimpleNamespace(
            owner=None, interaction_kind="damage", source_kind="enemy_projectile", source_team="enemy_1",
            amount=6, attack_type="magic", tags=set(), hits={}, rehit_ms=None, stops=False,
            attack_def=attack("arrow"), rect=surf.get_rect(center=(int(tip[0] - ux * 9), int(tip[1] - uy * 9))),
            mask=pygame.mask.from_surface(surf), is_moving=True, movement=pygame.math.Vector2(ux * 12, uy * 12))
        level = SimpleNamespace(attackable_sprites=[hero], interaction_resolver=Mock())
        Level4._strike_with_attack_sprites(level, [arrow])
        call = level.interaction_resolver.strike.call_args
        if call is not None:
            found.append(call.kwargs["contacts"].get(id(hero)))
    return found


def _drawn_near(real, contact, r):
    x, y = int(math.floor(contact[0])), int(math.floor(contact[1]))
    return {real[(x + dx, y + dy)] for dy in range(-r, r + 1) for dx in range(-r, r + 1) if (x + dx, y + dy) in real}


@pytest.mark.parametrize("action, step, facing", [("idle", 0, 90.0), ("move", 8, 0.0)])
def test_arrows_land_on_plate_or_skin_as_drawn(action, step, facing):
    """Plate or skin as the full mesh draws it at the hit. The points are ~1.6 px apart, so a seam
    between plate and skin is known to 2 px: every hit matches within 2 px, most within 1 (32 poses:
    96%; worst pose seen 13 of 15)."""
    hero = _hero(_items("barb_fullplate_"), action, step, facing)
    real = _truth(hero)
    checked = within_1 = within_2 = 0
    for contact in _arrow_contacts(hero):
        if not _drawn_near(real, contact, 1):
            continue
        piece = br.hit_layers(hero, contact).piece
        checked += 1
        within_1 += piece in _drawn_near(real, contact, 1)
        within_2 += piece in _drawn_near(real, contact, 2)
    assert checked >= 12
    assert within_2 == checked, (within_2, checked)
    assert within_1 / checked >= 0.85, (within_1, checked)
