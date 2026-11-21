"""Ice fog ordeal — same-map wrap containment and escape helpers."""

from ice_fog.config import FogOrdealConfig, load_ordeal_config, ordeal_config_from_dict
from ice_fog.geometry import FogCircle, antipode_inside, is_inside, sector_of
from ice_fog.ordeal import FogOrdeal
from ice_fog.path_state import EscapeRoute, PadSequence, PathStateMachine
from ice_fog.whisper import load_wind_whispers, whisper_event, whisper_panel_snapshot

__all__ = [
    "FogCircle",
    "FogOrdeal",
    "FogOrdealConfig",
    "EscapeRoute",
    "PadSequence",
    "PathStateMachine",
    "antipode_inside",
    "is_inside",
    "load_ordeal_config",
    "load_wind_whispers",
    "ordeal_config_from_dict",
    "sector_of",
    "whisper_event",
    "whisper_panel_snapshot",
]
