"""Env-driven runtime for the rudimentary multiplayer milestone (Main2 bootstrap).

Mirrors Code/benchmark_runtime.py / Code/rts_validation_runtime.py: a
@dataclass singleton built from PRCH_MULTIPLAYER_* env vars, wired into
Game.__init__ as a purely additive elif branch alongside
RTS_VALIDATION_RUNTIME / BENCHMARK_RUNTIME (see the multiplayer plan's
"Game flow integration" section). Unset by default, so it is a no-op
unless PRCH_MULTIPLAYER_ENABLED=1.
"""

import hashlib
import math
import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw) if raw is not None else default


def _default_spawn_offset(player_id: str) -> tuple:
    """Deterministic, well-spread spawn offset (px) keyed by player_id.

    Every client bootstraps to the SAME fixed local spawn -- Level4 puts every
    player at (15*TILESIZE, 25*TILESIZE) -- so without distinct offsets two
    clients start stacked on top of each other (see the plan's M2-M3
    implementation addenda). We place each player_id at a stable point on a
    small ring around that spawn. Uses hashlib (not built-in hash(), which is
    salted per-process via PYTHONHASHSEED) so the offset is reproducible.
    Explicit PRCH_MULTIPLAYER_SPAWN_X/Y override this entirely.
    """
    digest = hashlib.md5(player_id.encode("utf-8")).digest()
    angle = (digest[0] / 255.0) * 2.0 * math.pi
    radius = 64.0 + (digest[1] / 255.0) * 64.0  # 64..128 px from the shared spawn
    return (math.cos(angle) * radius, math.sin(angle) * radius)


def _resolve_spawn(name: str, default: float) -> float:
    # Explicit env wins; otherwise fall back to the per-player_id default.
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class MultiplayerRuntime:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 12345
    player_id: str = "player1"
    character: str = "../Graphics/Orange_Wizard/"
    spawn_x: float = 0.0
    spawn_y: float = 0.0


_player_id = _env_str("PRCH_MULTIPLAYER_PLAYER_ID", "player1")
_default_dx, _default_dy = _default_spawn_offset(_player_id)

MULTIPLAYER_RUNTIME = MultiplayerRuntime(
    enabled=_env_bool("PRCH_MULTIPLAYER_ENABLED", False),
    host=_env_str("PRCH_MULTIPLAYER_HOST", "127.0.0.1"),
    port=_env_int("PRCH_MULTIPLAYER_PORT", 12345),
    player_id=_player_id,
    character=_env_str("PRCH_MULTIPLAYER_CHARACTER", "../Graphics/Orange_Wizard/"),
    spawn_x=_resolve_spawn("PRCH_MULTIPLAYER_SPAWN_X", _default_dx),
    spawn_y=_resolve_spawn("PRCH_MULTIPLAYER_SPAWN_Y", _default_dy),
)
