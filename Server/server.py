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

Two modes:
- Open (no ticket secret): anyone may join with any player_id. Only allowed on
  127.0.0.1 -- the existing tests and the local "Local co-op (dev)" shortcut.
- Match (started by Server/launcher.py with --match-id and GAME_TICKET_SECRET): one
  match on one map. A join needs a valid signed ticket (Server/tickets.py); the
  player's id and character come from the ticket. The process exits by itself when
  the match is over.
"""

import argparse
import os
import socket
import sys
import threading
import time

# Headless: the server builds and runs the real Level4 (its surfaces and masks)
# without a real display, under the dummy SDL driver.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_CODE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code"))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from network.protocol import (  # noqa: E402
    MAX_CLIENT_MESSAGE_BYTES,
    MSG_HIT_ENEMY,
    MSG_INPUT,
    MSG_JOIN,
    MSG_JOIN_REJECTED,
    MSG_LEAVE,
    MSG_PICKUP_ITEM,
    MSG_PLAYER_JOINED,
    MSG_PLAYER_LEFT,
    MSG_STATE_UPDATE,
    PROTOCOL_VERSION,
    pack_message,
    recv_message,
)

from common import GameState, ServerPlayerState  # noqa: E402
import tickets  # noqa: E402

# Broadcast rate. Clients render their own player live every frame but only
# learn about remotes at this rate, so during motion a remote trails by up to
# one tick of movement. 60Hz (vs the original 30) halves that visible lag and
# matches a 60fps client. v0 stays a relay -- this only paces broadcasts.
TICK_RATE_HZ = 60
TICK_DT = 1.0 / TICK_RATE_HZ

# The co-op level the server loads by default, and the maps a match may use
# (Code/level_layouts.py).
from level_layouts import MP_LEVEL_NUMBER, MP_MAPS  # noqa: E402

# Match mode: a connection must send a valid join this soon after connecting, or it is
# dropped -- otherwise idle connections could hold the match ports.
JOIN_TIMEOUT_SECONDS = 5.0
# Match mode, CLI only: when the process ends by itself.
JOIN_WINDOW_SECONDS = 120.0     # nobody joined this long after the level loaded
EMPTY_GRACE_SECONDS = 10.0      # everyone left and nobody came back
DEFAULT_MAX_MATCH_SECONDS = 4 * 3600

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


def _wall_foot(raw):
    """The join message's wall footprint as an int tuple, or None if absent."""
    if not raw or len(raw) != 4:
        return None
    return tuple(int(v) for v in raw)


class GameServer:
    def __init__(self, host="127.0.0.1", port=12345, run_world_sim=True,
                 level_number=MP_LEVEL_NUMBER, match_id=None, ticket_secret=None,
                 exit_when_done=False, max_match_seconds=DEFAULT_MAX_MATCH_SECONDS):
        if ticket_secret is None and host not in _LOOPBACK_HOSTS:
            raise ValueError("refusing open joins on a non-loopback address; "
                             "give a match id and GAME_TICKET_SECRET")
        if ticket_secret is not None and not match_id:
            raise ValueError("a ticket secret needs a match id")
        if level_number not in MP_MAPS:
            raise ValueError(f"level {level_number} is not a multiplayer map (MP_MAPS)")
        self.host = host
        self.port = port
        self.level_number = level_number
        self.match_id = match_id
        self.ticket_secret = ticket_secret
        # Only the CLI sets this: os._exit would kill a test runner.
        self.exit_when_done = exit_when_done
        self.max_match_seconds = max_match_seconds
        self._listening_at = None
        self._ever_joined = False
        self._empty_since = None
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
        # client has joined; it loads its own map. None until then.
        self.server_level = None

    @property
    def match_mode(self):
        return self.ticket_secret is not None

    def run(self):
        # Match mode loads the level BEFORE announcing "listening": the launcher treats an
        # accepting port as "ready", so players never wait on the level build.
        if self.match_mode and self.run_world_sim:
            self._build_server_level()
        self._listening_at = time.monotonic()
        print(f"[server] listening on {self.host}:{self.port}", flush=True)
        threading.Thread(target=self._simulation_loop, daemon=True).start()
        self._accept_loop()

    def _accept_loop(self):
        while True:
            client_socket, addr = self.listen_socket.accept()
            print(f"[server] connection from {addr}")
            threading.Thread(target=self._client_receiver, args=(client_socket, addr), daemon=True).start()

    # -- per-client receiver thread: pure reader/mutator, never writes to a socket --

    def _admit(self, message):
        """Match mode: (player_id, character) from a valid ticket, or the refusal reason."""
        if message.get("protocol") != PROTOCOL_VERSION:
            return "Your game is out of date."
        try:
            payload = tickets.verify(self.ticket_secret, message.get("ticket"), self.match_id)
        except tickets.TicketError as exc:
            return str(exc)
        user_id, character = payload.get("uid"), payload.get("chr")
        if not isinstance(user_id, str) or not user_id or not isinstance(character, str):
            return "malformed ticket"
        return user_id, character

    @staticmethod
    def _reject(client_socket, reason):
        # The one place a receiver thread writes to a socket. Safe: this socket was never
        # put in client_sockets, so the sim loop (the sole writer otherwise) never sees it.
        try:
            client_socket.sendall(pack_message({"type": MSG_JOIN_REJECTED, "reason": reason}))
        except OSError:
            pass
        print(f"[server] join rejected: {reason}", flush=True)

    @staticmethod
    def _drop_if_not_joined(client_socket, joined):
        # Timer thread: wakes the blocked recv by shutting the socket down. A total
        # deadline, so a client dribbling one byte every few seconds is dropped too.
        if not joined.is_set():
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _client_receiver(self, client_socket, addr):
        player_id = None
        joined = threading.Event()
        deadline = None
        if self.match_mode:
            deadline = threading.Timer(JOIN_TIMEOUT_SECONDS, self._drop_if_not_joined,
                                       args=(client_socket, joined))
            deadline.daemon = True
            deadline.start()
        try:
            while True:
                message = recv_message(client_socket, max_bytes=MAX_CLIENT_MESSAGE_BYTES)
                msg_type = message.get("type")

                if msg_type == MSG_JOIN:
                    if player_id is not None:
                        continue  # one join per connection
                    if self.match_mode:
                        admitted = self._admit(message)
                        if isinstance(admitted, str):
                            self._reject(client_socket, admitted)
                            break
                        new_id, character = admitted
                    else:
                        new_id, character = message["player_id"], message["character"]
                    player = ServerPlayerState(
                        player_id=new_id,
                        character=character,
                        x=float(message["x"]),
                        y=float(message["y"]),
                        hitbox_w=float(message.get("hitbox_w", 0.0)),
                        hitbox_h=float(message.get("hitbox_h", 0.0)),
                        wall_foot=_wall_foot(message.get("wall_foot")),
                    )
                    # Check and insert under one lock, so two connections with the same
                    # ticket can't both get in.
                    with self.game_state.lock:
                        duplicate = self.match_mode and new_id in self.game_state.players
                        if not duplicate:
                            joined.set()
                            player_id = new_id
                            self._ever_joined = True
                            self.game_state.players[player_id] = player
                            self.client_sockets[player_id] = client_socket
                            # Co-op (Stage C): first client to join is the host (runs
                            # the real enemy sim + relays it). Each client learns its
                            # role from host_id in state_update.
                            if self.game_state.host_player_id is None:
                                self.game_state.host_player_id = player_id
                                print(f"[server] {player_id} is the host (enemy authority)")
                            # Server-authoritative pivot: the server LOADS ITS OWN map
                            # and runs the real Level4 -- it no longer accepts an enemy
                            # spawn spec from clients.
                            self.game_state.pending_events.append({
                                "type": MSG_PLAYER_JOINED,
                                "player_id": player_id,
                                "character": player.character,
                                "x": player.x,
                                "y": player.y,
                            })
                    if duplicate:
                        # player_id stays None, so the finally below can't drop the
                        # player who is already connected under this id.
                        self._reject(client_socket, "You are already in this match.")
                        break
                    if deadline is not None:
                        deadline.cancel()
                    print(f"[server] {player_id} joined as {player.character}")

                elif msg_type == MSG_INPUT:
                    with self.game_state.lock:
                        player = self.game_state.players.get(player_id)
                        # The SERVER owns the enemy sim (it runs the real Level4
                        # and the sim loop writes game_state.enemies each tick), so
                        # any `enemies` a client puts on an input message is ignored.
                        if player is not None:
                            # Store the report; the sim loop checks it against the
                            # walls (_accept_reports) before anything reads it.
                            health = message.get("health")
                            player.apply_update(
                                float(message.get("x", player.x)),
                                float(message.get("y", player.y)),
                                float(message.get("move_x", 0.0)),
                                float(message.get("move_y", 0.0)),
                                bool(message.get("attacking", False)),
                                health=float(health) if health is not None else None,
                            )

                elif msg_type == MSG_HIT_ENEMY:
                    # CS3: a client's attack hit a (server-owned) enemy. Queue it
                    # for the sim loop, which applies it to the authoritative enemy.
                    # Accepted from ANY joined client (every client renders puppets +
                    # can attack); the server is the single apply-point now. The
                    # connection's own id overwrites whatever player_id the client wrote.
                    if player_id is not None:
                        with self.game_state.lock:
                            self.game_state.pending_enemy_hits.append(
                                dict(message, player_id=player_id))

                elif msg_type == MSG_PICKUP_ITEM:
                    # CS5b: a client claims a shared drop. Queue it for the sim loop,
                    # which arbitrates against the server's drop registry (first
                    # claim wins) and broadcasts the item_removed award -- to the
                    # connection that asked, never to an id the client names.
                    if player_id is not None:
                        with self.game_state.lock:
                            self.game_state.pending_pickups.append(
                                dict(message, player_id=player_id))

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

    # -- fixed-rate sim + broadcast loop --
    # The server does NOT simulate player movement: each tick it checks the latest
    # reported positions against the walls (_accept_reports), steps the world sim,
    # and broadcasts at a steady TICK_RATE_HZ, decoupled from clients' send rates.

    def _simulation_loop(self):
        accumulator = 0.0
        last = time.monotonic()
        next_over_check = 0.0
        while True:
            now = time.monotonic()
            accumulator += now - last
            last = now
            while accumulator >= TICK_DT:
                self.tick += 1
                self._accept_reports()
                self._step_world_sim()
                self._broadcast_tick()
                accumulator -= TICK_DT
            if self.exit_when_done and now >= next_over_check:
                next_over_check = now + 1.0
                reason = self._match_over_reason(now)
                if reason is not None:
                    print(f"[server] match {self.match_id} over: {reason}", flush=True)
                    # Not listen_socket.close(): on Linux that doesn't reliably wake a
                    # blocked accept(). The launcher reaps the exit.
                    os._exit(0)
            time.sleep(0.001)

    def _match_over_reason(self, now):
        """Match mode, CLI only: why this match should end now, or None."""
        if self._listening_at is None:
            return None
        if now - self._listening_at > self.max_match_seconds:
            return "time limit reached"
        with self.game_state.lock:
            have_players = bool(self.game_state.players)
        if have_players:
            self._empty_since = None
            return None
        if not self._ever_joined:
            return "nobody joined" if now - self._listening_at > JOIN_WINDOW_SECONDS else None
        if self._empty_since is None:
            self._empty_since = now
        return "everyone left" if now - self._empty_since > EMPTY_GRACE_SECONDS else None

    # -- check reported player positions against the walls --
    # Runs on the sim thread every tick, in relay mode too, before the world sim, so
    # Level4 and the broadcast only ever see checked positions. Same walls and same
    # collision_core code the client moves with, so an honest client is never corrected.
    def _accept_reports(self):
        gs = self.game_state
        with gs.lock:
            tree = gs.obstacle_quad_tree
            for pid, player in gs.players.items():
                rx, ry = player.reported_x, player.reported_y
                if player.accept_report(tree):
                    print(f"[server] dropped {pid}'s report ({rx}, {ry}): footprint in a "
                          f"wall; kept ({player.x}, {player.y})")

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
        self.server_level = build_headless_level(level_number=self.level_number)
        # One map: reported positions are checked against the walls its enemies use.
        with self.game_state.lock:
            self.game_state.obstacle_quad_tree = self.server_level.layout_manager.obstacle_quad_tree
        # Park the sentinel off-map; networked players are added each tick.
        self.server_level.player.rect.center = self._SENTINEL_PARK
        self.server_level.player.hitbox.center = self._SENTINEL_PARK
        print(f"[server] world sim online (real Level4, level {self.level_number}): "
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Headless authoritative game server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--map", type=int, default=MP_LEVEL_NUMBER, help="level number (MP_MAPS)")
    parser.add_argument("--match-id", default=None,
                        help="match mode: admit only tickets for this match, exit when it is over")
    args = parser.parse_args(argv)
    secret = None
    if args.match_id:
        # The secret only ever comes from the environment: `ps` shows argv to everyone.
        secret = tickets.secret_from_env(os.environ.get("GAME_TICKET_SECRET"))
    max_seconds = float(os.environ.get("MAX_MATCH_SECONDS", DEFAULT_MAX_MATCH_SECONDS))
    GameServer(host=args.host, port=args.port, level_number=args.map, match_id=args.match_id,
               ticket_secret=secret, exit_when_done=bool(args.match_id),
               max_match_seconds=max_seconds).run()


if __name__ == "__main__":
    main()
