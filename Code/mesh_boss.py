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

Not loaded == not paid for: nothing happens until a MeshBoss is constructed.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

MESH_ROOT = "../Graphics/Meshes"


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
        if self.skinned:
            data = np.load(os.path.join(root, "skin.npz"))
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

    @classmethod
    def get(cls, name):
        pack = cls._cache.get(name)
        if pack is None:
            pack = cls._cache[name] = cls(name)
        return pack

    @classmethod
    def exists(cls, name):
        return os.path.isfile(os.path.normpath(os.path.join(MESH_ROOT, name, "pack.json")))


class MeshBoss:
    """One drawable instance. Cheap: the pack (the big arrays) is shared between instances."""

    # Engine statuses stay idle/move/attack; current packs use clip names.
    _STATUS_ALIASES = {
        "idle": ("idle", "settle_01", "settle_02", "settle_03"),
        "move": ("move", "walk", "run"),
        "attack": ("attack", "attack2", "attack3"),
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
        if self.frame >= n:
            self.frame = self.frame % n if loop else n - 1
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

    # --- drawing ------------------------------------------------------------------------
    def draw(self, backend, screen_pos, facing_deg=0.0, height_px=650, elevation_deg=45.0,
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
