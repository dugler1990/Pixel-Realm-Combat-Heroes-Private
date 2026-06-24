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
from network import MSG_HIT_PLAYER, MSG_ENEMY_DIED, MSG_ITEM_REMOVED  # noqa: E402
from Settings import TILESIZE  # noqa: E402


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


def test_server_gather_relay_and_apply_enemy_hit():
    """Slice 4a: the server's enemy-relay snapshot (-> client puppets) and the
    apply path for a client's relayed hit (-> the authoritative enemy)."""
    random.seed(2)
    level, _alice, center = _server_level_with_player()
    spawner = level.layout_manager.spawner
    # Spawn one real enemy directly (no need to wait for the proximity area).
    spawner.spawn_enemy({"type": "raccoon"}, pos=(center[0] / TILESIZE, center[1] / TILESIZE))
    assert len(spawner.enemies) == 1
    enemy = spawner.enemies[0]

    relay = level.gather_enemy_relay()
    assert len(relay) == 1
    e = relay[0]
    assert e["id"] == enemy.id
    assert e["type"] == "raccoon"
    assert set(e) >= {"id", "type", "x", "y", "status", "dir", "health"}
    assert e["health"] > 0

    # A client's relayed hit is applied to the authoritative enemy (i-frames make
    # the first hit land on a freshly spawned, vulnerable enemy).
    hp0 = enemy.health
    assert level.apply_enemy_hit(enemy.id, 25.0, "weapon") is True
    assert enemy.health <= hp0 - 25

    # An unknown enemy id is a no-op (already dead/despawned).
    assert level.apply_enemy_hit(999999, 25.0, "weapon") is False

    # A lethal hit + one sim tick removes it from the world and the relay.
    level.apply_enemy_hit(enemy.id, enemy.health + 100, "weapon")
    level.set_server_player_state("alice", center[0], center[1], health=1000)
    level.run(1.0 / 60.0)
    assert all(en.id != enemy.id for en in spawner.enemies)
    assert all(r["id"] != enemy.id for r in level.gather_enemy_relay())


def test_server_enemy_death_emits_event_without_local_xp():
    """Slice 4b: a server-side death becomes an enemy_died event (FX/XP ride it
    to clients); the parked sentinel never accrues XP and no local ItemVisual is
    spawned."""
    random.seed(5)
    level, _alice, center = _server_level_with_player()
    spawner = level.layout_manager.spawner
    spawner.spawn_enemy({"type": "raccoon"}, pos=(center[0] / TILESIZE, center[1] / TILESIZE))
    enemy = spawner.enemies[0]
    exp_before = level.player.exp

    # Kill it, then tick once so check_enemy_deaths captures it (server mode).
    level.apply_enemy_hit(enemy.id, enemy.health + 100, "weapon")
    level.set_server_player_state("alice", center[0], center[1], health=1000)
    level.run(1.0 / 60.0)

    deaths = level.drain_deaths()
    assert len(deaths) == 1
    d = deaths[0]
    assert d["type"] == MSG_ENEMY_DIED
    assert d["id"] == enemy.id
    assert d["monster"] == "raccoon"
    assert "exp" in d and "x" in d and "y" in d
    assert level.drain_deaths() == []  # drained

    # The server applied NO XP locally (it rides the event, awarded on clients).
    assert level.player.exp == exp_before
    # No local item visuals were spawned on the (render-less) server.
    from tmx_layout_manager import ItemVisual  # noqa
    assert not any(isinstance(s, ItemVisual)
                   for s in level.layout_manager.visible_sprites.sprites())


def test_server_pickup_arbitration_first_claim_wins():
    """Slice 4b: a shared drop is awarded to the first claimer; a later claim of
    the same drop gets nothing (no dupes)."""
    random.seed(6)
    level, _alice, _center = _server_level_with_player()
    level._server_dropped_items[42] = {"item_id": "gold_coin", "x": 1, "y": 2}

    awarded = level.arbitrate_pickup(42, "alice")
    assert awarded == {"type": MSG_ITEM_REMOVED, "drop_id": 42, "to": "alice"}
    # The drop is gone -> a second (losing) claim banks nothing.
    assert level.arbitrate_pickup(42, "bob") is None
    assert level.arbitrate_pickup(999, "alice") is None  # unknown drop
