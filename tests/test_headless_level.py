"""Slice 1 (server-authoritative pivot) -- characterization of the REAL Level4
run headless.

Proves the server can construct and tick the SAME Level4 the client runs, with
no window and no rendering (StubBackend under dummy SDL): the real Spawner
spawns real enemies via the map's proximity spawn areas, and the real enemy AI
moves them -- all driven by the unmodified Level4.run(dt). This is the baseline
the later slices must preserve: when run() is split into a sim-only path and the
GameServer is wired onto it, this same world behavior must still hold.

No Code/ behavior changes here: is_server defaults False, so singleplayer/client
construct Level4 byte-identically; only this headless bootstrap passes is_server.
"""

import math
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT / "Code", REPO_ROOT / "Server"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pygame  # noqa: E402
import pytest  # noqa: E402

pygame.init()
pygame.display.set_mode((1280, 720))

from headless_level import build_headless_level  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    # Test isolation: an earlier module (test_render_backend) opens an OpenGL
    # display whose dummy-SDL failures can leave the display subsystem in a state
    # where loading monster art via convert_alpha SEGFAULTS. We construct a REAL
    # Level4 (real CombatUnits), so force a clean SOFTWARE display before each
    # test. (The real server runs in a fresh process -- this is suite-only.)
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((1280, 720))
    yield


def _first_enemy_area(level):
    """The enemy-bearing spawn area with the smallest frequency (fastest to fire),
    so the test triggers a real proximity spawn in the fewest frames. Returns
    (area, center_xy, frequency)."""
    best = None
    for a in level.layout_manager.spawner.spawn_areas:
        cfg = a["config"]
        weights = cfg.get("enemy_spawn_weights") or {}
        if not weights or sum(weights.values()) <= 0:
            continue
        freq = float(cfg.get("frequency", 0) or 0)
        if best is None or freq < best[2]:
            oi = a["object_info"]
            center = (
                int(oi["rect_x_px"] + oi["rect_w_px"] / 2),
                int(oi["rect_y_px"] + oi["rect_h_px"] / 2),
            )
            best = (a, center, freq)
    return best


def test_headless_level_constructs():
    random.seed(1234)
    level = build_headless_level(level_number=6)

    assert level.is_server is True  # the headless bootstrap flags it (inert)
    assert level.player is not None
    assert getattr(level.player, "health", 0) > 0
    assert level.layout_manager is not None
    assert level.layout_manager.spawner is not None
    assert level.layout_manager.obstacle_quad_tree is not None
    assert level.layout_manager.entity_quad_tree is not None
    # No placed enemies on this map -- everything comes from spawn areas.
    assert len(level.layout_manager.spawner.enemies) == 0
    assert len(level.layout_manager.spawner.spawn_areas) > 0


def test_headless_run_spawns_and_moves_real_enemies():
    random.seed(1234)
    level = build_headless_level(level_number=6)
    spawner = level.layout_manager.spawner

    area = _first_enemy_area(level)
    assert area is not None, "level 6 should have at least one enemy spawn area"
    _a, center, freq = area

    # Park the player on the area so proximity passes; the area fires once its
    # spawn_timer reaches `frequency` seconds (dt accumulates in real seconds).
    level.player.rect.center = center
    level.player.hitbox.center = center

    dt = 1.0 / 60.0
    frames = int(freq * 60) + 120  # one full spawn cycle + buffer
    spawn_frame = None
    spawn_positions = {}
    for i in range(frames):
        level.run(dt)  # the REAL, unmodified game loop -- headless
        if spawn_frame is None and spawner.enemies:
            spawn_frame = i
            spawn_positions = {e.id: e.rect.center for e in spawner.enemies}

    # The real Spawner spawned real enemies through run()'s handle_spawn_areas.
    assert spawn_frame is not None, "no enemy spawned from the proximity area"
    assert len(spawner.enemies) > 0

    # The real enemy AI moved at least one of them (they aggro the lone player).
    moved = False
    for e in spawner.enemies:
        start = spawn_positions.get(e.id)
        if start is None:
            continue
        if math.hypot(e.rect.centerx - start[0], e.rect.centery - start[1]) > 1.0:
            moved = True
            break
    assert moved, "spawned enemies never moved -- enemy AI did not tick in run()"

    # Sim state stayed sane (no NaNs, player intact) across the whole run.
    assert getattr(level.player, "health", 0) > 0
    for e in spawner.enemies:
        assert math.isfinite(e.rect.centerx) and math.isfinite(e.rect.centery)


def test_server_run_skips_render_but_simulates_identically(monkeypatch):
    """Slice 2: Level4.run()'s draw-only calls are guarded by `not is_server`.

    Proves both halves of the guard contract:
      * the server path (is_server=True) makes ZERO custom_draw calls, the
        client path (is_server=False) draws every frame; and
      * skipping rendering does NOT change the simulation -- given the same seed
        and a deterministic clock, the two paths produce a bit-identical world
        (enemy positions/health + player health) after a long run with spawns,
        movement, and combat.

    The deterministic clock matters because enemy attack cadence is wall-clock
    gated (pygame.time.get_ticks); pinning it to a frame counter makes both runs
    comparable.
    """
    frame = {"n": 0}
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: frame["n"] * 16)

    def run_one(is_server):
        frame["n"] = 0
        random.seed(20260623)
        level = build_headless_level(level_number=6, is_server=is_server)
        spawner = level.layout_manager.spawner
        _a, center, freq = _first_enemy_area(level)
        level.player.rect.center = center
        level.player.hitbox.center = center

        draw_calls = {"n": 0}
        vs = level.layout_manager.visible_sprites
        real_custom_draw = vs.custom_draw

        def counting_custom_draw(*args, **kwargs):
            draw_calls["n"] += 1
            return real_custom_draw(*args, **kwargs)

        vs.custom_draw = counting_custom_draw

        frames = int(freq * 60) + 60  # one spawn cycle + combat frames
        for _ in range(frames):
            level.run(1.0 / 60.0)
            frame["n"] += 1

        digest = sorted(
            (round(e.rect.centerx), round(e.rect.centery), round(getattr(e, "health", 0)))
            for e in spawner.enemies
        )
        return draw_calls["n"], digest, round(level.player.health, 3), frames

    client_calls, client_digest, client_hp, frames = run_one(False)
    server_calls, server_digest, server_hp, _ = run_one(True)

    # The guard actually gates rendering.
    assert client_calls == frames  # client draws every frame
    assert server_calls == 0  # server renders nothing

    # ...and skipping render leaves the simulation bit-identical.
    assert server_digest == client_digest
    assert server_hp == client_hp
    assert len(server_digest) > 0  # the run genuinely simulated enemies + combat
