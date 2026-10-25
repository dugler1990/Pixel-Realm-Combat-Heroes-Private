"""One ground-targeted meteor: targeting → descent → impact → residual DoT."""
from __future__ import annotations

import math
import random

import pygame

from Interaction import InteractionContext

_SCALE_CACHE: dict[tuple[int, int, int], list[pygame.Surface]] = {}
_PERSPECTIVE_CACHE: dict[tuple[int, int], pygame.Surface] = {}
_NORM_CACHE: dict[tuple[int, int, int], pygame.Surface] = {}
_ATMO_CACHE: dict[tuple[int, int, int], pygame.Surface] = {}
_IDENTITY_CACHE: dict[tuple[int, int, int], pygame.Surface] = {}


def _normalized_on_canvas(base: pygame.Surface, rw: int, rh: int) -> pygame.Surface:
    """Park a frame on a fixed canvas so anim frames share one footprint."""
    if base.get_width() == rw and base.get_height() == rh:
        return base
    key = (id(base), rw, rh)
    cached = _NORM_CACHE.get(key)
    if cached is not None:
        return cached
    canvas = pygame.Surface((rw, rh), pygame.SRCALPHA)
    canvas.blit(base, base.get_rect(midbottom=(rw // 2, rh)))
    _NORM_CACHE[key] = canvas
    return canvas

# Fixed isometric approach: trail points down-right, so flight starts up-left.
_FLIGHT_BASE_PX = 320.0
_FLIGHT_MIN_PX = 280.0
_FLIGHT_MAX_PX = 780.0
_FLIGHT_VIEW_MARGIN = 48.0
# Travel clock — same for every meteor size. Duration scales only with path length
# so average world-speed stays similar (longer on-screen entries take a bit longer).
_FLIGHT_MS_PER_FRAME = 70
_APPROACH = (-1.0 / math.sqrt(2.0), -1.0 / math.sqrt(2.0))
# Descent draw scale at t=0 (grows to 1.0 at impact). Doubled grow vs old 0.6→1.
_PERSPECTIVE_START = 0.4
# While u is below this, draw above Y-sorted bodies (sky). Then join normal depth.
_AERIAL_DRAW_UNTIL_U = 0.90
# Atmospheric perspective: cool/dim/soft far → full near (driven by same eased u).
_ATMO_FAR_RGB = (110, 145, 210)  # stronger cool haze when high
_ATMO_FAR_ALPHA = 110  # much softer when high
_ATMO_NEAR_ALPHA = 255
# Per-strike pairing tint (pad + rock share a hue). Strength high for readability test.
_IDENTITY_COLORS = (
    (255, 70, 220),   # magenta
    (60, 230, 255),   # cyan
    (255, 210, 40),   # gold
    (110, 255, 80),   # lime
    (255, 130, 50),   # orange
)
_IDENTITY_STRENGTH = 0.1  # 0..1 multiply toward identity; cranked for A/B test
# Targeting mark reads larger than the rock so the danger zone is obvious.
_TARGETING_SCALE_BOOST = 1.5
# Knockback resist: missing strength uses this; each point shaves a little shove.
_DEFAULT_KNOCKBACK_STRENGTH = 5.0
_STRENGTH_RESIST_PER_POINT = 0.015
_MIN_KNOCKBACK_FACTOR = 0.55


def _scale_frames(frames, scale: float) -> list[pygame.Surface]:
    if abs(scale - 1.0) < 0.02:
        return list(frames)
    # Bucket to 0.05 so random scales reuse surfaces.
    bucket = max(0.4, min(3.0, round(scale * 20) / 20.0))
    key = (id(frames[0]) if frames else 0, len(frames), int(bucket * 100))
    cached = _SCALE_CACHE.get(key)
    if cached is not None:
        return cached
    out = []
    for frame in frames:
        w = max(1, int(frame.get_width() * bucket))
        h = max(1, int(frame.get_height() * bucket))
        out.append(pygame.transform.smoothscale(frame, (w, h)))
    _SCALE_CACHE[key] = out
    return out


def _leading_hotspot_frac(surface: pygame.Surface) -> tuple[float, float]:
    """Fraction (x,y) of the leading opaque mass — meteor head / seal core."""
    try:
        raw = pygame.image.tostring(surface, "RGBA")
    except Exception:
        return 0.5, 0.5
    w, h = surface.get_size()
    if w < 1 or h < 1:
        return 0.5, 0.5
    import array

    buf = array.array("B", raw)
    xs = []
    ys = []
    # Sample every other pixel for speed on large canvases.
    step = 2 if w * h > 20000 else 1
    for y in range(0, h, step):
        row = y * w * 4
        for x in range(0, w, step):
            a = buf[row + x * 4 + 3]
            if a > 40:
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0.5, 0.5
    # Leading tip bias for diagonal meteors (down-right).
    u = [x + y for x, y in zip(xs, ys)]
    thr = sorted(u)[int(0.70 * (len(u) - 1))]
    lx = [x for x, y, uu in zip(xs, ys, u) if uu >= thr]
    ly = [y for x, y, uu in zip(xs, ys, u) if uu >= thr]
    if not lx:
        lx, ly = xs, ys
    return (sum(lx) / len(lx)) / w, (sum(ly) / len(ly)) / h


def _opaque_centroid_frac(surface: pygame.Surface) -> tuple[float, float]:
    try:
        raw = pygame.image.tostring(surface, "RGBA")
    except Exception:
        return 0.5, 0.5
    w, h = surface.get_size()
    if w < 1 or h < 1:
        return 0.5, 0.5
    import array

    buf = array.array("B", raw)
    sx = sy = n = 0
    step = 2 if w * h > 20000 else 1
    for y in range(0, h, step):
        row = y * w * 4
        for x in range(0, w, step):
            if buf[row + x * 4 + 3] > 40:
                sx += x
                sy += y
                n += 1
    if n <= 0:
        return 0.5, 0.5
    return (sx / n) / w, (sy / n) / h


def _perspective_surface(base: pygame.Surface, factor: float) -> pygame.Surface:
    """Scale a full-size descent frame by perspective factor (cached buckets)."""
    if factor >= 0.98:
        return base
    bucket = max(0.25, min(1.0, round(factor * 50) / 50.0))
    if bucket >= 0.98:
        return base
    key = (id(base), int(bucket * 100))
    cached = _PERSPECTIVE_CACHE.get(key)
    if cached is not None:
        return cached
    w = max(1, int(base.get_width() * bucket))
    h = max(1, int(base.get_height() * bucket))
    out = pygame.transform.smoothscale(base, (w, h))
    _PERSPECTIVE_CACHE[key] = out
    return out


def _atmosphere_surface(base: pygame.Surface, u: float) -> pygame.Surface:
    """Continuous far→near haze: cooler/dimmer/softer when high, full color near ground."""
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else float(u))
    bucket = round(u * 20) / 20.0
    if bucket >= 0.98:
        return base
    key = (id(base), int(bucket * 100))
    cached = _ATMO_CACHE.get(key)
    if cached is not None:
        return cached

    # Lerp multiply veil from cool haze → white, and lift alpha.
    fr, fg, fb = _ATMO_FAR_RGB
    r = int(fr + (255 - fr) * bucket)
    g = int(fg + (255 - fg) * bucket)
    b = int(fb + (255 - fb) * bucket)
    a = int(_ATMO_FAR_ALPHA + (_ATMO_NEAR_ALPHA - _ATMO_FAR_ALPHA) * bucket)

    out = base.copy()
    veil = pygame.Surface(out.get_size(), pygame.SRCALPHA)
    veil.fill((r, g, b, a))
    out.blit(veil, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    _ATMO_CACHE[key] = out
    return out


def _identity_tint(base: pygame.Surface, rgb: tuple[int, int, int], strength: float) -> pygame.Surface:
    """Multiply-tint toward an identity color so pad and rock share a readable hue."""
    strength = 0.0 if strength < 0.0 else (1.0 if strength > 1.0 else float(strength))
    if strength < 0.02:
        return base
    key = (id(base), (rgb[0] << 16) | (rgb[1] << 8) | rgb[2], int(round(strength * 100)))
    cached = _IDENTITY_CACHE.get(key)
    if cached is not None:
        return cached
    r = int(255 + (int(rgb[0]) - 255) * strength)
    g = int(255 + (int(rgb[1]) - 255) * strength)
    b = int(255 + (int(rgb[2]) - 255) * strength)
    out = base.copy()
    veil = pygame.Surface(out.get_size(), pygame.SRCALPHA)
    veil.fill((r, g, b, 255))
    out.blit(veil, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    _IDENTITY_CACHE[key] = out
    return out


class MeteorTargetMarker(pygame.sprite.Sprite):
    """Ground warning mark — loops until the meteor impacts."""

    def __init__(
        self,
        frames,
        ground_pos,
        groups,
        frame_duration_ms: int,
        identity_rgb: tuple[int, int, int] | None = None,
        identity_strength: float = _IDENTITY_STRENGTH,
    ):
        super().__init__(groups)
        self.frames = list(frames) if frames else [pygame.Surface((1, 1), pygame.SRCALPHA)]
        self.ground_pos = (float(ground_pos[0]), float(ground_pos[1]))
        self.frame_duration_ms = max(1, int(frame_duration_ms))
        self.frame_index = 0
        self.last_frame_ms = pygame.time.get_ticks()
        self.sprite_type = "effect"
        self._identity_rgb = identity_rgb
        self._identity_strength = float(identity_strength)
        # Seal center (not midbottom) so the crater matches ground_pos.
        fx, fy = _opaque_centroid_frac(self.frames[0])
        self._hot_fx, self._hot_fy = fx, fy
        self._set_frame(0)

    def _set_frame(self, index: int):
        base = self.frames[index]
        if self._identity_rgb is not None:
            self.image = _identity_tint(base, self._identity_rgb, self._identity_strength)
        else:
            self.image = base
        self._plant()

    def _plant(self):
        hx = int(self.image.get_width() * self._hot_fx)
        hy = int(self.image.get_height() * self._hot_fy)
        self.rect = self.image.get_rect(
            topleft=(int(self.ground_pos[0] - hx), int(self.ground_pos[1] - hy))
        )

    def update(self, dt=None):
        if len(self.frames) <= 1:
            return
        now = pygame.time.get_ticks()
        if now - self.last_frame_ms < self.frame_duration_ms:
            return
        self.last_frame_ms = now
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self._set_frame(self.frame_index)


class MeteorStrike(pygame.sprite.Sprite):
    """Phased meteor VFX + burst/DoT damage at a ground point."""

    PHASES = ("targeting", "descent", "impact", "residual", "linger")

    def __init__(
        self,
        pos,
        groups,
        *,
        frames_by_phase: dict,
        level,
        owner=None,
        source_team=None,
        scale: float = 1.0,
        burst_damage: int = 75,
        dot_damage: int = 8,
        dot_interval_ms: int = 500,
        linger_ms: int = 3000,
        impact_radius: float = 90,
        frame_duration_ms: int = 70,
        knockback: float = 252.0,
        knockback_follow_through: float = 0.55,
        shake_scale_threshold: float | None = None,
        base_frame_duration_ms: int | None = None,
    ):
        super().__init__(groups)
        self.level = level
        self.owner = owner
        self.source_team = source_team or getattr(owner, "team_id", "enemy")
        self.ground_pos = (float(pos[0]), float(pos[1]))
        self.scale = float(scale)
        # Size weight at 1.0 = config baseline; bigger → more damage/knockback, slower.
        size_w = max(0.45, self.scale)
        self.burst_damage = int(round(burst_damage * size_w))
        self.dot_damage = max(1, int(round(dot_damage * (0.65 + 0.35 * size_w))))
        self.dot_interval_ms = int(dot_interval_ms)
        self.linger_ms = int(linger_ms)
        self.impact_radius = float(impact_radius) * self.scale
        base_fd = int(base_frame_duration_ms if base_frame_duration_ms is not None else frame_duration_ms)
        # Visual frame tick + flight clock: size-independent for even travel tests.
        self.frame_duration_ms = max(35, int(base_fd))
        self._flight_frame_duration_ms = max(35, int(_FLIGHT_MS_PER_FRAME))
        self.knockback = float(knockback) * size_w
        self.impulse_follow_through = float(knockback_follow_through)
        self.shake_scale_threshold = shake_scale_threshold
        self._identity_rgb = random.choice(_IDENTITY_COLORS)
        self._identity_strength = _IDENTITY_STRENGTH

        targeting_scale = self.scale * _TARGETING_SCALE_BOOST
        self._frames = {
            "targeting": _scale_frames(frames_by_phase.get("targeting") or [], targeting_scale),
            "descent": _scale_frames(frames_by_phase.get("descent") or [], self.scale),
            "impact": _scale_frames(frames_by_phase.get("impact") or [], self.scale),
            "residual": _scale_frames(frames_by_phase.get("residual") or [], self.scale),
            "linger": _scale_frames(frames_by_phase.get("residual_v") or [], self.scale),
        }
        # If linger variants missing, reuse residual.
        if not self._frames["linger"]:
            self._frames["linger"] = list(self._frames["residual"])

        self.sprite_type = "magic"
        self.phase = "targeting"
        self.frame_index = 0
        self.last_frame_ms = pygame.time.get_ticks()
        self.linger_started_ms = None
        self.last_dot_ms = 0
        self._burst_done = False
        self._last_smoke_drip_ms = 0
        self._marker = None

        # Descent flight state (filled when descent phase begins).
        self._flight_active = False
        self._flight_start = self.ground_pos
        self._flight_end = self.ground_pos
        self._flight_start_ms = 0
        self._flight_duration_ms = 1
        self._flight_pos = self.ground_pos
        self._flight_travel_u = 0.0
        desc = self._frames.get("descent") or []
        self._descent_ref_w = max((f.get_width() for f in desc), default=1)
        self._descent_ref_h = max((f.get_height() for f in desc), default=1)
        # Ball hotspot inside descent art (stable after normalize); impact uses centroid.
        if desc:
            self._ball_fx, self._ball_fy = _leading_hotspot_frac(desc[0])
        else:
            self._ball_fx, self._ball_fy = 0.5, 0.5
        impact = self._frames.get("impact") or []
        if impact:
            self._impact_fx, self._impact_fy = _opaque_centroid_frac(impact[0])
        else:
            self._impact_fx, self._impact_fy = 0.5, 0.5
        targeting = self._frames.get("targeting") or []
        if targeting:
            self._mark_fx, self._mark_fy = _opaque_centroid_frac(targeting[0])
        else:
            self._mark_fx, self._mark_fy = 0.5, 0.5

        self.image = self._tinted_phase_frame(self._current_frames()[0])
        self._plant()
        if self.phase == "descent" and not self._flight_active:
            self._begin_descent_flight(pygame.time.get_ticks())
            self._plant()

    def _current_frames(self):
        frames = self._frames.get(self.phase) or []
        if frames:
            return frames
        # Skip empty phases.
        for name in self.PHASES:
            if self._frames.get(name):
                self.phase = name
                return self._frames[name]
        return [pygame.Surface((1, 1), pygame.SRCALPHA)]

    def _camera_view_rect(self):
        """World-space view rect expanded by a margin; None if camera unknown."""
        layout = getattr(self.level, "layout_manager", None)
        cam = getattr(layout, "visible_sprites", None) if layout is not None else None
        if cam is None:
            return None
        offset = getattr(cam, "offset", None)
        if offset is None:
            return None
        w = int(getattr(cam, "window_width", 0) or 0)
        h = int(getattr(cam, "window_height", 0) or 0)
        if w < 1 or h < 1:
            backend = getattr(self.level, "backend", None)
            if backend is not None:
                try:
                    w, h = backend.get_size()
                except Exception:
                    return None
        if w < 1 or h < 1:
            return None
        m = _FLIGHT_VIEW_MARGIN
        return pygame.Rect(
            float(offset.x) - m,
            float(offset.y) - m,
            float(w) + 2 * m,
            float(h) + 2 * m,
        )

    def _compute_flight_start(self):
        """Same approach for every size; start just off-screen when possible."""
        gx, gy = self.ground_pos
        ax, ay = _APPROACH

        def at_dist(d: float):
            return (gx + ax * d, gy + ay * d)

        view = self._camera_view_rect()
        if view is None:
            return at_dist(_FLIGHT_BASE_PX)

        def outside(d: float) -> bool:
            x, y = at_dist(d)
            return not view.collidepoint(x, y)

        if outside(_FLIGHT_MIN_PX):
            return at_dist(_FLIGHT_MIN_PX)
        if not outside(_FLIGHT_MAX_PX):
            return at_dist(_FLIGHT_MAX_PX)

        lo, hi = _FLIGHT_MIN_PX, _FLIGHT_MAX_PX
        for _ in range(18):
            mid = 0.5 * (lo + hi)
            if outside(mid):
                hi = mid
            else:
                lo = mid
        return at_dist(hi)

    def _tinted_phase_frame(self, frame: pygame.Surface) -> pygame.Surface:
        return _identity_tint(frame, self._identity_rgb, self._identity_strength)

    @property
    def draws_above_y_sort(self) -> bool:
        """Sky layer until late approach, then settle into ground Y-sort."""
        return (
            self.phase == "descent"
            and self._flight_active
            and self._flight_travel_u < _AERIAL_DRAW_UNTIL_U
        )

    def _plant(self, pos=None):
        """Anchor the meaningful hotspot (ball / seal / blast) on world pos."""
        if pos is None:
            if self.phase == "descent":
                pos = self._flight_pos
            else:
                pos = self.ground_pos
        if self.phase == "descent":
            fx, fy = self._ball_fx, self._ball_fy
        elif self.phase == "targeting":
            fx, fy = self._mark_fx, self._mark_fy
        elif self.phase in ("impact", "residual", "linger"):
            fx, fy = self._impact_fx, self._impact_fy
        else:
            fx, fy = 0.5, 0.5
        hx = int(self.image.get_width() * fx)
        hy = int(self.image.get_height() * fy)
        self.rect = self.image.get_rect(
            topleft=(int(pos[0] - hx), int(pos[1] - hy))
        )

    def _apply_descent_visual(self):
        """Perspective scale + atmospheric tint from the same eased travel u."""
        frames = self._frames.get("descent") or []
        if not frames:
            return
        idx = min(int(self.frame_index), len(frames) - 1)
        base = _normalized_on_canvas(frames[idx], self._descent_ref_w, self._descent_ref_h)
        u = self._flight_travel_u
        factor = _PERSPECTIVE_START + (1.0 - _PERSPECTIVE_START) * u
        scaled = _perspective_surface(base, factor)
        shaded = _atmosphere_surface(scaled, u)
        self.image = _identity_tint(shaded, self._identity_rgb, self._identity_strength)

    def _begin_descent_flight(self, now: int):
        self._flight_start = self._compute_flight_start()
        self._flight_end = self.ground_pos
        self._flight_start_ms = now
        frames = self._frames.get("descent") or []
        # Same travel clock for every size. path_mul keeps average speed similar across path lengths.
        base_dur = max(1, len(frames) * self._flight_frame_duration_ms)
        path_len = math.hypot(
            self._flight_end[0] - self._flight_start[0],
            self._flight_end[1] - self._flight_start[1],
        )
        path_mul = max(1.0, path_len / _FLIGHT_BASE_PX)
        self._flight_duration_ms = max(1, int(base_dur * path_mul))
        self._flight_pos = self._flight_start
        self._flight_travel_u = 0.0
        self._flight_active = True
        self._apply_descent_visual()

    def _update_flight_pos(self, now: int) -> float:
        """Advance descent; ease-in travel so speed rises near the ground. Returns t in [0,1]."""
        t = (now - self._flight_start_ms) / float(self._flight_duration_ms)
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        # Quadratic ease-in: most distance covered in the final stretch.
        u = t * t
        self._flight_travel_u = u
        sx, sy = self._flight_start
        ex, ey = self._flight_end
        self._flight_pos = (sx + (ex - sx) * u, sy + (ey - sy) * u)
        return t

    def _advance_phase(self):
        idx = self.PHASES.index(self.phase)
        while idx + 1 < len(self.PHASES):
            idx += 1
            nxt = self.PHASES[idx]
            if self._frames.get(nxt):
                self.phase = nxt
                self.frame_index = 0
                now = pygame.time.get_ticks()
                if nxt == "descent":
                    self._ensure_ground_marker()
                    self._begin_descent_flight(now)
                    self._plant()
                    return
                if nxt == "impact" and not self._burst_done:
                    self._clear_ground_marker()
                    self._apply_burst()
                    self._burst_done = True
                    fluid = getattr(self.level, "fluid_smoke", None)
                    if fluid is not None:
                        # Softer impact bloom — builds instead of popping solid.
                        fluid.queue_splat(
                            self.ground_pos,
                            amount=0.45 + 0.2 * min(2.0, self.scale),
                            radius_px=32.0 + 18.0 * self.scale,
                            rise=0.55,
                        )
                        fluid.queue_splat(
                            self.ground_pos,
                            amount=0.22 + 0.1 * min(2.0, self.scale),
                            radius_px=50.0 + 22.0 * self.scale,
                            rise=0.35,
                        )
                if nxt == "linger":
                    self.linger_started_ms = now
                    self.last_dot_ms = self.linger_started_ms
                self.image = self._tinted_phase_frame(self._current_frames()[0])
                self._plant()
                return
        self.kill()

    def _ensure_ground_marker(self):
        """Keep purple warning mark on the crater through the whole descent."""
        if self._marker is not None:
            return
        frames = self._frames.get("targeting") or []
        if not frames:
            return
        # Use base frame timing so the mark keeps pulsing while big rocks fall slowly.
        base_fd = max(35, int(round(70 * max(0.45, min(1.0, self.scale)))))
        self._marker = MeteorTargetMarker(
            frames,
            self.ground_pos,
            list(self.groups()),
            frame_duration_ms=base_fd,
            identity_rgb=self._identity_rgb,
            identity_strength=self._identity_strength,
        )

    def _clear_ground_marker(self):
        if self._marker is not None:
            self._marker.kill()
            self._marker = None

    def kill(self):
        self._clear_ground_marker()
        super().kill()

    def _target_center(self, sprite):
        hitbox = getattr(sprite, "hitbox", None)
        if hitbox is not None:
            return hitbox.center
        rect = getattr(sprite, "rect", None)
        if rect is not None:
            return rect.center
        return None

    def _hosts_in_radius(self):
        attackable = getattr(self.level, "attackable_sprites", None)
        if attackable is None:
            return []
        cx, cy = self.ground_pos
        r2 = self.impact_radius * self.impact_radius
        hits = []
        for sprite in attackable.sprites():
            if sprite is self.owner:
                continue
            center = self._target_center(sprite)
            if center is None:
                continue
            dx = center[0] - cx
            dy = center[1] - cy
            if dx * dx + dy * dy <= r2:
                hits.append(sprite)
        return hits

    def _apply_damage(self, amount: int, *, phase: str):
        resolver = getattr(self.level, "interaction_resolver", None)
        if resolver is None or amount <= 0:
            return
        for target in self._hosts_in_radius():
            target_team = getattr(target, "team_id", None)
            if not resolver.can_potentially_affect(
                source_team=self.source_team,
                target_team=target_team,
                kind="damage",
            ):
                continue
            ctx = InteractionContext(
                kind="damage",
                source_kind="enemy_special",
                source=self,
                owner=self.owner,
                source_team=self.source_team,
                target=target,
                amount=amount,
                attack_type="magic",
                phase=phase,
                tags={"meteor", phase},
            )
            resolver.apply(ctx)

    def _target_knockback_factor(self, target) -> float:
        """Stronger targets shrug off a bit of explosion shove."""
        strength = _DEFAULT_KNOCKBACK_STRENGTH
        stats = getattr(target, "stats", None)
        if isinstance(stats, dict) and stats.get("strength") is not None:
            try:
                strength = float(stats["strength"])
            except (TypeError, ValueError):
                pass
        else:
            raw = getattr(target, "strength", None)
            if raw is not None:
                try:
                    strength = float(raw)
                except (TypeError, ValueError):
                    pass
        return max(_MIN_KNOCKBACK_FACTOR, 1.0 - _STRENGTH_RESIST_PER_POINT * strength)

    def _apply_explosion_knockback(self):
        """Radial impulse from impact center — same pattern as leap slam."""
        if self.knockback <= 0:
            return
        resolver = getattr(self.level, "interaction_resolver", None)
        if resolver is None:
            return
        cx, cy = self.ground_pos
        radius = max(1.0, self.impact_radius)
        for target in self._hosts_in_radius():
            center = self._target_center(target)
            if center is None:
                continue
            dx = center[0] - cx
            dy = center[1] - cy
            dist = math.hypot(dx, dy)
            if dist > radius:
                continue
            if dist < 1e-3:
                nx, ny = 1.0, 0.0
            else:
                nx, ny = dx / dist, dy / dist
            # Stronger near the crater; still shoves at the rim.
            falloff = max(0.35, 1.0 - dist / radius)
            mag = self.knockback * falloff * self._target_knockback_factor(target)
            resolver.apply(
                InteractionContext(
                    kind="impulse",
                    source_kind="enemy_special",
                    source=self,
                    owner=self.owner,
                    source_team=self.source_team,
                    target=target,
                    impulse_x=nx * mag,
                    impulse_y=ny * mag,
                    phase="impact",
                    tags={"meteor", "impact", "explosion"},
                )
            )

    def _apply_burst(self):
        self._apply_damage(self.burst_damage, phase="impact")
        self._apply_explosion_knockback()
        self._maybe_screen_shake()

    def _maybe_screen_shake(self):
        """Shake on impacts larger than mean+1σ of the shower size distribution."""
        threshold = self.shake_scale_threshold
        if threshold is None or self.scale < threshold:
            return
        cam = getattr(getattr(self.level, "layout_manager", None), "visible_sprites", None)
        add = getattr(cam, "add_screen_shake", None)
        if not callable(add):
            return
        # Noticeable kick; scales up for the biggest rocks in range.
        excess = self.scale - float(threshold)
        amp = 16.0 + 18.0 * min(1.0, excess / 0.35)
        dur = int(380 + 220 * min(1.0, self.scale / 1.6))
        add(amplitude=amp, duration_ms=dur)

    def _tick_dot(self, now: int):
        if self.phase not in ("residual", "linger"):
            return
        if now - self.last_dot_ms < self.dot_interval_ms:
            return
        self.last_dot_ms = now
        self._apply_damage(self.dot_damage, phase="residual")

    def update(self, dt=None):
        now = pygame.time.get_ticks()
        frames = self._current_frames()

        if self.phase == "descent":
            t = self._update_flight_pos(now)
            if t >= 1.0:
                self._advance_phase()
                return

        if now - self.last_frame_ms >= self.frame_duration_ms:
            self.last_frame_ms = now
            self.frame_index += 1
            if self.frame_index >= len(frames):
                if self.phase == "descent":
                    # Loop for flight life; footprint is normalized so size doesn't cycle.
                    self.frame_index = 0
                    self._apply_descent_visual()
                    self._plant()
                elif self.phase == "linger":
                    self.frame_index = 0
                    self.image = self._tinted_phase_frame(frames[0])
                    self._plant()
                else:
                    self._advance_phase()
                    return
            else:
                if self.phase == "descent":
                    self._apply_descent_visual()
                else:
                    self.image = self._tinted_phase_frame(frames[self.frame_index])
                self._plant()
        elif self.phase == "descent":
            # Keep sliding / growing between frame ticks.
            self._apply_descent_visual()
            self._plant()

        if self.phase == "impact" and not self._burst_done:
            self._clear_ground_marker()
            self._apply_burst()
            self._burst_done = True

        if self.phase in ("residual", "linger"):
            self._tick_dot(now)
            fluid = getattr(self.level, "fluid_smoke", None)
            if fluid is not None and now - self._last_smoke_drip_ms >= 170:
                self._last_smoke_drip_ms = now
                # Ember wisps — between soft-whisper and impact-strength.
                fluid.queue_splat(
                    (
                        self.ground_pos[0] + random.uniform(-14, 14) * self.scale,
                        self.ground_pos[1] + random.uniform(-10, 10) * self.scale,
                    ),
                    amount=0.09 + 0.04 * self.scale,
                    radius_px=14.0 + 8.0 * self.scale,
                    rise=0.38,
                )

        if self.phase == "linger" and self.linger_started_ms is not None:
            if now - self.linger_started_ms >= self.linger_ms:
                self.kill()
