"""The mesh hero is hit where he is drawn (damage chunk 4b, visual_hits.plan.md (a)): on the mesh's own
points (mesh_points) or on body.json's capsules, Settings.MESH_HERO_HIT_BODY. Every test runs for both."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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

import hit_core  # noqa: E402
import Player as player_module  # noqa: E402
from damage_data import attack  # noqa: E402
from Level4_tmxdev import Level4  # noqa: E402
from Player import BasePlayer, SpecificPlayer  # noqa: E402
from player_mesh import PlayerMesh  # noqa: E402
from Support import mesh_feet_world  # noqa: E402

SPRITE = ROOT / "Graphics" / "barb" / "down_idle" / "0.png"


@pytest.fixture(autouse=True, params=["points", "capsules"])
def hit_body(request, monkeypatch):
    monkeypatch.setattr(player_module, "MESH_HERO_HIT_BODY", request.param)
    return request.param


def _hero(mesh=True, drew=True, action="move", step=8, facing=300.0):
    """A hero as the game builds one: the barb sprite at (500, 500), and the barb mesh sized to its
    figure. Default pose: the walk frame and facing where a foot reaches 15 px below the sprite."""
    image = pygame.image.load(str(SPRITE)).convert_alpha()
    hero = BasePlayer.__new__(BasePlayer)
    hero.image = image
    hero.rect = image.get_rect(topleft=(500, 500))
    hero.mask = pygame.mask.from_surface(image)
    hero.hitbox = hero.rect.inflate(-6, -20)
    hero.team_id = "player"
    if mesh:
        skin = PlayerMesh("barb", image.get_bounding_rect().height)
        skin.skin.set_action(action)
        skin.skin.frame = float(step)
        skin.facing_deg = facing
        hero.mesh_skin = skin
        hero._mesh_drew = drew
        hit_core.reaches_past_rect(hero)             # as SpecificPlayer._attach_mesh does
    return hero


def _pixels(shape):
    return {(shape.rect.x + x, shape.rect.y + y) for x, y in shape.mask.outline()} | {
        (shape.rect.x + x, shape.rect.y + y)
        for x in range(shape.rect.w) for y in range(shape.rect.h) if shape.mask.get_at((x, y))
    }


def _dot(point):
    return hit_core.Shape(pygame.mask.Mask((1, 1), fill=True), point[0], point[1])


def test_capsules_lie_inside_hit_rect_and_reach_past_the_sprite():
    hero = _hero()
    shape = hit_core.shape_of(hero)
    box = shape.mask.get_bounding_rects()
    pixels = box[0].unionall(box[1:]).move(shape.rect.topleft)
    assert hero.hit_rect.contains(pixels)
    assert pixels.bottom > hero.rect.bottom          # the foot stepping toward the camera


def test_hit_on_the_capsules_not_the_sprite():
    hero = _hero()
    capsules = _pixels(hit_core.shape_of(hero))
    sprite = _pixels(hit_core.Shape(hero.mask, *hero.rect.topleft))
    only_capsules = sorted(capsules - sprite)
    only_sprite = sorted(sprite - capsules)
    assert only_capsules and only_sprite
    for point in (only_capsules[0], only_capsules[-1]):
        assert hit_core.find_hits(_dot(point), [hero]) == [hero], point
    for point in (only_sprite[0], only_sprite[-1]):
        assert hit_core.find_hits(_dot(point), [hero]) == [], point


def test_a_foot_below_the_sprite_is_found_through_hit_rect():
    hero = _hero()
    shape = hit_core.shape_of(hero)
    below = [p for p in _pixels(shape) if p[1] >= hero.rect.bottom]
    assert below
    assert hit_core.find_hits(_dot(below[0]), [hero]) == [hero]


def test_attaching_the_mesh_lists_him_as_reaching_past_his_rect():
    hero = _hero(mesh=False)
    SpecificPlayer._attach_mesh(hero, "barb")
    assert hero.mesh_skin is not None and hero in hit_core._REACHING


def test_reaching_body_is_found_only_if_it_is_a_candidate():
    hero = _hero()
    shape = hit_core.shape_of(hero)
    below = [p for p in _pixels(shape) if p[1] >= hero.rect.bottom]
    other = SimpleNamespace(rect=pygame.Rect(below[0][0], below[0][1], 4, 4),
                            mask=pygame.mask.Mask((4, 4), fill=True))
    assert hit_core.find_hits(_dot(below[0]), [other]) == [other]       # the hero is not a candidate
    assert hit_core.find_hits(_dot(below[0]), [other, hero]) == [other, hero]


def test_hit_rect_is_kept_until_the_pose_changes():
    hero = _hero()
    first = hero.hit_rect
    assert hero.hit_rect is first
    hero.mesh_skin.skin.frame = 0.0
    assert hero.hit_rect is not first
    hero.rect.x += 10
    assert hero.hit_rect.x != first.x


def test_drawn_where_the_camera_puts_him(hit_body):
    hero = _hero()
    shape = hit_core.shape_of(hero)
    skin = hero.mesh_skin
    fx, fy = mesh_feet_world(hero)
    if hit_body == "capsules":
        mask, dx, dy = skin.skin.body_mask(round(skin.yaw_deg()) % 360, skin.height_px)
        assert shape.rect.topleft == (int(fx + dx), int(fy + dy))
    else:
        outline, feet = hero.hit_outline()
        assert feet == (fx, fy) and shape.mask is outline.mask
        assert shape.rect.topleft == (int(fx) + outline.dx, int(fy) + outline.dy)


@pytest.mark.parametrize("kwargs", [{"mesh": False}, {"drew": False}])
def test_sprite_hero_or_undrawn_mesh_is_hit_on_the_sprite(kwargs):
    hero = _hero(**kwargs)
    assert hero.hit_shape() is None and hero.hit_rect is None
    shape = hit_core.shape_of(hero)
    assert shape.mask is hero.mask and shape.rect.topleft == hero.rect.topleft


def test_an_arrow_at_his_foot_hits_through_the_game_strike():
    hero = _hero()
    shape = hit_core.shape_of(hero)
    foot = max(_pixels(shape), key=lambda p: p[1])           # lowest capsule pixel, below the sprite
    arrow = SimpleNamespace(
        owner=None, interaction_kind="damage", source_kind="enemy_projectile", source_team="enemy_1",
        amount=6, attack_type="magic", tags=set(), hits={}, rehit_ms=None, stops=False,
        attack_def=attack("arrow"), rect=pygame.Rect(foot[0] - 8, foot[1] - 1, 16, 3),
        mask=pygame.mask.Mask((16, 3), fill=True), is_moving=True, movement=pygame.math.Vector2(12, 0))
    level = SimpleNamespace(attackable_sprites=[hero], interaction_resolver=Mock())
    Level4._strike_with_attack_sprites(level, [arrow])
    kwargs = level.interaction_resolver.strike.call_args.kwargs
    contact = kwargs["contacts"].get(id(hero))
    assert contact in _pixels(shape)
