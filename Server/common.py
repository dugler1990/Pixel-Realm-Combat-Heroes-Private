"""Minimal authoritative state model for the multiplayer server.

This deliberately does NOT instantiate real `Player`/`CombatUnit`/`Level4`
objects (see the multiplayer plan's "Server design" section) -- those are
deeply coupled to pygame surfaces, asset loading, and spatial indices.
Instead this is a tiny, headless, msgpack-friendly model of just enough
per-player state to broadcast movement/animation to clients.
"""

import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_CODE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code"))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

# The server checks reported player positions with the same wall code the client moves
# with (collision_core), against its own Level4's obstacle QuadTree. GEOMETRY ONLY -- Rect
# and Mask, no display. (pygame.Rect / pygame.Mask need no display.)
from QuadTree import QuadTree  # noqa: E402
import collision_core  # noqa: E402
from network.protocol import derive_status  # noqa: E402

WallFoot = Tuple[int, int, int, int]


@dataclass
class ServerPlayerState:
    player_id: str
    character: str  # player_info_dir path, e.g. "../Graphics/Orange_Wizard/"
    # The last ACCEPTED position (the client's hitbox centre). The broadcast and the
    # server's Level4 read this, never a report that hasn't been checked.
    x: float
    y: float
    direction_x: float = 0.0  # -1, 0, 1 -- mirrors Player.direction.x
    direction_y: float = 0.0
    attacking: bool = False
    status: str = "down_idle"  # drives client animation; server-derived, see derive_status
    # Hitbox size and wall footprint (dx, dy, w, h relative to hitbox.topleft), sent at
    # join. No footprint => reports are accepted unchecked.
    hitbox_w: float = 0.0
    hitbox_h: float = 0.0
    wall_foot: Optional[WallFoot] = None
    # CS4: the client relays its real player's health each frame so the server's
    # enemy aggro can drop a downed player. Defaults alive until first reported.
    health: float = 100.0
    # The latest reported position, waiting for accept_report on the sim thread.
    reported_x: Optional[float] = None
    reported_y: Optional[float] = None

    def apply_update(self, x: float, y: float, move_x: float, move_y: float,
                     attacking: bool, health: float = None) -> None:
        """Store the client's reported position + re-derive `status` (receiver thread).

        The wire message carries BOTH the client's actual position `(x, y)` (from its
        real `Entity.move()`) AND its movement inputs `(move_x, move_y, attacking)`; the
        inputs only derive the animation `status`. The position waits in
        `reported_x/y` until `accept_report` checks it against the walls on the sim
        thread, so nothing ever broadcasts an unchecked report.
        """
        self.reported_x = x
        self.reported_y = y
        self.direction_x = move_x
        self.direction_y = move_y
        self.attacking = attacking
        self.status = derive_status(self.status, move_x, move_y, attacking)
        if health is not None:
            self.health = health

    def accept_report(self, obstacle_tree: "QuadTree") -> bool:
        """Accept the latest report, or drop it; True if it was dropped.

        A report whose footprint overlaps no wall is accepted exactly. One inside a wall
        (lag or a cheat) is dropped and the player stays at the last accepted position:
        one check, where moving toward the report pixel by pixel cost one check per
        pixel of the jump. An honest client's reports are always clear, so it is never
        corrected.
        """
        if self.reported_x is None:
            return False
        rx, ry = self.reported_x, self.reported_y
        self.reported_x = self.reported_y = None
        if (obstacle_tree is None or self.wall_foot is None
                or self.hitbox_w <= 0 or self.hitbox_h <= 0):
            self.x, self.y = rx, ry
            return False
        size = (self.hitbox_w, self.hitbox_h)
        reported = collision_core.hitbox_from_center((rx, ry), size)
        if collision_core.hits_wall(
                collision_core.foot_rect(reported, self.wall_foot), obstacle_tree):
            return True
        self.x, self.y = rx, ry
        return False

    def to_snapshot(self) -> dict:
        return {
            "character": self.character,
            "x": self.x,
            "y": self.y,
            "direction_x": self.direction_x,
            "direction_y": self.direction_y,
            "status": self.status,
        }


@dataclass
class GameState:
    players: Dict[str, ServerPlayerState] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    # Lifecycle notices (player_joined/player_left) queued by receiver threads,
    # drained and broadcast by the tick loop -- keeps the tick loop the sole
    # socket writer (see "Threading model" in the multiplayer plan).
    pending_events: List[dict] = field(default_factory=list)
    # The walls reported positions are checked against: the server's own Level4's
    # obstacle QuadTree (the one its enemies collide with), set when the level is built.
    # None until then (and in relay mode, unless a test injects one).
    obstacle_quad_tree: Optional[QuadTree] = None
    # First client to join is flagged the host (legacy field, broadcast in
    # state_update). The server-authoritative pivot made it vestigial -- the
    # SERVER owns the enemy sim (it runs the real Level4); host_id no longer
    # decides who simulates. Kept until the clients stop reading it.
    host_player_id: Optional[str] = None
    # The live enemy render-state the sim loop writes each tick from the real
    # Level4 (gather_enemy_relay) and the broadcast loop ships to every client.
    enemies: List[dict] = field(default_factory=list)
    # player->enemy hits (MSG_HIT_ENEMY) from ANY client, queued by receiver
    # threads and drained by the sim loop, which applies each to the authoritative
    # Level4 enemy. Same threading discipline as pending_events.
    pending_enemy_hits: List[dict] = field(default_factory=list)
    # CS5b: shared-loot pickup requests (MSG_PICKUP_ITEM) from clients, queued by
    # receiver threads and drained by the sim loop, which arbitrates them against
    # the server's drop registry (first claim wins) -> item_removed broadcast.
    pending_pickups: List[dict] = field(default_factory=list)
    # (CS3/CS5b: the old `pending_to_host` queue -- joiner->host enemy hits + loot
    #  pickups -- was removed. The server is authoritative now: hits go to
    #  pending_enemy_hits, pickups to pending_pickups, both applied in the sim loop.)
