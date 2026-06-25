"""Headless authoritative multiplayer server.

Design rationale lives in the multiplayer plan (.claude/plans/
ok-lets-make-a-drifting-yeti.md), "Server design" / "Wire protocol" /
"Threading model" sections:

- One socket per client, length-prefixed msgpack framing (Code/network/protocol.py).
- Fixed-tick simulation loop (TICK_RATE_HZ), independent of clients' variable dt.
- Each client gets a receiver thread that only reads messages and mutates
  GameState under its lock -- it never writes to a socket. The simulation
  loop is the sole socket writer: it copies a snapshot out from under the
  lock, releases it, then sends.
"""

import os
import socket
import sys
import threading
import time

# Headless: the server builds obstacle pixel masks (Stage B2.5) via Surface +
# surfarray, which work without a real display under the dummy SDL driver.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_CODE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code"))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from network.protocol import (  # noqa: E402
    MSG_HIT_ENEMY,
    MSG_INPUT,
    MSG_JOIN,
    MSG_LEAVE,
    MSG_PICKUP_ITEM,
    MSG_PLAYER_JOINED,
    MSG_PLAYER_LEFT,
    MSG_STATE_UPDATE,
    pack_message,
    recv_message,
)

from common import GameState, ServerPlayerState  # noqa: E402

# Broadcast rate. Clients render their own player live every frame but only
# learn about remotes at this rate, so during motion a remote trails by up to
# one tick of movement. 60Hz (vs the original 30) halves that visible lag and
# matches a 60fps client. v0 stays a relay -- this only paces broadcasts.
TICK_RATE_HZ = 60
TICK_DT = 1.0 / TICK_RATE_HZ

# The co-op level the server loads. MP is level 6 only for now.
MP_LEVEL_NUMBER = 6


class GameServer:
    def __init__(self, host="0.0.0.0", port=12345, run_world_sim=True):
        self.host = host
        self.port = port
        # The real server runs the authoritative world sim (loads + ticks the
        # real Level4). Set False for a pure relay (the Stage A/B transport +
        # obstacle-collision layer, which is independent of the world sim) -- used
        # by the movement/collision tests so they don't build the heavy level.
        self.run_world_sim = run_world_sim
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_socket.bind((host, port))
        self.listen_socket.listen()

        self.game_state = GameState()
        self.client_sockets = {}  # player_id -> socket, guarded by game_state.lock
        self.tick = 0
        # CS2: the server-authoritative enemy sim. Built lazily by the sim loop
        # (sole owner -> all pygame/sim work stays on one thread) once the first
        # client has uploaded the map geometry + enemy spawn spec. None until then.
        self.server_level = None

    def run(self):
        print(f"[server] listening on {self.host}:{self.port}")
        threading.Thread(target=self._simulation_loop, daemon=True).start()
        self._accept_loop()

    def _accept_loop(self):
        while True:
            client_socket, addr = self.listen_socket.accept()
            print(f"[server] connection from {addr}")
            threading.Thread(target=self._client_receiver, args=(client_socket, addr), daemon=True).start()

    # -- per-client receiver thread: pure reader/mutator, never writes to a socket --

    def _client_receiver(self, client_socket, addr):
        player_id = None
        try:
            while True:
                message = recv_message(client_socket)
                msg_type = message.get("type")

                if msg_type == MSG_JOIN:
                    player_id = message["player_id"]
                    player = ServerPlayerState(
                        player_id=player_id,
                        character=message["character"],
                        x=float(message["x"]),
                        y=float(message["y"]),
                        hitbox_w=float(message.get("hitbox_w", 0.0)),
                        hitbox_h=float(message.get("hitbox_h", 0.0)),
                    )
                    with self.game_state.lock:
                        self.game_state.players[player_id] = player
                        self.client_sockets[player_id] = client_socket
                        # Co-op (Stage C): first client to join is the host (runs
                        # the real enemy sim + relays it). Each client learns its
                        # role from host_id in state_update.
                        if self.game_state.host_player_id is None:
                            self.game_state.host_player_id = player_id
                            print(f"[server] {player_id} is the host (enemy authority)")
                        # Stage B2: first non-empty geometry upload wins; build
                        # the real obstacle QuadTree from it (all clients share
                        # the same map on localhost/LAN).
                        obstacles = message.get("obstacles")
                        if obstacles and self.game_state.obstacle_quad_tree is None:
                            # Entries are (x,y,w,h) or, for irregular obstacles,
                            # (x,y,w,h,packed_mask) -- pass through verbatim so
                            # build_obstacle_index can rebuild the pixel masks.
                            self.game_state.build_obstacle_index(
                                obstacles,
                                float(message.get("map_width", 0.0)),
                                float(message.get("map_height", 0.0)),
                            )
                            masked = sum(1 for o in obstacles if len(o) >= 5 and o[4])
                            print(f"[server] built obstacle quadtree from {len(obstacles)} rects "
                                  f"({masked} masked) ({player_id})")
                        # CS2: the first client also uploads the map's enemy spawn
                        # spec (its TMX placed-entity enemy configs) + map dims; the
                        # sim loop builds the authoritative ServerLevel from these.
                        # First non-empty upload wins (all share the same map).
                        enemy_spawns = message.get("enemy_spawns")
                        spawn_areas = message.get("spawn_areas")
                        if (enemy_spawns or spawn_areas) and self.game_state.pending_enemy_spawns is None \
                                and self.game_state.pending_spawn_areas is None:
                            self.game_state.pending_enemy_spawns = list(enemy_spawns or [])
                            self.game_state.pending_spawn_areas = list(spawn_areas or [])
                            self.game_state.map_width = float(message.get("map_width", 0.0))
                            self.game_state.map_height = float(message.get("map_height", 0.0))
                            print(f"[server] received {len(enemy_spawns or [])} placed enemies + "
                                  f"{len(spawn_areas or [])} spawn areas ({player_id})")
                        self.game_state.pending_events.append({
                            "type": MSG_PLAYER_JOINED,
                            "player_id": player_id,
                            "character": player.character,
                            "x": player.x,
                            "y": player.y,
                        })
                    print(f"[server] {player_id} joined as {player.character}")

                elif msg_type == MSG_INPUT:
                    with self.game_state.lock:
                        player = self.game_state.players.get(player_id)
                        # CS2: the SERVER owns the enemy sim now -- it no longer
                        # trusts a client's uploaded `enemies` (the sim loop writes
                        # game_state.enemies from ServerLevel each tick). Any
                        # `enemies` still on an input message is ignored.
                        if player is not None:
                            # v0 position relay: trust the client's reported (x, y),
                            # use move_x/move_y/attacking only to derive status.
                            # Stage B2: apply_update then validates against the
                            # obstacle quadtree (None until geometry is uploaded).
                            health = message.get("health")
                            player.apply_update(
                                float(message.get("x", player.x)),
                                float(message.get("y", player.y)),
                                float(message.get("move_x", 0.0)),
                                float(message.get("move_y", 0.0)),
                                bool(message.get("attacking", False)),
                                self.game_state.obstacle_quad_tree,
                                health=float(health) if health is not None else None,
                            )

                elif msg_type == MSG_HIT_ENEMY:
                    # CS3: a client's attack hit a (server-owned) enemy. Queue it
                    # for the sim loop, which applies it to the authoritative enemy.
                    # Accepted from ANY client (every client renders puppets + can
                    # attack); the server is the single apply-point now.
                    with self.game_state.lock:
                        self.game_state.pending_enemy_hits.append(dict(message))

                elif msg_type == MSG_PICKUP_ITEM:
                    # CS5b: a client claims a shared drop. Queue it for the sim loop,
                    # which arbitrates against the server's drop registry (first
                    # claim wins) and broadcasts the item_removed award.
                    with self.game_state.lock:
                        self.game_state.pending_pickups.append(dict(message))

                # (CS5: there is no client-broadcast reward path anymore. The
                #  SERVER is authoritative for deaths/loot and emits enemy_died/
                #  item_dropped/item_removed itself from the sim loop -- it does NOT
                #  accept them from clients, closing that cheat vector.)

                elif msg_type == MSG_LEAVE:
                    break

        except (ConnectionError, OSError):
            pass
        finally:
            self._disconnect(player_id, client_socket)

    def _disconnect(self, player_id, client_socket):
        if player_id is not None:
            with self.game_state.lock:
                removed = self.game_state.players.pop(player_id, None)
                self.client_sockets.pop(player_id, None)
                if removed is not None:
                    self.game_state.pending_events.append({"type": MSG_PLAYER_LEFT, "player_id": player_id})
                # Co-op: if the host left, hand authority to a remaining player
                # (its enemy sim takes over) and drop the stale enemy list.
                if player_id == self.game_state.host_player_id:
                    self.game_state.enemies = []
                    self.game_state.host_player_id = next(iter(self.game_state.players), None)
                    if self.game_state.host_player_id is not None:
                        print(f"[server] host left; {self.game_state.host_player_id} is the new host")
            print(f"[server] {player_id} left")
        try:
            client_socket.close()
        except OSError:
            pass

    # -- fixed-rate broadcast loop --
    # v0 / Stage A: the server does NOT simulate movement (position is relayed
    # from clients, applied on receipt in apply_update). This loop only paces
    # broadcasts at a steady TICK_RATE_HZ, decoupled from clients' send rates.
    # Stage B/C is where per-tick server-side simulation/validation comes back.

    def _simulation_loop(self):
        accumulator = 0.0
        last = time.monotonic()
        while True:
            now = time.monotonic()
            accumulator += now - last
            last = now
            while accumulator >= TICK_DT:
                self.tick += 1
                self._step_world_sim()
                self._broadcast_tick()
                accumulator -= TICK_DT
            time.sleep(0.001)

    # -- advance the server-authoritative world simulation one tick --
    # The server runs the REAL Level4 (it loads its own map + enemies). Owned
    # solely by this loop thread, so all pygame/sim work stays single-threaded.
    # We only touch the shared GameState (players in, enemies/events out) briefly
    # under the lock; the (potentially slow) run() tick runs outside it.
    def _step_world_sim(self):
        if not self.run_world_sim:
            return  # pure-relay mode: no world sim, no level build
        gs = self.game_state
        if self.server_level is None:
            with gs.lock:
                have_players = bool(gs.players)
            if not have_players:
                return  # nothing to simulate until a client joins
            self._build_server_level()

        with gs.lock:
            players = [{"player_id": pid, "character": p.character,
                        "x": p.x, "y": p.y, "health": p.health}
                       for pid, p in gs.players.items()]
            hits = gs.pending_enemy_hits
            gs.pending_enemy_hits = []
            pickups = gs.pending_pickups
            gs.pending_pickups = []
        level = self.server_level
        # Apply queued player->enemy hits BEFORE the tick, so a lethal hit is
        # caught by this tick's check_enemy_deaths and the enemy drops from the
        # broadcast (clients then kill the puppet).
        for hit in hits:
            level.apply_enemy_hit(
                hit.get("enemy_id"), hit.get("amount"), hit.get("attack_type"),
            )
        # Reconcile networked players (add joiners / apply reports / drop leavers),
        # then run ONE real sim tick (render-skipped via is_server).
        level.sync_players(players)
        level.run(TICK_DT)

        enemies = level.gather_enemy_relay()
        # enemy->player hits recorded this tick -> hit_player (victim's client
        # applies the damage to its real player: its own i-frames/death).
        player_hits = level.drain_player_hits()
        # enemy deaths -> enemy_died (FX + XP awarded on each client).
        deaths = level.drain_deaths()
        # this tick's loot drops + arbitrate any pickup claims (first wins).
        item_drops = level.drain_item_drops()
        item_removes = []
        for pk in pickups:
            event = level.arbitrate_pickup(pk.get("drop_id"), pk.get("player_id"))
            if event is not None:
                item_removes.append(event)
        with gs.lock:
            gs.enemies = enemies
            gs.pending_events.extend(player_hits)
            gs.pending_events.extend(deaths)
            gs.pending_events.extend(item_drops)
            gs.pending_events.extend(item_removes)

    # Where the parked sentinel self.player sits: far off-map so no enemy ever
    # reaches it (it stays as combat_context default_target, only ever used when
    # there's no resolver -- which never happens). The networked players are the
    # real in-world targets.
    _SENTINEL_PARK = (-100000, -100000)

    def _build_server_level(self):
        # Build + run the REAL Level4 headless (the server-authoritative pivot):
        # it loads its OWN map (obstacles, spawn areas, enemies) -- no client
        # upload needed. Heavy import + load; runs on the sim-loop thread so all
        # pygame/sim work stays single-threaded.
        from headless_level import build_headless_level
        self.server_level = build_headless_level(level_number=MP_LEVEL_NUMBER)
        # Park the sentinel off-map; networked players are added each tick.
        self.server_level.player.rect.center = self._SENTINEL_PARK
        self.server_level.player.hitbox.center = self._SENTINEL_PARK
        print(f"[server] world sim online (real Level4, level {MP_LEVEL_NUMBER}): "
              f"{len(self.server_level.layout_manager.spawner.spawn_areas)} spawn areas")

    # -- snapshot-then-release: copy state out, send outside the lock (sole writer) --

    def _broadcast_tick(self):
        with self.game_state.lock:
            events = list(self.game_state.pending_events)
            self.game_state.pending_events.clear()
            state_message = {
                "type": MSG_STATE_UPDATE,
                "tick": self.tick,
                "server_time_ms": time.monotonic() * 1000.0,
                "host_id": self.game_state.host_player_id,
                "players": {pid: p.to_snapshot() for pid, p in self.game_state.players.items()},
                "enemies": self.game_state.enemies,
            }
            sockets = dict(self.client_sockets)

        for event in events:
            self._send_to_all(sockets, event)
        self._send_to_all(sockets, state_message)

    def _send_to_all(self, sockets, message):
        payload = pack_message(message)
        for player_id, sock in sockets.items():
            try:
                sock.sendall(payload)
            except OSError:
                pass  # the receiver thread will notice and clean up


if __name__ == "__main__":
    GameServer().run()
