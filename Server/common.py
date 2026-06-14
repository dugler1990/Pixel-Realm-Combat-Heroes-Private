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
from typing import Dict, List

_CODE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code"))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from network.protocol import derive_status  # noqa: E402


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

    def apply_update(self, x: float, y: float, move_x: float, move_y: float, attacking: bool) -> None:
        """Relay the client's authoritative position + re-derive `status`.

        v0 / Stage A is a POSITION RELAY. The wire message carries BOTH the
        client's actual position `(x, y)` (from its real `Entity.move()`) AND
        its movement inputs `(move_x, move_y, attacking)`. In v0 the server
        trusts the position field and only uses the inputs to derive the
        animation `status`.

        Why not integrate position server-side from the inputs (the original
        v0 design)? Because a server-side linear integration diverged by
        hundreds of pixels from the client's real physics (acceleration/
        friction/mask-collision) -- the local player's position is
        client-owned and unvalidated in v0 (multiplayer plan ownership table).

        The inputs are kept ON THE WIRE precisely so the safe model is a
        SERVER-ONLY upgrade later: Stage B/C starts simulating from these same
        inputs and stops trusting the client's `(x, y)` (validation/
        reconciliation), with zero client/protocol change. `tick`/
        `server_time_ms` in the broadcast already carry what interpolation
        (Stage D) needs.
        """
        self.x = x
        self.y = y
        self.direction_x = move_x
        self.direction_y = move_y
        self.attacking = attacking
        self.status = derive_status(self.status, move_x, move_y, attacking)

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
