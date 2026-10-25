"""Wind-driven smoke puffs for meteor impacts (fixed emitter, capped pool)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pygame


_MAX_PUFFS = 384
_MAX_EMITTERS = 64
# Instance layout matches grass: center(2) halfsize(2) angle(1) uvrect(4) tint(4)
_INST_FLOATS = 13


@dataclass
class _Emitter:
    x: float
    y: float
    scale: float
    end_ms: int
    next_spawn_ms: int
    spawn_interval_ms: int


class SmokeSystem:
    """Fixed-position emitters that spawn short-lived wind-advected smoke puffs."""

    def __init__(self, frames: list[pygame.Surface] | None = None):
        self.frames = list(frames or [])
        self.n_frames = max(1, len(self.frames))
        self._emitters: list[_Emitter] = []
        # Parallel arrays for active puffs (SoA-ish for cheap update / draw pack).
        self._n = 0
        self._x = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._y = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._vx = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._vy = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._life = np.zeros(_MAX_PUFFS, dtype=np.float32)  # seconds remaining
        self._life0 = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._frame = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._scale = np.zeros(_MAX_PUFFS, dtype=np.float32)
        self._frame_timer = np.zeros(_MAX_PUFFS, dtype=np.float32)

        self._frame_halves: list[tuple[float, float]] = []
        self._refresh_frame_halves()

        # Scratch for GPU upload (sorted by y).
        self._draw_buf = np.zeros((_MAX_PUFFS, _INST_FLOATS), dtype=np.float32)
        self._atlas_uvs: np.ndarray | None = None  # filled by backend after atlas build
        self._atlas_halves: np.ndarray | None = None

    def _refresh_frame_halves(self) -> None:
        self._frame_halves = []
        for fr in self.frames:
            w, h = fr.get_size()
            self._frame_halves.append((w * 0.5, h * 0.5))
        if not self._frame_halves:
            self._frame_halves = [(32.0, 48.0)]

    def set_frames(self, frames: list[pygame.Surface]) -> None:
        self.frames = list(frames or [])
        self.n_frames = max(1, len(self.frames))
        self._refresh_frame_halves()

    def set_atlas_meta(self, uvs: np.ndarray, halves: np.ndarray) -> None:
        self._atlas_uvs = np.asarray(uvs, dtype=np.float32)
        self._atlas_halves = np.asarray(halves, dtype=np.float32)

    def emit(
        self,
        pos,
        *,
        scale: float = 1.0,
        duration_ms: int = 2800,
        spawn_interval_ms: int = 110,
    ) -> None:
        now = pygame.time.get_ticks()
        if len(self._emitters) >= _MAX_EMITTERS:
            self._emitters.pop(0)
        self._emitters.append(
            _Emitter(
                x=float(pos[0]),
                y=float(pos[1]),
                scale=max(0.25, float(scale)),
                end_ms=now + int(duration_ms),
                next_spawn_ms=now,
                spawn_interval_ms=max(40, int(spawn_interval_ms)),
            )
        )

    def _spawn_puff(self, ex: float, ey: float, scale: float, wx: float, wy: float, wind_i: float) -> None:
        if self._n >= _MAX_PUFFS:
            # Drop oldest by shifting left one (cheap enough at cap).
            self._x[:-1] = self._x[1:]
            self._y[:-1] = self._y[1:]
            self._vx[:-1] = self._vx[1:]
            self._vy[:-1] = self._vy[1:]
            self._life[:-1] = self._life[1:]
            self._life0[:-1] = self._life0[1:]
            self._frame[:-1] = self._frame[1:]
            self._scale[:-1] = self._scale[1:]
            self._frame_timer[:-1] = self._frame_timer[1:]
            self._n = _MAX_PUFFS - 1

        i = self._n
        self._n += 1
        rise = 55.0 + 35.0 * scale
        wind_birth = 28.0
        self._x[i] = ex + (np.random.uniform(-6, 6) * scale)
        self._y[i] = ey + (np.random.uniform(-4, 4) * scale)
        self._vx[i] = wx * wind_birth + np.random.uniform(-8, 8)
        self._vy[i] = -rise + wy * wind_birth + np.random.uniform(-6, 6)
        life = max(0.55, 1.35 / (1.0 + 0.35 * max(0.0, wind_i)))
        self._life[i] = life
        self._life0[i] = life
        self._frame[i] = 0.0
        self._scale[i] = 0.35 + 0.45 * scale
        self._frame_timer[i] = 0.0

    def update(self, dt: float, weather) -> None:
        if dt is None or dt <= 0:
            dt = 1.0 / 30.0
        now = pygame.time.get_ticks()
        wx = wy = wind_i = 0.0
        if weather is not None:
            try:
                wx, wy = weather.calculate_wind_force()
            except Exception:
                wx = wy = 0.0
            wind_i = float(getattr(weather, "wind_intensity", 0.0) or 0.0)

        # Emitters
        alive_e = []
        for em in self._emitters:
            if now >= em.end_ms:
                continue
            while em.next_spawn_ms <= now:
                self._spawn_puff(em.x, em.y, em.scale, wx, wy, wind_i)
                em.next_spawn_ms += em.spawn_interval_ms
                if em.next_spawn_ms < now - em.spawn_interval_ms * 2:
                    em.next_spawn_ms = now + em.spawn_interval_ms
            alive_e.append(em)
        self._emitters = alive_e

        n = self._n
        if n == 0:
            return

        wind_accel = 22.0
        self._vx[:n] += wx * wind_accel * dt
        self._vy[:n] += wy * wind_accel * dt
        # Gentle continued rise.
        self._vy[:n] -= 12.0 * dt
        self._x[:n] += self._vx[:n] * dt
        self._y[:n] += self._vy[:n] * dt
        self._life[:n] -= dt
        self._frame_timer[:n] += dt

        frame_dt = 0.07
        adv_idx = np.nonzero(self._frame_timer[:n] >= frame_dt)[0]
        if len(adv_idx):
            self._frame[adv_idx] = np.minimum(self._frame[adv_idx] + 1.0, float(self.n_frames - 1))
            self._frame_timer[adv_idx] = 0.0

        # Compact dead puffs.
        alive = self._life[:n] > 0.02
        if not np.all(alive):
            idx = np.nonzero(alive)[0]
            m = len(idx)
            self._x[:m] = self._x[idx]
            self._y[:m] = self._y[idx]
            self._vx[:m] = self._vx[idx]
            self._vy[:m] = self._vy[idx]
            self._life[:m] = self._life[idx]
            self._life0[:m] = self._life0[idx]
            self._frame[:m] = self._frame[idx]
            self._scale[:m] = self._scale[idx]
            self._frame_timer[:m] = self._frame_timer[idx]
            self._n = m

    def pack_instances(self, camera_offset) -> tuple[np.ndarray, int]:
        """Return (instance_array Nx13, count) in camera space, y-sorted."""
        n = self._n
        if n == 0:
            return self._draw_buf[:0], 0

        ox = float(camera_offset[0])
        oy = float(camera_offset[1])
        order = np.argsort(self._y[:n])

        uvs = self._atlas_uvs
        halves = self._atlas_halves
        out = self._draw_buf[:n]
        for dst, src in enumerate(order):
            fid = int(self._frame[src]) % self.n_frames
            sc = float(self._scale[src])
            if halves is not None and fid < len(halves):
                hw, hh = float(halves[fid, 0]) * sc, float(halves[fid, 1]) * sc
            else:
                hw, hh = self._frame_halves[fid % len(self._frame_halves)]
                hw *= sc
                hh *= sc
            # Orient so authored "up" aligns with velocity (screen y-down).
            angle = math.atan2(float(self._vx[src]), -float(self._vy[src]))
            life_t = float(self._life[src] / max(1e-3, self._life0[src]))
            alpha = max(0.0, min(1.0, life_t * 1.15))
            if uvs is not None and fid < len(uvs):
                u0, v0, u1, v1 = uvs[fid]
            else:
                u0 = v0 = 0.0
                u1 = v1 = 1.0
            out[dst, 0] = self._x[src] - ox
            # Pivot near the plume base so the emitter stays on the fire when upright.
            out[dst, 1] = self._y[src] - oy - hh * 0.72
            out[dst, 2] = hw
            out[dst, 3] = hh
            out[dst, 4] = angle
            out[dst, 5] = u0
            out[dst, 6] = v0
            out[dst, 7] = u1
            out[dst, 8] = v1
            out[dst, 9] = 1.0
            out[dst, 10] = 1.0
            out[dst, 11] = 1.0
            out[dst, 12] = alpha
        return out, n
