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

_CODE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code"))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from network.protocol import (  # noqa: E402
    MSG_INPUT,
    MSG_JOIN,
    MSG_LEAVE,
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


class GameServer:
    def __init__(self, host="0.0.0.0", port=12345):
        self.host = host
        self.port = port
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_socket.bind((host, port))
        self.listen_socket.listen()

        self.game_state = GameState()
        self.client_sockets = {}  # player_id -> socket, guarded by game_state.lock
        self.tick = 0

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
                        # Stage B2: first non-empty geometry upload wins; build
                        # the real obstacle QuadTree from it (all clients share
                        # the same map on localhost/LAN).
                        obstacles = message.get("obstacles")
                        if obstacles and self.game_state.obstacle_quad_tree is None:
                            rects = [
                                (float(o[0]), float(o[1]), float(o[2]), float(o[3])) for o in obstacles
                            ]
                            self.game_state.build_obstacle_index(
                                rects,
                                float(message.get("map_width", 0.0)),
                                float(message.get("map_height", 0.0)),
                            )
                            print(f"[server] built obstacle quadtree from {len(rects)} rects ({player_id})")
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
                        if player is not None:
                            # v0 position relay: trust the client's reported (x, y),
                            # use move_x/move_y/attacking only to derive status.
                            # Stage B2: apply_update then validates against the
                            # obstacle quadtree (None until geometry is uploaded).
                            player.apply_update(
                                float(message.get("x", player.x)),
                                float(message.get("y", player.y)),
                                float(message.get("move_x", 0.0)),
                                float(message.get("move_y", 0.0)),
                                bool(message.get("attacking", False)),
                                self.game_state.obstacle_quad_tree,
                            )

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
                self._broadcast_tick()
                accumulator -= TICK_DT
            time.sleep(0.001)

    # -- snapshot-then-release: copy state out, send outside the lock (sole writer) --

    def _broadcast_tick(self):
        with self.game_state.lock:
            events = list(self.game_state.pending_events)
            self.game_state.pending_events.clear()
            state_message = {
                "type": MSG_STATE_UPDATE,
                "tick": self.tick,
                "server_time_ms": time.monotonic() * 1000.0,
                "players": {pid: p.to_snapshot() for pid, p in self.game_state.players.items()},
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
