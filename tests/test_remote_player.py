"""Headless test for Code/RemotePlayer.py (Milestone 3 -- THE CRUX).

Exercises the network-driven puppet end of the rendering integration WITHOUT
the full Level4/custom_draw stack: construct a real RemotePlayer (real assets,
animations, masks, hitbox via the inherited BasePlayer pipeline), feed it
snapshots, tick update(), and assert its position/facing/animation track the
server values. The "two windows, two sprites" visual check is the human
acceptance test (plan Verification step 3) and can't run headlessly here
because level 6's daytime path needs the GPU backend's draw_shadow.
"""

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

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))  # convert_alpha()/asset loads need a video mode

from PlayerSelection import unlocked_player_base_stats, unlocked_player_directory  # noqa: E402
from RemotePlayer import RemotePlayer  # noqa: E402

CHARACTER = unlocked_player_directory[0]  # "../Graphics/Orange_Wizard/"
STATS = unlocked_player_base_stats[0]


def _make_remote(center=(100.0, 200.0)):
    return RemotePlayer(
        player_id="remote1",
        character_assets=CHARACTER,
        center=center,
        groups=[pygame.sprite.Group()],
        obstacle_sprites=SimpleNamespace(),
        initial_stats=dict(STATS),
        level=SimpleNamespace(),
        input_manager=SimpleNamespace(),
        QuadTree=None,
        entity_quad_tree=None,
    )


def test_construction_seeds_idle_at_spawn():
    remote = _make_remote(center=(100.0, 200.0))
    assert remote.player_id == "remote1"
    assert remote.status == "down_idle"
    assert remote.rect.center == (100, 200)
    assert remote.hitbox.center == (100, 200)
    assert isinstance(remote.image, pygame.Surface)


def test_apply_snapshot_repositions_immediately():
    # The inbox is drained at the top of run(), but in the daytime path
    # custom_draw runs BEFORE update_parallel. So apply_snapshot must move the
    # sprite NOW (not wait for update()), else it's drawn one frame stale.
    remote = _make_remote(center=(0.0, 0.0))
    remote.apply_snapshot(500.0, 600.0, 1.0, 0.0, "right")
    assert remote.rect.center == (500, 600)  # before any update() call
    assert remote.hitbox.center == (500, 600)


def test_update_snaps_to_snapshot_position_and_facing():
    remote = _make_remote(center=(0.0, 0.0))
    remote.apply_snapshot(500.0, 600.0, 1.0, 0.0, "right")
    remote.update(dt=0.016, QuadTree=None, entity_quad_tree=None)

    assert remote.rect.center == (500, 600)
    assert remote.hitbox.center == (500, 600)
    assert remote.direction.x == 1.0
    assert remote.direction.y == 0.0
    assert remote.status == "right"


def test_update_matches_camera_group_kwargs_only_call():
    # YSortCameraGroup._update_single_sprite calls Entities as
    # update(dt=.., QuadTree=.., entity_quad_tree=..) -- all keywords.
    remote = _make_remote()
    remote.apply_snapshot(10.0, 20.0, -1.0, 0.0, "left")
    remote.update(dt=0.016, QuadTree=None, entity_quad_tree=None)
    assert remote.status == "left"
    assert remote.rect.center == (10, 20)


def test_idle_status_is_honored_verbatim_from_server():
    remote = _make_remote()
    remote.apply_snapshot(300.0, 300.0, 0.0, 0.0, "up_idle")
    remote.update()
    assert remote.status == "up_idle"
    assert remote.direction.x == 0.0
    assert remote.direction.y == 0.0


def test_animation_frame_advances_across_updates():
    remote = _make_remote()
    remote.apply_snapshot(0.0, 0.0, 1.0, 0.0, "right")
    remote.update()
    first = remote.frame_index
    remote.update()
    second = remote.frame_index
    assert second != first  # animate() is being driven each tick


def test_world_sim_hooks_are_inert_noops():
    # Level4.run() calls these on every Entity in visible_sprites; for a v0
    # puppet they must be safe no-ops (server owns effects/combat in Stage C).
    remote = _make_remote()
    assert remote.check_effects(None, None) is None
    assert remote.apply_environmental_damage(0.016) is None


def test_kill_removes_from_group():
    group = pygame.sprite.Group()
    remote = RemotePlayer(
        player_id="remote2",
        character_assets=CHARACTER,
        center=(0.0, 0.0),
        groups=[group],
        obstacle_sprites=SimpleNamespace(),
        initial_stats=dict(STATS),
        level=SimpleNamespace(),
        input_manager=SimpleNamespace(),
        QuadTree=None,
        entity_quad_tree=None,
    )
    assert remote in group.sprites()
    remote.kill()
    assert remote not in group.sprites()
