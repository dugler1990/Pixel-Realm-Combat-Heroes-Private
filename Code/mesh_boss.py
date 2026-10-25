"""Method B: draw a boss as a real mesh instead of pre-rendered sprites.

Method A (tools/boss_sprite_pipeline) bakes every pose x direction to PNGs: ~1 GB on disk and
~70 min of render per boss, frames sized by the widest pose, and the size on screen is fixed at
bake time. Method B ships one decimated mesh + one texture + baked per-frame vertex positions
(``export_mesh_runtime.py``) and poses it on the GPU:

    disk      ~10-30 MB per boss instead of ~1 GB
    VRAM      one vertex buffer + one texture; frames stream into it
    scale      free -- any size, any angle, no re-render
    render     none; changing the animation is a bpy re-bake, minutes not hours

The cost is a real 3D pass inside a 2D engine: its own shader, depth buffer and camera. This
module owns all of that and nothing else in the engine needs to know. It draws through the
existing GPUBackend's GL context (`backend.draw_mesh_boss`), so there is no second window and no
new dependency -- PyOpenGL is already required by the backend.

    boss = MeshBoss("demon")                     # loads Graphics/Meshes/demon/
    boss.set_action("move"); boss.advance(dt)
    boss.draw(backend, screen_pos, facing_deg, height_px=650)

Collision comes from body.json capsules posed with the same skin_mats the draw uses.
Not loaded == not paid for: nothing happens until a MeshBoss is constructed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import OrderedDict

import numpy as np
import pygame

from Settings import VIEW_ELEVATION_DEG
from body_contact import CONTACT_STATS, ground_to_screen, model_to_ground

MESH_ROOT = "../Graphics/Meshes"
BODY_VERSION = 1
_MASK_CACHE_CAP = 128


def project_model_points(points, pivot, facing_deg, scale, elevation_deg=VIEW_ELEVATION_DEG):
    """Orthographic screen offsets from the feet, matching the skin shader."""
    return ground_to_screen(
        model_to_ground(points, pivot, facing_deg, scale), elevation_deg
    )


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _BodyMaskCache:
    """Process-wide LRU of capsule masks. Keyed so every machine gets the same mask."""

    def __init__(self, capacity=_MASK_CACHE_CAP):
        self.capacity = int(capacity)
        self._items: OrderedDict = OrderedDict()
        self.demons = 0
        self.builds = 0
        self.hits = 0
        self.ms = 0.0
        self._log_at = 0

    def get(self, key):
        item = self._items.get(key)
        if item is None:
            return None
        self._items.move_to_end(key)
        self.hits += 1
        return item

    def put(self, key, value):
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def note_demon(self):
        self.demons += 1
        self.flush_log()

    def note_build(self, ms):
        self.builds += 1
        self.ms += float(ms)

    def flush_log(self, now_ms=None):
        """Print this second's cost once a second, then clear the counters."""
        if now_ms is None:
            try:
                now_ms = pygame.time.get_ticks()
            except Exception:
                now_ms = int(time.time() * 1000)
        if self._log_at == 0:
            self._log_at = now_ms
            return
        if now_ms - self._log_at < 1000:
            return
        print(
            f"[body] demons={self.demons} builds={self.builds} "
            f"hits={self.hits} ms={self.ms:.2f} "
            f"contacts={CONTACT_STATS['contacts']} contact_ms={CONTACT_STATS['ms']:.2f}"
        )
        self._log_at = now_ms
        self.demons = 0
        self.builds = 0
        self.hits = 0
        self.ms = 0.0
        CONTACT_STATS["contacts"] = 0
        CONTACT_STATS["ms"] = 0.0

    def clear(self):
        self._items.clear()
        self.demons = 0
        self.builds = 0
        self.hits = 0
        self.ms = 0.0
        self._log_at = 0


BODY_MASK_CACHE = _BodyMaskCache()


def flush_body_mask_log(now_ms=None):
    BODY_MASK_CACHE.flush_log(now_ms)


def _draw_capsule_2d(surf, a, b, radius, color=(255, 255, 255, 255)):
    """Rasterize a 2D stadium (two circles + the quad between them)."""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    r = max(1, int(math.ceil(float(radius))))
    pygame.draw.circle(surf, color, (int(round(ax)), int(round(ay))), r)
    pygame.draw.circle(surf, color, (int(round(bx)), int(round(by))), r)
    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    nx = -dy / length * float(radius)
    ny = dx / length * float(radius)
    pts = [
        (ax + nx, ay + ny),
        (ax - nx, ay - ny),
        (bx - nx, by - ny),
        (bx + nx, by + ny),
    ]
    pygame.draw.polygon(surf, color, pts)


def _pose_capsule_ends(pack, frame_index):
    """Return posed capsule endpoints as (N*2, 3) float64."""
    bones = np.asarray([c["bone"] for c in pack.capsules], dtype=np.int32)
    ends = np.empty((len(pack.capsules) * 2, 4), dtype=np.float64)
    for i, cap in enumerate(pack.capsules):
        ends[2 * i, :3] = cap["a"]
        ends[2 * i + 1, :3] = cap["b"]
        ends[2 * i, 3] = 1.0
        ends[2 * i + 1, 3] = 1.0
    mats = np.asarray(pack.skin_mats[int(frame_index)], dtype=np.float64)
    bone_mats = mats[bones]
    end_mats = np.repeat(bone_mats, 2, axis=0)
    return np.einsum("nij,nj->ni", end_mats, ends)[:, :3]


def _capsule_projection(
    pack,
    frame_index,
    facing_deg,
    scale,
    elevation_deg=VIEW_ELEVATION_DEG,
):
    """Pose + project capsules. Returns (facing_key, xy, radii, x0, y0, w, h)."""
    if not pack.capsules:
        raise RuntimeError(f"pack {pack.name!r} has no body capsules")
    facing_key = int(round(float(facing_deg))) % 360
    posed = _pose_capsule_ends(pack, frame_index)
    radii = np.asarray([c["radius"] for c in pack.capsules], dtype=np.float64) * float(scale)
    xy = project_model_points(posed, pack.pivot, facing_key, scale, elevation_deg)

    pad = float(radii.max()) + 2.0 if radii.size else 2.0
    x0 = float(xy[:, 0].min()) - pad
    y0 = float(xy[:, 1].min()) - pad
    x1 = float(xy[:, 0].max()) + pad
    y1 = float(xy[:, 1].max()) + pad
    w = max(1, int(math.ceil(x1 - x0)))
    h = max(1, int(math.ceil(y1 - y0)))
    return facing_key, xy, radii, x0, y0, w, h


def capsule_screen_bounds(
    pack,
    frame_index,
    facing_deg,
    scale,
    elevation_deg=VIEW_ELEVATION_DEG,
):
    """Projected capsule AABB relative to feet at (0, 0).

    Returns ``(dx, dy, w, h, ground_radius_px)`` where ``(dx, dy)`` is the
    top-left of the AABB (same convention as ``build_body_mask``'s mask offset)
    and ``ground_radius_px`` is ``max(capsule radii) * scale``.
    """
    _facing, _xy, radii, x0, y0, w, h = _capsule_projection(
        pack, frame_index, facing_deg, scale, elevation_deg)
    ground_radius_px = float(radii.max()) if radii.size else 8.0
    return x0, y0, w, h, ground_radius_px


def build_body_mask(
    pack,
    frame_index,
    facing_deg,
    scale,
    elevation_deg=VIEW_ELEVATION_DEG,
):
    """Pose rest capsules, project, rasterize. Returns (mask, dx, dy) from feet.

    dx, dy are the top-left of the mask relative to the feet / hitbox.midbottom.
    Tools/tests only — gameplay uses ``capsule_screen_bounds`` instead.
    """
    if not pack.capsules:
        raise RuntimeError(f"pack {pack.name!r} has no body capsules")
    facing_key = int(round(float(facing_deg))) % 360
    scale_key = round(float(scale), 4)
    elev_key = round(float(elevation_deg), 2)
    key = (pack.name, int(frame_index), facing_key, scale_key, elev_key)

    BODY_MASK_CACHE.note_demon()
    cached = BODY_MASK_CACHE.get(key)
    if cached is not None:
        return cached

    t0 = time.perf_counter()
    facing_key, xy, radii, x0, y0, w, h = _capsule_projection(
        pack, frame_index, facing_key, scale, elevation_deg)
    surf = pygame.Surface((w, h), flags=pygame.SRCALPHA)
    for i in range(len(pack.capsules)):
        a = (xy[2 * i, 0] - x0, xy[2 * i, 1] - y0)
        b = (xy[2 * i + 1, 0] - x0, xy[2 * i + 1, 1] - y0)
        _draw_capsule_2d(surf, a, b, radii[i])
    mask = pygame.mask.from_surface(surf)
    result = (mask, x0, y0)
    BODY_MASK_CACHE.note_build((time.perf_counter() - t0) * 1000.0)
    BODY_MASK_CACHE.put(key, result)
    return result


class MeshBossPack:
    """The on-disk pack: geometry, per-frame vertex positions, albedo. One per monster name."""

    _cache: dict[str, "MeshBossPack"] = {}

    def __init__(self, name):
        root = os.path.normpath(os.path.join(MESH_ROOT, name))
        self.name = name
        self.root = root
        with open(os.path.join(root, "pack.json"), encoding="utf-8") as fh:
            self.meta = json.load(fh)
        self.albedo_path = os.path.join(root, self.meta.get("albedo", "albedo.png"))
        self.skinned = self.meta.get("format") == "skin" and os.path.isfile(os.path.join(root, "skin.npz"))
        self.capsules = []
        self.capsule_radii = np.zeros(0, dtype=np.float64)
        self._posed_ends_cache: dict = {}
        if self.skinned:
            skin_path = os.path.join(root, "skin.npz")
            data = np.load(skin_path)
            self.rest_pos = data["rest_pos"]
            self.rest_nrm = data["rest_nrm"]
            self.uv = data["uv"]
            self.indices = data["indices"]
            self.joints = data["joints"]
            self.weights = data["weights"]
            self.skin_mats = data["skin_mats"]          # [frames, bones, 4, 4]
            self.ranges = json.loads(str(data["ranges"]))
            self.fps = float(data["fps"])
            self.pivot = np.array(data["pivot"], dtype=np.float32)
            lo = np.array(data["bbox_lo"], np.float32)
            hi = np.array(data["bbox_hi"], np.float32)
            self._load_body(root, skin_path)
        else:
            npz_path = os.path.join(root, "mesh.npz")
            try:
                data = np.load(npz_path, mmap_mode="r")
            except ValueError:
                data = np.load(npz_path)
            self.positions = data["positions"]          # [frames, V, 3] float16
            self.normals = data["normals"]              # [frames, V, 3] int8
            self.uv = data["uv"].astype(np.float32)     # [V, 2]
            self.indices = data["indices"].astype(np.uint32)
            self.ranges = json.loads(str(data["ranges"]))
            self.fps = float(data["fps"])
            self.pivot = np.array(data["pivot"], dtype=np.float32)
            lo = np.array(data["bbox_lo"], np.float32)
            hi = np.array(data["bbox_hi"], np.float32)
        self.bbox_lo = lo
        self.bbox_hi = hi
        self.height_units = float(hi[2] - lo[2])

    def _load_body(self, root, skin_path):
        body_path = os.path.join(root, "body.json")
        if not os.path.isfile(body_path):
            raise FileNotFoundError(
                f"skinned pack {self.name!r} is missing body.json; "
                f"run tools/boss_sprite_pipeline/bake_body_capsules.py {self.name}"
            )
        with open(body_path, encoding="utf-8") as fh:
            body = json.load(fh)
        if int(body.get("version", -1)) != BODY_VERSION:
            raise ValueError(
                f"body.json for {self.name!r} has version {body.get('version')!r}, "
                f"expected {BODY_VERSION}"
            )
        expected = sha1_file(skin_path)
        got = body.get("skin_sha1")
        if got != expected:
            raise ValueError(
                f"body.json for {self.name!r} was baked for skin sha1 {got}, "
                f"but skin.npz is {expected}; re-run bake_body_capsules.py"
            )
        self.capsules = []
        for cap in body.get("capsules") or []:
            self.capsules.append({
                "bone": int(cap["bone"]),
                "a": np.asarray(cap["a"], dtype=np.float64),
                "b": np.asarray(cap["b"], dtype=np.float64),
                "radius": float(cap["radius"]),
            })
        if not self.capsules:
            raise ValueError(f"body.json for {self.name!r} has no capsules")
        self.capsule_radii = np.asarray(
            [c["radius"] for c in self.capsules], dtype=np.float64
        )
        self._posed_ends_cache = {}

    def posed_capsule_ends(self, frame_index):
        """Posed capsule endpoints A, B as (N,3) model-space arrays. Cached per frame."""
        frame = int(frame_index)
        cached = self._posed_ends_cache.get(frame)
        if cached is not None:
            return cached
        posed = _pose_capsule_ends(self, frame)
        n = len(self.capsules)
        A = posed[0::2].copy()
        B = posed[1::2].copy()
        self._posed_ends_cache[frame] = (A, B)
        return A, B

    @classmethod
    def get(cls, name):
        pack = cls._cache.get(name)
        if pack is None:
            pack = cls._cache[name] = cls(name)
        return pack

    @classmethod
    def exists(cls, name):
        return os.path.isfile(os.path.normpath(os.path.join(MESH_ROOT, name, "pack.json")))

    @classmethod
    def clear_cache(cls):
        cls._cache.clear()


class MeshBoss:
    """One drawable instance. Cheap: the pack (the big arrays) is shared between instances."""

    # Engine statuses stay idle/move/attack; current packs use clip names.
    _STATUS_ALIASES = {
        "idle": ("idle", "settle_01", "settle_02", "settle_03"),
        "move": ("move", "walk", "run"),
        "attack": ("attack", "attack2", "attack3"),
        # MeteorShower / cast specials — kneepunch retarget, renamed cast1_swift in pack.
        "Summoning": ("cast1_swift", "kneepunch", "idle", "settle_01"),
        "cast1_swift": ("cast1_swift", "kneepunch"),
    }
    # 24/30 fps source idles read best at about half speed.
    _HALF_SPEED = frozenset({"idle", "settle_01", "settle_02", "settle_03"})

    def __init__(self, name, action="idle"):
        self.pack = MeshBossPack.get(name)
        resolved = self.resolve_action(action)
        self.action = resolved if resolved is not None else sorted(self.pack.ranges)[0]
        self.frame = 0.0
        self._uploaded = False

    def resolve_action(self, action):
        if action in self.pack.ranges:
            return action
        for candidate in self._STATUS_ALIASES.get(action, ()):
            if candidate in self.pack.ranges:
                return candidate
        return None

    # --- playback -----------------------------------------------------------------------
    def set_action(self, action):
        resolved = self.resolve_action(action)
        if resolved is not None and resolved != self.action:
            self.action = resolved
            self.frame = 0.0

    def playback_fps(self):
        fps = self.pack.fps
        if self.action in self._HALF_SPEED:
            return fps * 0.5
        return fps

    def advance(self, dt, fps=None, loop=True):
        lo, hi = self.pack.ranges[self.action]
        n = hi - lo + 1
        self.frame += (fps if fps is not None else self.playback_fps()) * dt
        self._clip_finished = False
        if self.frame >= n:
            self._clip_finished = True
            self.frame = self.frame % n if loop else n - 1
        return int(self.frame)

    @property
    def clip_finished(self):
        return bool(getattr(self, "_clip_finished", False))

    def advance_frames(self, frames, loop=True):
        """Step by a frame count. Walk uses this so the cycle matches ground covered."""
        lo, hi = self.pack.ranges[self.action]
        n = hi - lo + 1
        self.frame += float(frames)
        if self.frame >= n:
            self.frame = self.frame % n if loop else n - 1
        elif self.frame < 0:
            self.frame = 0.0
        return int(self.frame)

    @property
    def frame_index(self):
        # A constant, not "skip advance": set_action still jumps idle <-> walk ranges,
        # and every demon of a pack shares one uploaded frame.
        pin = os.environ.get("PRCH_MESH_PIN_FRAME", "")
        if pin != "":
            return int(pin)
        lo, _ = self.pack.ranges[self.action]
        return lo + int(self.frame)

    def body_mask(self, facing_deg, height_px, elevation_deg=VIEW_ELEVATION_DEG):
        """Capsule mask for the current frame, hung as an offset from the feet."""
        scale = float(height_px) / max(self.pack.height_units, 1e-6)
        return build_body_mask(
            self.pack, self.frame_index, facing_deg, scale, elevation_deg)

    def body_bounds(self, facing_deg, height_px, elevation_deg=VIEW_ELEVATION_DEG):
        """Capsule AABB for the current frame: (dx, dy, w, h, ground_radius_px)."""
        scale = float(height_px) / max(self.pack.height_units, 1e-6)
        return capsule_screen_bounds(
            self.pack, self.frame_index, facing_deg, scale, elevation_deg)

    # --- drawing ------------------------------------------------------------------------
    def draw(self, backend, screen_pos, facing_deg=0.0, height_px=650,
             elevation_deg=VIEW_ELEVATION_DEG,
             light_dir=(-0.4, -0.5, 0.75), ambient=0.35):
        """Draw at `screen_pos` (the ground-contact pixel), `height_px` tall on screen.

        `facing_deg` spins the model about its up axis, so any angle works -- not just the 8
        the sprite route bakes. Falls back silently on a backend without the mesh pass (CPU).
        """
        draw = getattr(backend, "draw_mesh_boss", None)
        if draw is None:
            return False
        scale = height_px / max(self.pack.height_units, 1e-6)
        amb = os.environ.get("PRCH_MESH_AMBIENT", "")
        if amb != "":
            ambient = float(amb)
        return draw(self.pack, self.frame_index, screen_pos, facing_deg, scale,
                    elevation_deg, light_dir, ambient)
