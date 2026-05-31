"""Folder-based phased visuals: timed sequences (build sites) and layered amount (ice shelf)."""

import os

import pygame

from Support import import_folder

from .assets import load_sprite

_DEFAULT_FRAME_INTERVAL = 0.2
_RTS_GRAPHICS_SUBDIR = "rts"


def rts_graphics_root():
    code_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(code_dir, "..", "..", "Graphics", _RTS_GRAPHICS_SUBDIR))


def _float_val(data, *keys, default=0.0):
    for key in keys:
        if key in data and data[key] is not None:
            return float(data[key])
    return float(default)


def load_folder_frames(folder, sprite_keys=None, fallback_size=(32, 32)):
    """Load frames from Graphics/rts/{folder}/ or from sprite_key list."""
    frames = []
    folder_name = str(folder or "").strip()
    if folder_name:
        path = os.path.join(rts_graphics_root(), folder_name)
        if os.path.isdir(path):
            frames = import_folder(path)
    if not frames and sprite_keys:
        for key in sprite_keys:
            frames.append(load_sprite(str(key), fallback_size=fallback_size))
    if not frames:
        frames = [load_sprite("node_ice_shelf", fallback_size=fallback_size)]
    return frames


class FrameCycler:
    """Advance through a list of surfaces like a sprite animation."""

    def __init__(self, frames, frame_interval_sec=_DEFAULT_FRAME_INTERVAL):
        self.frames = list(frames) if frames else []
        self.frame_interval_sec = max(0.05, float(frame_interval_sec or _DEFAULT_FRAME_INTERVAL))
        self._frame_index = 0
        self._accum = 0.0

    def reset(self):
        self._frame_index = 0
        self._accum = 0.0

    def update(self, dt):
        if len(self.frames) <= 1:
            return
        self._accum += float(dt or 0)
        while self._accum >= self.frame_interval_sec:
            self._accum -= self.frame_interval_sec
            self._frame_index = (self._frame_index + 1) % len(self.frames)

    def current_surface(self):
        if not self.frames:
            return load_sprite("node_ice_shelf")
        return self.frames[self._frame_index % len(self.frames)]


def parse_timed_phases(raw_list):
    phases = []
    for row in raw_list or []:
        if not isinstance(row, dict):
            continue
        phases.append(
            {
                "folder": str(row.get("folder", "")).strip(),
                "sprite_keys": list(row.get("spriteKeys") or row.get("sprite_keys") or []),
                "duration_sec": _float_val(row, "durationSec", "duration_sec", default=1.0),
                "frame_interval_sec": _float_val(
                    row,
                    "frameIntervalSec",
                    "frame_interval_sec",
                    default=_DEFAULT_FRAME_INTERVAL,
                ),
            }
        )
    return phases


def parse_visual_layers(raw_list, max_ice=None):
    layers = []
    for row in raw_list or []:
        if not isinstance(row, dict):
            continue
        layers.append(
            {
                "folder": str(row.get("folder", "")).strip(),
                "sprite_keys": list(row.get("spriteKeys") or row.get("sprite_keys") or []),
                "ice_capacity": int(row.get("iceCapacity", row.get("ice_capacity", 0)) or 0),
                "frame_interval_sec": _float_val(
                    row,
                    "frameIntervalSec",
                    "frame_interval_sec",
                    default=_DEFAULT_FRAME_INTERVAL,
                ),
            }
        )
    if max_ice is not None and layers:
        total_cap = sum(max(0, layer["ice_capacity"]) for layer in layers)
        if total_cap <= 0:
            per = max(1, int(max_ice) // len(layers))
            for layer in layers:
                layer["ice_capacity"] = per
    return layers


class TimedPhaseVisual:
    """Play folder phases back-to-back on a timer (build site visuals)."""

    def __init__(self, phases_config, fallback_size=(32, 32)):
        self.phases = parse_timed_phases(phases_config)
        self.fallback_size = fallback_size
        self.phase_index = 0
        self.phase_elapsed = 0.0
        self._cycler = FrameCycler([], _DEFAULT_FRAME_INTERVAL)
        self._started = False
        if self.phases:
            self._load_phase(0)

    def total_duration_sec(self):
        return sum(max(0.0, p["duration_sec"]) for p in self.phases)

    def reset(self):
        self.phase_index = 0
        self.phase_elapsed = 0.0
        self._started = False
        if self.phases:
            self._load_phase(0)
        else:
            self._cycler = FrameCycler([], _DEFAULT_FRAME_INTERVAL)

    def start(self):
        self._started = True

    def is_complete(self):
        return self._started and self.phase_index >= len(self.phases)

    def _load_phase(self, index):
        if index < 0 or index >= len(self.phases):
            self._cycler = FrameCycler([], _DEFAULT_FRAME_INTERVAL)
            return
        phase = self.phases[index]
        frames = load_folder_frames(
            phase["folder"],
            phase.get("sprite_keys"),
            fallback_size=self.fallback_size,
        )
        self._cycler = FrameCycler(frames, phase["frame_interval_sec"])

    def update(self, dt):
        if not self._started or not self.phases:
            return False
        dt = float(dt or 0)
        self._cycler.update(dt)
        if self.phase_index >= len(self.phases):
            return False
        self.phase_elapsed += dt
        changed = False
        while (
            self.phase_index < len(self.phases)
            and self.phase_elapsed >= self.phases[self.phase_index]["duration_sec"]
        ):
            self.phase_elapsed -= self.phases[self.phase_index]["duration_sec"]
            self.phase_index += 1
            if self.phase_index < len(self.phases):
                self._load_phase(self.phase_index)
            changed = True
        return changed

    def apply_to_sprite(self, sprite):
        center = sprite.rect.center
        surf = self._cycler.current_surface()
        sprite.image = surf
        sprite.rect = surf.get_rect(center=center)


class LayeredAmountVisual:
    """Folder per ice layer; advance when cumulative drain crosses layer boundaries."""

    def __init__(self, layers_config, max_ice=100, fallback_size=(32, 32)):
        self.fallback_size = fallback_size
        self.max_ice = max(0, int(max_ice or 0))
        self.layers = parse_visual_layers(layers_config, max_ice=self.max_ice)
        if self.max_ice <= 0 and self.layers:
            self.max_ice = sum(max(0, layer["ice_capacity"]) for layer in self.layers)
        self.ice_remaining = self.max_ice
        self.layer_index = 0
        self._cycler = FrameCycler([], _DEFAULT_FRAME_INTERVAL)
        self._load_layer(0)

    def _cumulative_capacities(self):
        total = 0
        caps = []
        for layer in self.layers:
            total += max(0, layer["ice_capacity"])
            caps.append(total)
        return caps

    def _layer_index_for_consumed(self, consumed):
        caps = self._cumulative_capacities()
        for i, cap in enumerate(caps):
            if consumed < cap:
                return i
        return len(self.layers)

    def reset(self):
        self.ice_remaining = self.max_ice
        self.layer_index = 0
        self._load_layer(0)

    def is_depleted(self):
        return self.ice_remaining <= 0 or self.layer_index >= len(self.layers)

    def drain(self, amount):
        if self.is_depleted() or amount <= 0:
            return False
        before_layer = self.layer_index
        self.ice_remaining = max(0, self.ice_remaining - int(amount))
        consumed = self.max_ice - self.ice_remaining
        new_layer = self._layer_index_for_consumed(consumed)
        if new_layer != self.layer_index:
            self.layer_index = new_layer
            self._load_layer(self.layer_index)
        if self.ice_remaining <= 0:
            self.layer_index = len(self.layers)
        return new_layer != before_layer or self.ice_remaining <= 0

    def _load_layer(self, index):
        if index < 0 or index >= len(self.layers):
            self._cycler = FrameCycler([], _DEFAULT_FRAME_INTERVAL)
            return
        layer = self.layers[index]
        frames = load_folder_frames(
            layer["folder"],
            layer.get("sprite_keys"),
            fallback_size=self.fallback_size,
        )
        self._cycler = FrameCycler(frames, layer["frame_interval_sec"])
        self._cycler.reset()

    def update(self, dt):
        self._cycler.update(dt)

    def apply_to_sprite(self, sprite):
        center = sprite.rect.center
        surf = self._cycler.current_surface()
        sprite.image = surf
        sprite.rect = surf.get_rect(center=center)
