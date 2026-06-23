"""Co-op (CS3): the SERVER's sim step drains a relayed hit and damages the enemy.

Server-authoritative pivot: a client's MSG_HIT_ENEMY is queued on
game_state.pending_enemy_hits by the receiver thread; the sim loop's
_step_enemy_sim drains it and applies the damage to the authoritative
ServerLevel enemy. This covers that glue directly (no sockets), complementing the
end-to-end socket test in test_coop_enemy_relay.
"""

import os
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
pygame.display.set_mode((64, 64))

from Settings import TILESIZE  # noqa: E402
from common import ServerPlayerState  # noqa: E402
import server as server_module  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((64, 64))
    yield


def _server_with_enemy():
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    gs = srv.game_state
    # player far away so the squid never aggros/moves -- isolate the hit's effect.
    gs.players["alice"] = ServerPlayerState(player_id="alice", character="x",
                                            x=5000.0, y=5000.0)
    gs.pending_enemy_spawns = [{"kind": "enemy", "type": "squid", "pos": [10, 10]}]
    gs.map_width = gs.map_height = 20000.0
    srv._step_enemy_sim()                      # builds the sim + spawns the squid
    enemy = srv.server_level.spawner.enemies[0]
    return srv, enemy


def test_step_enemy_sim_drains_pending_hit_and_damages_enemy():
    srv, enemy = _server_with_enemy()
    before = enemy.health
    srv.game_state.pending_enemy_hits.append(
        {"type": "hit_enemy", "player_id": "alice", "enemy_id": enemy.id,
         "amount": 30, "attack_type": "weapon"}
    )
    srv._step_enemy_sim()
    assert enemy.health == before - 30
    assert srv.game_state.pending_enemy_hits == []   # drained


def test_step_enemy_sim_lethal_hit_removes_enemy_from_broadcast():
    srv, enemy = _server_with_enemy()
    srv.game_state.pending_enemy_hits.append(
        {"type": "hit_enemy", "player_id": "alice", "enemy_id": enemy.id,
         "amount": enemy.health + 50, "attack_type": "weapon"}
    )
    srv._step_enemy_sim()
    assert all(e["id"] != enemy.id for e in srv.game_state.enemies)  # killed + dropped
