"""Client-side networking for the rudimentary multiplayer milestone.

`MultiplayerClient` owns a single TCP socket plus a daemon background
thread that reads framed messages and pushes them onto a `queue.Queue`.

Per the multiplayer plan's "Client networking layer": the receive thread
must never touch pygame objects directly -- sprite groups, surfaces, etc.
aren't thread-safe to mutate off the main thread. It only parses framed
messages onto the queue; the main thread (Level4.run) is the only thing
that drains it, via `poll()`. Outbound sends (`send_join`/`send_input`/
`send_leave`) also happen on the main thread -- sendall() of ~150 bytes is
fast enough at 30fps on localhost/LAN to not need its own thread.
"""

import queue
import socket
import threading

from .protocol import (
    MSG_HIT_ENEMY,
    MSG_INPUT,
    MSG_JOIN,
    MSG_LEAVE,
    MSG_PICKUP_ITEM,
    pack_message,
    recv_message,
)


class MultiplayerClient:
    def __init__(self, host: str, port: int, player_id: str):
        self.player_id = player_id
        self.inbox = queue.Queue()
        self._seq = 0
        self._closed = False

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((host, port))

        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def _receive_loop(self) -> None:
        while not self._closed:
            try:
                message = recv_message(self.socket)
            except (ConnectionError, OSError):
                break
            self.inbox.put(message)

    def send_join(self, character: str, x: float, y: float,
                  hitbox_w: float = 0.0, hitbox_h: float = 0.0,
                  obstacles=None, map_width: float = 0.0, map_height: float = 0.0,
                  enemy_spawns=None, spawn_areas=None) -> None:
        """Announce this player. Stage B optionally uploads the map's obstacle
        rects + dimensions (the client already has them) + this player's hitbox
        size, so the server can build a quadtree and validate positions against
        walls. CS2 (server-authoritative co-op) optionally uploads the map's
        enemy spawn spec (the TMX placed-enemy configs) so the server can build
        and own the enemy sim. All default off, so a client that omits them just
        gets the v0 relay (no server collision/enemies)."""
        message = {
            "type": MSG_JOIN,
            "player_id": self.player_id,
            "character": character,
            "x": x,
            "y": y,
            "hitbox_w": hitbox_w,
            "hitbox_h": hitbox_h,
        }
        if obstacles:
            message["obstacles"] = obstacles
            message["map_width"] = map_width
            message["map_height"] = map_height
        if enemy_spawns:
            message["enemy_spawns"] = enemy_spawns
        if spawn_areas:
            message["spawn_areas"] = spawn_areas
        if enemy_spawns or spawn_areas:
            # map dims feed the server's sim world even if obstacles were omitted.
            message["map_width"] = map_width
            message["map_height"] = map_height
        self._send(message)

    def send_state(self, x: float, y: float, move_x: float, move_y: float, attacking: bool,
                   health=None) -> None:
        """Report the local player's actual position + movement inputs.

        v0 / Stage A is a position relay: the server trusts (x, y) and uses
        move_x/move_y/attacking only to derive the animation status. The inputs
        ride along so a later (Stage B/C) server can switch to simulating from
        them and validating position -- a server-only change, no client edit.

        CS4 (server-authoritative co-op): also relay the player's current
        `health` so the server's enemy aggro can drop a downed player (and a
        future spectate/respawn flow can react). Omitted -> server keeps the
        player marked alive.
        """
        self._seq += 1
        message = {
            "type": MSG_INPUT,
            "player_id": self.player_id,
            "seq": self._seq,
            "x": x,
            "y": y,
            "move_x": move_x,
            "move_y": move_y,
            "attacking": attacking,
        }
        if health is not None:
            message["health"] = health
        self._send(message)

    def send_hit_enemy(self, enemy_id, amount: float, attack_type) -> None:
        """CS3: report that THIS client's attack hit a (server-owned) enemy.
        `enemy_id` is the server's id for that enemy; `amount` is resolved from
        this client's player stats. The SERVER applies it to the authoritative
        enemy. Sent by every client (all render puppets + can attack)."""
        self._send({
            "type": MSG_HIT_ENEMY,
            "player_id": self.player_id,
            "enemy_id": enemy_id,
            "amount": amount,
            "attack_type": attack_type,
        })

    # CS5b: every client claims shared loot from the SERVER (which arbitrates,
    # first claim wins). The death/drop/removal events are SERVER-emitted -- no
    # client sends them (closing that cheat vector), so there are no
    # send_enemy_died/send_item_dropped/send_item_removed methods anymore.
    def send_pickup_item(self, drop_id) -> None:
        self._send({"type": MSG_PICKUP_ITEM, "player_id": self.player_id, "drop_id": drop_id})

    def send_leave(self) -> None:
        self._send({"type": MSG_LEAVE, "player_id": self.player_id})

    def _send(self, message: dict) -> None:
        try:
            self.socket.sendall(pack_message(message))
        except OSError:
            pass

    def poll(self) -> list:
        """Drain and return all messages received since the last poll."""
        messages = []
        while True:
            try:
                messages.append(self.inbox.get_nowait())
            except queue.Empty:
                break
        return messages

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.send_leave()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
