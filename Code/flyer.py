"""A sprite flyer. Not an Entity. Right-facing frames live in
Graphics/Monsters/flyer/move/; left is that strip flipped.

He stays near his spawn, but the lap is not a smooth hover. The downstroke
(wings traveling downward in the clip) surges him along the circle and lifts
him. The upstroke coasts and drops him.

hurt is the damage animation: it plays when a hit lands, then he goes back
to the flap. crash and breath are his attacks: when the player is close he
uses one of them, then flaps again. The travel in those clips is already in
the frames, so the lap waits while one is playing.
"""
from __future__ import annotations

import json
import math
import os

import pygame

from Settings import FPS, VIEW_ELEVATION_DEG

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "Graphics", "Monsters", "flyer"))
_MOVE = os.path.join(_ROOT, "move")

# True height above the ground point. The draw shifts by this times cos(elevation),
# because a pixel of height is foreshortened on the map.
HOVER_PX = 180.0
# How far the downstroke lifts him, and the upstroke drops him, in true pixels.
FLAP_LIFT_PX = 70.0
ORBIT_RADIUS_PX = 160.0
ORBIT_Y_SCALE = 0.55
# Four wingbeats per lap. Most of each beat's travel happens on the downstroke.
BEATS_PER_LAP = 4.0
COAST_SHARE = 0.25
# How close the player has to be before he attacks, and how long he flaps
# between one attack and the next.
ATTACK_RANGE_PX = 560.0
ATTACK_GAP_TICKS = 90
_ATTACKS = ("crash", "breath")

_CACHE = None


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    names = [n for n in os.listdir(_MOVE) if n.lower().endswith(".png")]
    names.sort(key=lambda n: int(os.path.splitext(n)[0]))
    if not names:
        raise FileNotFoundError(f"no flyer frames in {_MOVE}")
    right = [pygame.image.load(os.path.join(_MOVE, n)).convert_alpha() for n in names]
    left = [pygame.transform.flip(frame, True, False) for frame in right]
    meta_path = os.path.join(_ROOT, "clip.json")
    frame_ms = 83.0
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            frame_ms = float(json.load(fh).get("frame_ms", frame_ms))
    # Same unit as a monster's animation_speed: frames advanced per game tick.
    wing_step = (1000.0 / frame_ms) / FPS
    # Higher value = wings lower in the picture. The clip bottoms near frame 5
    # and tops near frame 16, so this rises on the downstroke.
    cys = [float(pygame.mask.from_surface(frame).centroid()[1]) for frame in right]
    lo, hi = min(cys), max(cys)
    span = max(hi - lo, 1.0)
    wing_low = [(c - lo) / span for c in cys]
    actions = {}
    for name in ("hurt",) + _ATTACKS:
        spec = _load_strip(os.path.join(_ROOT, name))
        if spec is not None:
            actions[name] = spec
    _CACHE = (right, left, wing_step, wing_low, actions)
    return _CACHE


def _load_strip(folder):
    """One right-facing one-shot, or None if that folder has no frames yet."""
    if not os.path.isdir(folder):
        return None
    names = [n for n in os.listdir(folder) if n.lower().endswith(".png")]
    names.sort(key=lambda n: int(os.path.splitext(n)[0]))
    if not names:
        return None
    right = [pygame.image.load(os.path.join(folder, n)).convert_alpha() for n in names]
    left = [pygame.transform.flip(frame, True, False) for frame in right]
    frame_ms = 83.0
    anchor = [right[0].get_width() // 2, right[0].get_height() // 2]
    meta_path = os.path.join(folder, "clip.json")
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        frame_ms = float(meta.get("frame_ms", frame_ms))
        if meta.get("anchor"):
            anchor = [int(meta["anchor"][0]), int(meta["anchor"][1])]
    return {
        "right": right,
        "left": left,
        "step": (1000.0 / frame_ms) / FPS,
        "anchor": anchor,
    }


def _sample(curve, index):
    n = len(curve)
    i = int(index) % n
    t = index - math.floor(index)
    return curve[i] * (1.0 - t) + curve[(i + 1) % n] * t


class Flyer(pygame.sprite.Sprite):
    """Flap-driven lap around the spawn. Altitude tracks the wing, not a separate bob."""

    draws_above_y_sort = True

    def __init__(self, pos, groups, level=None):
        super().__init__(groups)
        self.monster_name = "flyer"
        self.team_id = "enemy"
        self.level = level
        self.right_frames, self.left_frames, self.wing_step, self.wing_low, actions = _load()
        self.actions = actions
        self.attacks = [name for name in _ATTACKS if name in actions]
        n = len(self.right_frames)
        ticks_per_beat = n / self.wing_step
        angle_per_beat = math.tau / BEATS_PER_LAP
        self.coast_step = (COAST_SHARE * angle_per_beat) / ticks_per_beat
        self.surge = (1.0 - COAST_SHARE) * angle_per_beat
        self.frame_index = 0.0
        self.wing_low_now = _sample(self.wing_low, 0.0)
        self.origin_x = float(pos[0])
        self.origin_y = float(pos[1])
        # Different spawns leave the circle at different points.
        self.angle = (self.origin_x * 0.002 + self.origin_y * 0.001) % (math.tau)
        self.facing_right = True
        self.altitude = HOVER_PX
        self.ground_x = self.origin_x
        self.ground_y = self.origin_y
        self.action = None
        self.action_index = 0.0
        self.attack_cursor = 0
        self.attack_wait = 0
        self.hurt_lock = 0
        self.hold_x = self.origin_x
        self.hold_y = self.origin_y
        self.image = self.right_frames[0]
        self.rect = self.image.get_rect()
        self._place()

    def receive_interaction(self, ctx):
        # A hit plays the tumble. It does not play during the tumble itself,
        # or the same swing would restart it every tick.
        if getattr(ctx, "kind", None) != "damage":
            return
        if "hurt" not in self.actions:
            return
        if self.action == "hurt" or self.hurt_lock > 0:
            return
        self._begin_action("hurt")

    def update(self, dt=None, **kwargs):
        # One tick, like Entity.move and CombatUnit.animate. The dt handed in is
        # seconds and the rest of the sim does not scale by it.
        if self.hurt_lock > 0:
            self.hurt_lock -= 1
        if self.action is not None:
            self._advance_action()
            return
        self._flap_tick()
        if self.attack_wait > 0:
            self.attack_wait -= 1
            return
        if self.attacks and self._player_in_range():
            name = self.attacks[self.attack_cursor % len(self.attacks)]
            self.attack_cursor += 1
            self._begin_action(name)

    def _player_point(self):
        level = self.level
        player = None if level is None else getattr(level, "player", None)
        if player is None:
            return None
        hitbox = getattr(player, "hitbox", None)
        if hitbox is not None:
            return float(hitbox.centerx), float(hitbox.centery)
        rect = getattr(player, "rect", None)
        if rect is None:
            return None
        return float(rect.centerx), float(rect.centery)

    def _player_in_range(self):
        point = self._player_point()
        if point is None:
            return False
        dx = point[0] - self.ground_x
        dy = point[1] - self.ground_y
        return dx * dx + dy * dy <= ATTACK_RANGE_PX * ATTACK_RANGE_PX

    def _flap_tick(self):
        prev = self.wing_low_now
        self.frame_index = (self.frame_index + self.wing_step) % len(self.right_frames)
        low = _sample(self.wing_low, self.frame_index)
        # Positive while the wings travel downward: that is the push.
        power = max(0.0, low - prev)
        self.wing_low_now = low
        self.angle = (self.angle + self.coast_step + self.surge * power) % math.tau
        self.altitude = HOVER_PX + FLAP_LIFT_PX * (low * 2.0 - 1.0)
        self._place()

    def _begin_action(self, name):
        if name not in self.actions:
            return
        point = self._player_point()
        if point is not None:
            self.facing_right = point[0] >= self.ground_x
        self.action = name
        self.action_index = 0.0
        # The body stays on this point. Motion after this is inside the frames.
        self.hold_x = float(self.rect.centerx)
        self.hold_y = float(self.rect.centery)
        self._place_action()

    def _advance_action(self):
        spec = self.actions[self.action]
        self.action_index += spec["step"]
        if self.action_index >= len(spec["right"]):
            finished = self.action
            self.action = None
            self.frame_index = 0.0
            self.wing_low_now = _sample(self.wing_low, 0.0)
            if finished == "hurt":
                self.hurt_lock = 45
            elif finished in _ATTACKS:
                self.attack_wait = ATTACK_GAP_TICKS
            self._flap_tick()
            return
        self._place_action()

    def _place_action(self):
        spec = self.actions[self.action]
        frames = spec["right"] if self.facing_right else spec["left"]
        image = frames[min(int(self.action_index), len(frames) - 1)]
        ax, ay = spec["anchor"]
        if not self.facing_right:
            ax = image.get_width() - 1 - ax
        self.image = image
        self.rect = image.get_rect(topleft=(round(self.hold_x - ax), round(self.hold_y - ay)))

    def _place(self):
        ground_x = self.origin_x + math.cos(self.angle) * ORBIT_RADIUS_PX
        ground_y = self.origin_y + math.sin(self.angle) * ORBIT_RADIUS_PX * ORBIT_Y_SCALE
        # Tangent of x = origin + cos(angle): positive x is the rightward half.
        vx = -math.sin(self.angle)
        if abs(vx) > 0.2:
            self.facing_right = vx > 0.0
        frames = self.right_frames if self.facing_right else self.left_frames
        self.image = frames[int(self.frame_index)]
        lift = self.altitude * math.cos(math.radians(VIEW_ELEVATION_DEG))
        self.ground_x = ground_x
        self.ground_y = ground_y
        self.rect = self.image.get_rect(midbottom=(round(ground_x), round(ground_y - lift)))
