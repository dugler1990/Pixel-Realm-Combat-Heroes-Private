"""Same-map fog ordeal: wrap containment + sequence/pad/task escapes."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ice_fog.config import FogOrdealConfig
from ice_fog.geometry import FogCircle, antipode_inside, pad_hit, sector_of
from ice_fog.path_state import PadSequence, PathStateMachine


class FogOrdeal:
    """Track tangled state inside a fog circle and emit plain event dicts."""

    def __init__(self, config: FogOrdealConfig):
        self.config = config
        self.circle: FogCircle = config.circle
        self.tangled = False
        self.x = config.circle.cx
        self.y = config.circle.cy
        self._last_teleport_ms = -10**9
        self.path = PathStateMachine(list(config.routes))
        self.pads = (
            PadSequence(list(config.pads), list(config.pad_order))
            if config.pads and config.pad_order
            else None
        )
        self._whisper_sent = False

    def update_position(self, x: float, y: float, now_ms: int = 0) -> List[Dict]:
        events: List[Dict] = []
        inside = self.circle.is_inside(x, y)

        if not self.tangled:
            if inside:
                self.tangled = True
                self.x, self.y = x, y
                events.append({"type": "entered", "x": x, "y": y})
                if self.config.whisper_on_enter and not self._whisper_sent:
                    self._whisper_sent = True
                    events.append(
                        {"type": "whisper", "line_id": self.config.whisper_on_enter}
                    )
            else:
                self.x, self.y = x, y
            return events

        # Tangled: apply position, then contain if outside.
        self.x, self.y = x, y
        if inside:
            if self.pads is not None:
                for pad in self.pads.pads:
                    if pad_hit(
                        self.circle, x, y, pad.angle_deg, pad.half_width_deg
                    ):
                        events.append({"type": "pad_hit", "pad_id": pad.pad_id})
                        if self.pads.hit(pad.pad_id):
                            events.extend(self._escape("pads"))
                        break
            return events

        # Outside while tangled → wrap (with cooldown).
        if now_ms - self._last_teleport_ms < self.config.cooldown_ms:
            # Hold last inside suggestion: snap back toward antipode of attempt.
            nx, ny = antipode_inside(
                self.circle, x, y, self.config.inset
            )
            self.x, self.y = nx, ny
            return events

        sector = sector_of(self.circle, x, y)
        nx, ny = antipode_inside(self.circle, x, y, self.config.inset)
        self._last_teleport_ms = now_ms
        events.append(
            {
                "type": "teleported",
                "from": (x, y),
                "to": (nx, ny),
                "sector": sector,
            }
        )
        self.x, self.y = nx, ny

        if self.config.track_sequence_on_wrap and self.path.routes:
            events.append({"type": "sequence_step", "direction": sector})
            route = self.path.push(sector)
            if route is not None:
                events.extend(self._escape("sequence", route_name=route.name))
            elif not self.path.steps:
                # push cleared on mismatch — still emit reset marker via empty steps
                events.append({"type": "sequence_reset"})

        return events

    def complete_escape(self) -> List[Dict]:
        if not self.tangled:
            return []
        return self._escape("task")

    def _escape(self, how: str, route_name: Optional[str] = None) -> List[Dict]:
        self.tangled = False
        self._whisper_sent = False
        self.path.reset()
        if self.pads is not None:
            self.pads.reset()
        payload: Dict = {"type": "escaped", "how": how}
        if route_name is not None:
            payload["route"] = route_name
        return [payload]

    def position(self) -> Tuple[float, float]:
        return (self.x, self.y)
