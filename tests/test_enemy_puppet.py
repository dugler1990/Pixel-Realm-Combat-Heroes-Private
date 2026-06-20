"""Headless tests for Code/EnemyPuppet.py (co-op Stage C, slice C1).

Mirrors tests/test_remote_player.py: build a REAL EnemyPuppet (real enemy
assets/animations via the inherited CombatUnit pipeline), feed it the host's
relayed snapshots, and assert it tracks position/facing/status as a RENDER-ONLY
puppet -- never running AI/movement of its own. The "two windows see the same
monsters" check is the human acceptance test.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))  # asset loads / convert_alpha need a video mode

from Settings import monster_data  # noqa: E402
from EnemyPuppet import EnemyPuppet  # noqa: E402

MONSTER = next(iter(monster_data))  # any real enemy type


def _make_puppet(center=(100, 200), eid=7, group=None):
    return EnemyPuppet(
        enemy_id=eid,
        monster_name=MONSTER,
        center=center,
        groups=[group if group is not None else pygame.sprite.Group()],
        obstacle_sprites=SimpleNamespace(),
        level=SimpleNamespace(),
    )


def test_construction_centers_at_spawn():
    p = _make_puppet(center=(100, 200))
    assert p.enemy_id == 7
    assert p.type == MONSTER
    assert p.rect.center == (100, 200)
    assert p.hitbox.center == (100, 200)
    assert isinstance(p.image, pygame.Surface)


def test_apply_snapshot_repositions_immediately_and_sets_status_facing():
    p = _make_puppet(center=(0, 0))
    p.apply_snapshot(500, 600, "move", "left", health=42)
    assert p.rect.center == (500, 600)   # NOW, before any update() (drawn this frame)
    assert p.hitbox.center == (500, 600)
    assert p.status == "move"
    assert p.direction.x < 0             # faces left
    assert p.health == 42
    p.apply_snapshot(500, 600, "move", "right")
    assert p.direction.x > 0             # faces right


def test_update_is_render_only_never_self_moves():
    # status "move" makes a real CombatUnit.update() call move(); the puppet must
    # NOT -- its position comes only from snapshots.
    p = _make_puppet(center=(300, 300))
    p.apply_snapshot(300, 300, "move", "right")
    for _ in range(10):
        p.update()  # the camera-group update_parallel path
    assert p.rect.center == (300, 300)


def test_enemy_update_and_combat_update_are_noops():
    # Level4's per-frame visible_sprites sweep calls enemy_update on anything
    # that has it; the puppet must run NO AI (no raise, no state change).
    p = _make_puppet(center=(120, 120))
    p.apply_snapshot(120, 120, "idle", "right")
    snap = (p.rect.center, p.status)
    p.enemy_update(None, None, frame_number=5, entity_id_map={})
    p.combat_update(None, None, frame_number=5, entity_id_map={})
    assert (p.rect.center, p.status) == snap


def test_kill_removes_from_render_group():
    group = pygame.sprite.Group()
    p = _make_puppet(eid=1, group=group)
    assert p in group.sprites()
    p.kill()
    assert p not in group.sprites()


# -- C2: a hit on the puppet is RESOLVED locally + RELAYED, never applied to the
#    puppet's own health (the enemy is host-authoritative) --

def test_receive_interaction_relays_resolved_amount_and_does_not_change_health():
    p = _make_puppet(center=(0, 0))
    p.apply_snapshot(0, 0, "idle", "right", health=100)
    captured = []
    p.level = SimpleNamespace(_queue_enemy_hit=lambda eid, amt, at: captured.append((eid, amt, at)))
    source = SimpleNamespace(get_full_weapon_damage=lambda: 25, get_full_magic_damage=lambda: 40)

    weapon_ctx = SimpleNamespace(kind="damage", amount=None, source=source,
                                 attack_type="weapon", source_team="player", target=p)
    p.receive_interaction(weapon_ctx)
    assert captured == [(p.enemy_id, 25, "weapon")]   # weapon damage resolved from OUR stats
    assert p.health == 100                            # host owns health; puppet untouched

    captured.clear()
    magic_ctx = SimpleNamespace(kind="damage", amount=None, source=source,
                                attack_type="magic", source_team="player", target=p)
    p.receive_interaction(magic_ctx)
    assert captured == [(p.enemy_id, 40, "magic")]
    assert p.health == 100


def test_receive_interaction_uses_explicit_amount_when_present():
    p = _make_puppet(center=(0, 0))
    p.apply_snapshot(0, 0, "idle", "right", health=50)
    captured = []
    p.level = SimpleNamespace(_queue_enemy_hit=lambda eid, amt, at: captured.append((eid, amt, at)))
    ctx = SimpleNamespace(kind="damage", amount=7.5, source=None,
                          attack_type="weapon", source_team="player", target=p)
    p.receive_interaction(ctx)
    assert captured == [(p.enemy_id, 7.5, "weapon")]
    assert p.health == 50
