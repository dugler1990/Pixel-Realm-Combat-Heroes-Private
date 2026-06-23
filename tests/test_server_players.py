"""Slice 3 (server-authoritative pivot): networked players as in-world targets.

On the headless server each connected client is a server-mode `RemotePlayer`
living in visible_sprites + the entity quad tree, so the REAL enemy sim aggros
and damages it -- but the server does NOT own its health (the owning client
does). So a server-mode RemotePlayer RECORDS incoming damage for relay
(`drain_player_hits` -> MSG_HIT_PLAYER) instead of applying it, and a downed
player drops out of the entity tree so enemies disengage.

These prove the Code/-side pieces against a headless Level4; the GameServer
wiring (positions from client reports, broadcasting the events) is Slice 4.
"""

import os
import random
import sys
import types
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
from network import MSG_HIT_PLAYER  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((1280, 720))
    yield


def _server_level_with_player(player_id="alice", health=1000):
    """A headless server Level4 with the sentinel parked off-map and one
    networked player on enemy spawn area 0. Returns (level, player, center)."""
    level = build_headless_level(level_number=6, is_server=True)
    # Park the sentinel far off-map: it stays as combat_context default_target
    # but no enemy ever reaches it (default_target is only used when there's no
    # resolver, which never happens here), so it can't perturb aggro/spawns.
    level.player.rect.center = (-100000, -100000)
    level.player.hitbox.center = level.player.rect.center

    area = level.layout_manager.spawner.spawn_areas[0]
    oi = area["object_info"]
    center = (
        int(oi["rect_x_px"] + oi["rect_w_px"] / 2),
        int(oi["rect_y_px"] + oi["rect_h_px"] / 2),
    )
    player = level.add_server_player(player_id, "../Graphics/Orange_Wizard/",
                                     center[0], center[1], health=health)
    return level, player, center


def test_server_player_records_damage_without_applying():
    random.seed(1)
    level, alice, _center = _server_level_with_player()

    # It's a server-mode player in the world, on the player team, NOT attackable
    # by players (co-op).
    assert alice._server_mode is True
    assert alice.team_id == "player"
    assert alice in level.layout_manager.visible_sprites.sprites()
    assert alice not in level.attackable_sprites.sprites()
    assert level.server_players["alice"] is alice

    # An enemy hit RECORDS, it does NOT touch health (the client owns health).
    hp_before = alice.health
    ctx = types.SimpleNamespace(kind="damage", amount=37.0,
                                attack_type="melee", source=None)
    alice.receive_interaction(ctx)
    assert alice.health == hp_before  # server never applies
    assert alice.incoming_hits == [(37.0, "melee")]

    # drain_player_hits emits one MSG_HIT_PLAYER for the victim and clears.
    events = level.drain_player_hits()
    assert events == [{"type": MSG_HIT_PLAYER, "target_player_id": "alice",
                       "amount": 37.0, "attack_type": "melee"}]
    assert alice.incoming_hits == []
    assert level.drain_player_hits() == []  # drained


def test_server_enemies_spawn_near_player_then_damage_and_disengage_on_death():
    random.seed(20260623)
    level, alice, center = _server_level_with_player(health=1000)
    spawner = level.layout_manager.spawner
    dt = 1.0 / 60.0

    # Run past the area's first spawn cycle while alice stands on it. The spawn
    # area fires because _spawn_area_reference() points at the networked player
    # (the sentinel is off-map). Enemies then aggro + damage her.
    hits_while_alive = 0
    for _ in range(540):
        level.set_server_player_state("alice", center[0], center[1], health=alice.health)
        level.run(dt)
        hits_while_alive += len(level.drain_player_hits())

    assert len(spawner.enemies) > 0, "spawn area never fired at the networked player"
    assert hits_while_alive > 0, "server enemies never damaged the networked player"
    assert alice.health == 1000, "server applied damage -- it must only RECORD it"

    # Down the player (the client would report health<=0). She drops from the
    # entity tree, so enemies disengage. Settle a few frames, then assert no more
    # hits land.
    alice.health = 0
    for _ in range(30):  # settle any in-flight attack
        level.set_server_player_state("alice", center[0], center[1], health=0)
        level.run(dt)
        level.drain_player_hits()

    hits_while_dead = 0
    for _ in range(120):
        level.set_server_player_state("alice", center[0], center[1], health=0)
        level.run(dt)
        hits_while_dead += len(level.drain_player_hits())
    assert hits_while_dead == 0, "a downed player was still being hit -- not dropped from aggro"
