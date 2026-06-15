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

# Stage B2: the server uses pygame's geometry primitives (Rect) + the game's
# real QuadTree + the shared collision_core. GEOMETRY ONLY -- no display,
# surfaces, assets, or game loop; the server still never instantiates
# Player/Level4. (pygame.Rect needs no display.)
import pygame  # noqa: E402
from QuadTree import QuadTree, QuadTreeManager  # noqa: E402
from hashRect import HashableRect  # noqa: E402
import collision_core  # noqa: E402
from network.protocol import derive_status  # noqa: E402

# Obstacle rect = (x, y, w, h). Uploaded by the client at join (Stage B).
ObstacleRect = Tuple[float, float, float, float]

# Server obstacle-collision tuning (Stage B2). The server iterates the SHARED
# collision_core push-out (the same math the client runs per frame) to fully
# separate a discrete reported position. Small per-pass cap -> minimal overshoot
# past the wall (<= _PUSH_CAP px, and only for already-violating positions).
_PUSH_CAP = 8.0           # px moved per separation pass
_MAX_PASSES = 40          # clears up to _PUSH_CAP * _MAX_PASSES px of penetration
_OVERLAP_TOLERANCE = 2.0  # don't correct grazes <= this (honest players at a wall)
_QUERY_ID = -999_999      # broadphase query id; must not collide with obstacle ids


def _overlap_amounts(player_rect, obstacle_rect):
    """(overlap_x, overlap_y) of two rects; <= 0 on either axis means no overlap."""
    ox = min(player_rect.right, obstacle_rect.right) - max(player_rect.left, obstacle_rect.left)
    oy = min(player_rect.bottom, obstacle_rect.bottom) - max(player_rect.top, obstacle_rect.top)
    return ox, oy


@dataclass
class ServerPlayerState:
    player_id: str
    character: str  # player_info_dir path, e.g. "../Graphics/Orange_Wizard/"
    x: float
    y: float
    direction_x: float = 0.0  # -1, 0, 1 -- mirrors Player.direction.x
    direction_y: float = 0.0
    attacking: bool = False
    status: str = "down_idle"  # drives client animation; server-derived, see derive_status
    # Collision-rect size, sent at join (Stage B). 0 => obstacle resolution off.
    hitbox_w: float = 0.0
    hitbox_h: float = 0.0

    def apply_update(self, x: float, y: float, move_x: float, move_y: float,
                     attacking: bool, obstacle_index: "QuadTree" = None) -> None:
        """Relay the client's authoritative position + re-derive `status`, then
        (Stage B) validate the position against map obstacles.

        v0 / Stage A is a POSITION RELAY. The wire message carries BOTH the
        client's actual position `(x, y)` (from its real `Entity.move()`) AND
        its movement inputs `(move_x, move_y, attacking)`. The server trusts the
        position field and uses the inputs only to derive the animation
        `status`. (Integrating position server-side from inputs -- the original
        v0 design -- diverged hundreds of px from the client's real physics; see
        the plan's "CORRECTION".)

        Stage B adds obstacle VALIDATION on top of the relay: the stored (and
        therefore broadcast) position is pushed out of any map obstacle, so the
        shared/authoritative view can't sit inside a wall. The inputs stay on
        the wire so a later stage can move from "validate" to "simulate" with no
        client/protocol change.
        """
        self.x = x
        self.y = y
        self.direction_x = move_x
        self.direction_y = move_y
        self.attacking = attacking
        self.status = derive_status(self.status, move_x, move_y, attacking)
        if obstacle_index is not None and self.hitbox_w > 0 and self.hitbox_h > 0:
            self.resolve_obstacle_collision(obstacle_index)

    def resolve_obstacle_collision(self, obstacle_index: "QuadTree") -> None:
        """Push (x, y) out of overlapping map obstacles, using the REAL QuadTree
        broadphase + the SHARED `collision_core` push-out (the same code the
        client runs). Stage B2 -- replaces B1's hand-rolled linear-scan MTV.

        Each pass: query the quadtree for obstacles near the player's hitbox,
        keep those overlapping beyond a small tolerance (so honest players at a
        wall *surface* aren't nudged), and apply `collision_core.obstacle_pushout`
        (capped per pass) -- the identical rect math `Entity` uses. Iterating it
        separates a discrete reported position the way the client's per-frame
        push separates over many frames.

        Parallel-maintenance WIN (multiplayer plan): the push-out is now ONE
        function shared with `Entity` -- duplication #1 eliminated for the rect
        path. The conformance test asserts client == server for the same inputs.

        Scope: resolves the realistic cases (walls, edges, corners). A position
        teleported *deep* into a multi-tile cluster (a blatant cheat) may not
        fully escape in `_MAX_PASSES`; the server still reduces penetration.
        Honest clients never produce that (their own collision keeps them at the
        wall surface).
        """
        hw = self.hitbox_w / 2.0
        hh = self.hitbox_h / 2.0
        for _ in range(_MAX_PASSES):
            player_rect = pygame.Rect(
                round(self.x - hw), round(self.y - hh),
                round(self.hitbox_w), round(self.hitbox_h),
            )
            query = HashableRect(player_rect, _id=_QUERY_ID)
            overlapping = []
            for item in obstacle_index.hit(query):
                ox, oy = _overlap_amounts(player_rect, item.rect)
                if ox > _OVERLAP_TOLERANCE and oy > _OVERLAP_TOLERANCE:
                    overlapping.append(item.rect)
            if not overlapping:
                break
            dx, dy = collision_core.obstacle_pushout(player_rect, overlapping, _PUSH_CAP)
            if dx == 0.0 and dy == 0.0:
                break
            self.x += dx
            self.y += dy

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
    # Map collision geometry (Stage B), uploaded by the client at join. First
    # non-empty upload wins -- all clients share the same map on localhost/LAN.
    # The quadtree is the real game `QuadTree`, built from the uploaded rects.
    obstacle_quad_tree: Optional[QuadTree] = None

    def build_obstacle_index(self, obstacles: List[ObstacleRect],
                             map_w: float, map_h: float) -> None:
        """Build the real obstacle `QuadTree` from uploaded (x,y,w,h) rects.

        Same class/broadphase the client uses (Code/QuadTree.py); pygame.Rect is
        pure geometry (no display). Idempotent-ish: first non-empty upload wins
        (call site guards on `obstacle_quad_tree is None`).
        """
        if not obstacles:
            return
        items = [
            HashableRect(pygame.Rect(int(x), int(y), int(w), int(h)), _id=i)
            for i, (x, y, w, h) in enumerate(obstacles)
        ]
        bounding = pygame.Rect(0, 0, max(1, int(map_w)), max(1, int(map_h)))
        self.obstacle_quad_tree = QuadTree(
            items=items, depth=8, bounding_rect=bounding, manager=QuadTreeManager(),
        )
