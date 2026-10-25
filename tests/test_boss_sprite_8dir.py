"""Headless checks for N-direction pre-rendered monsters (tools/boss_sprite_pipeline).

Needs an installed set at Graphics/Monsters/_test_fox (run the pipeline on
bosses/_test_fox.json); skips otherwise. Also writes a facing strip to
logs/boss_sprite_8dir_strip.png — the Phase 0 "walks in every direction" gate.
"""

import copy
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
os.chdir(CODE_DIR)  # asset paths in the engine are ../Graphics/... relative to Code/

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from Settings import monster_data  # noqa: E402
from combat_unit import CombatUnit  # noqa: E402
from EnemyPuppet import EnemyPuppet  # noqa: E402

MONSTER = "_test_fox"
MANIFEST = REPO_ROOT / "Graphics" / "Monsters" / MONSTER / "manifest.json"
pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="run the boss sprite pipeline on _test_fox first")


@pytest.fixture(autouse=True)
def _register_test_monster():
    monster_data.setdefault(MONSTER, copy.deepcopy(monster_data["demon_dog"]))
    yield


def _make_unit(pos=(300, 300)):
    return CombatUnit(
        monster_name=MONSTER, pos=pos, groups=[pygame.sprite.Group()],
        obstacle_sprites=pygame.sprite.Group(), combat_context={}, persistent=False,
    )


def test_loads_every_direction_from_manifest():
    manifest = json.loads(MANIFEST.read_text())
    unit = _make_unit()
    assert unit.eight_dir
    assert unit.direction_keys == manifest["directions"]
    for action, spec in manifest["actions"].items():
        for key in manifest["directions"]:
            assert len(unit.animations[action][key]) == spec["frames"]
    assert unit.direction_string == "s"


def test_plants_manifest_anchor_on_hitbox_for_every_frame():
    unit = _make_unit()
    ax, ay = unit.sprite_anchor_px
    for key in unit.direction_keys:
        unit.direction = pygame.math.Vector2(1, 0).rotate(unit.COMPASS_DEG[key])
        unit.status = "idle"
        unit.frame_index = 0
        unit.animate()
        assert unit.get_direction_as_string() == key
        assert unit.rect.left + round(ax) == unit.hitbox.midbottom[0]
        assert unit.rect.top + round(ay) == unit.hitbox.midbottom[1]


def test_facing_has_hysteresis_on_sector_edge():
    unit = _make_unit()
    unit.direction = pygame.math.Vector2(1, 0)          # exactly east
    assert unit.get_direction_as_string() == "e"
    unit.direction = pygame.math.Vector2(1, 0).rotate(26)  # 3.5° past the e/se edge → still e
    assert unit.get_direction_as_string() == "e"
    unit.direction = pygame.math.Vector2(1, 0).rotate(45)  # dead centre of se
    assert unit.get_direction_as_string() == "se"
    unit.direction = pygame.math.Vector2(1, 0).rotate(19)  # 3.5° back past the edge → still se
    assert unit.get_direction_as_string() == "se"


def test_puppet_round_trips_compass_keys():
    puppet = EnemyPuppet(
        enemy_id=1, monster_name=MONSTER, center=(0, 0), groups=[pygame.sprite.Group()],
        obstacle_sprites=SimpleNamespace(), level=SimpleNamespace(),
    )
    assert puppet.eight_dir
    for key in puppet.direction_keys:
        puppet.apply_snapshot(10, 20, "move", key)
        assert puppet.get_direction_as_string() == key


def test_move_frames_advance_with_distance_and_write_strip():
    unit = _make_unit()
    w, h = unit.image.get_size()
    strip = pygame.Surface((w * len(unit.direction_keys), h * 2), pygame.SRCALPHA)
    strip.fill((80, 80, 80, 255))
    for i, key in enumerate(unit.direction_keys):
        unit.direction = pygame.math.Vector2(1, 0).rotate(unit.COMPASS_DEG[key])
        unit.hitbox.midbottom = (i * w + round(unit.sprite_anchor_px[0]), round(unit.sprite_anchor_px[1]))
        unit.status = "idle"
        unit.frame_index = 0
        unit.animate()
        strip.blit(unit.image, unit.rect)
        unit.status = "move"
        unit.frame_index = 0
        unit.distance_moved = 16.0  # more than one PIXELS_PER_ANIM_FRAME
        unit.hitbox.midbottom = (i * w + round(unit.sprite_anchor_px[0]), h + round(unit.sprite_anchor_px[1]))
        unit.animate()
        assert unit.frame_index > 0
        strip.blit(unit.image, unit.rect)
    out = REPO_ROOT / "logs" / "boss_sprite_8dir_strip.png"
    out.parent.mkdir(exist_ok=True)
    pygame.image.save(strip, str(out))
    assert out.exists()
