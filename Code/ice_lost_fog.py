"""Shim — prefer `ice_fog` package (same-map wrap ordeal).

Kept so older draft imports resolve. New code should `import ice_fog`.
"""

from ice_fog import (  # noqa: F401
    EscapeRoute,
    FogCircle,
    FogOrdeal,
    FogOrdealConfig,
    PathStateMachine,
    antipode_inside,
    load_ordeal_config,
    sector_of,
)
from ice_fog.ordeal import FogOrdeal as IceLostFogSystem  # noqa: F401

__all__ = [
    "EscapeRoute",
    "FogCircle",
    "FogOrdeal",
    "FogOrdealConfig",
    "IceLostFogSystem",
    "PathStateMachine",
    "antipode_inside",
    "load_ordeal_config",
    "sector_of",
]
