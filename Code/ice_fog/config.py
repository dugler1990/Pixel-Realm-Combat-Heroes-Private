"""Load fog ordeal JSON configs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ice_fog.geometry import FogCircle
from ice_fog.path_state import EscapeRoute, PadSpec


@dataclass
class FogOrdealConfig:
    circle: FogCircle
    inset: float = 8.0
    cooldown_ms: int = 250
    whisper_on_enter: Optional[str] = "fog_enter"
    routes: List[EscapeRoute] = field(default_factory=list)
    pads: List[PadSpec] = field(default_factory=list)
    pad_order: List[str] = field(default_factory=list)
    track_sequence_on_wrap: bool = True


def load_ordeal_config(path) -> FogOrdealConfig:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return ordeal_config_from_dict(data)


def ordeal_config_from_dict(data: Dict) -> FogOrdealConfig:
    c = data.get("circle") or {}
    circle = FogCircle(
        float(c.get("cx", 200)),
        float(c.get("cy", 200)),
        float(c.get("r", 120)),
    )
    routes: List[EscapeRoute] = []
    for name, seq in (data.get("escape_sequences") or {}).items():
        dest = (data.get("escape_destinations") or {}).get(name) or {}
        tile = dest.get("tile") or [0, 0]
        routes.append(
            EscapeRoute(
                name=str(name),
                sequence=list(seq),
                layout=str(dest.get("layout") or ""),
                tile=(int(tile[0]), int(tile[1])),
            )
        )
    pads: List[PadSpec] = []
    for p in data.get("pads") or []:
        pads.append(
            PadSpec(
                pad_id=str(p["id"]),
                angle_deg=float(p.get("angle_deg", 0)),
                half_width_deg=float(p.get("half_width_deg", 25)),
            )
        )
    order = list(data.get("pad_order") or [p.pad_id for p in pads])
    return FogOrdealConfig(
        circle=circle,
        inset=float(data.get("inset", 8)),
        cooldown_ms=int(data.get("cooldown_ms", 250)),
        whisper_on_enter=data.get("whisper_on_enter", "fog_enter"),
        routes=routes,
        pads=pads,
        pad_order=order,
        track_sequence_on_wrap=bool(data.get("track_sequence_on_wrap", True)),
    )
