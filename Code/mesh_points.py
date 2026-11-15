"""A mesh body's hit outline from its real vertices: what is drawn is what is hit (damage chunk 4b).

The other way is body.json's capsules (mesh_boss.build_body_mask): round tubes fitted per bone, cheap,
but as deep as they are wide, so a flat chest seen from the side is a fat tube. This one takes the
mesh's own vertices:

- A few thousand of them, spread evenly (one per cell of a grid over the rest pose), with their skin
  weights. Each animation frame is posed once, the first time it is asked for (linear blend skinning,
  as the GPU does), and kept.
- For a pose and facing: project like the camera (same pivot, yaw, scale and elevation as the draw),
  spread each point over a 3x3 block so the outline is solid, keep the nearest point per pixel. The
  result is the hit mask and, per pixel, which point is in front there (so which bone). Kept in a
  small LRU.

No game imports besides pygame masks, so it runs headless.
"""
from __future__ import annotations

import math
import os
from collections import OrderedDict

import numpy as np
import pygame

from Settings import VIEW_ELEVATION_DEG

TARGET_POINTS = 3000
OUTLINE_CACHE = 64
# Each point covers SPLAT x SPLAT pixels so the outline is solid (2: a half-pixel rim, 3: one pixel).
SPLAT = 2
_SPLATS = {n: np.array([(dx, dy) for dy in range(n) for dx in range(n)], dtype=np.int32) - (n - 1) // 2
           for n in (2, 3)}

_CLOUDS = {}


class Outline:
    """One pose's hit outline, from the feet at (0, 0): mask at (dx, dy); labels[y, x] = point index
    in front there (-1: nothing)."""

    __slots__ = ("mask", "dx", "dy", "labels")

    def __init__(self, mask, dx, dy, labels):
        self.mask = mask
        self.dx = dx
        self.dy = dy
        self.labels = labels

    def point_at(self, x, y):
        """The point in front at screen offset (x, y) from the feet, or the nearest one within 2 px;
        None if there is none."""
        h, w = self.labels.shape
        cx, cy = int(math.floor(x - self.dx)), int(math.floor(y - self.dy))
        for r in (0, 1, 2):
            best = None
            for oy in range(-r, r + 1):
                for ox in range(-r, r + 1):
                    if max(abs(ox), abs(oy)) != r:
                        continue
                    px, py = cx + ox, cy + oy
                    if 0 <= px < w and 0 <= py < h and self.labels[py, px] >= 0:
                        d = ox * ox + oy * oy
                        if best is None or d < best[0]:
                            best = (d, int(self.labels[py, px]))
            if best is not None:
                return best[1]
        return None


class PointCloud:
    """The thinned vertices of one skinned pack, posed per frame on demand."""

    def __init__(self, pack, target=TARGET_POINTS):
        data = np.load(os.path.join(pack.root, "skin.npz"))
        rest = np.asarray(data["rest_pos"], dtype=np.float64)
        joints = np.asarray(data["joints"]).astype(np.int64)
        weights = np.asarray(data["weights"], dtype=np.float64)
        idx = _even_subset(rest, target)
        self.pack = pack
        self.count = len(idx)
        self.rest_h = np.hstack([rest[idx], np.ones((len(idx), 1))])
        self.joints = joints[idx]
        self.weights = weights[idx]
        self.owner = self.joints[np.arange(len(idx)), np.argmax(self.weights, axis=1)].astype(np.int32)
        self.pivot = np.asarray(pack.pivot, dtype=np.float64)
        self._posed = {}
        self._reach = {}
        self._outlines = OrderedDict()

    def posed(self, frame):
        """(N, 3) points of `frame`, minus the pivot. Posed once per frame."""
        p = self._posed.get(frame)
        if p is None:
            mats = np.asarray(self.pack.skin_mats[frame], dtype=np.float64)
            p = np.zeros((self.count, 3))
            for k in range(4):
                p += self.weights[:, k:k + 1] * np.einsum(
                    "vij,vj->vi", mats[self.joints[:, k]], self.rest_h)[:, :3]
            p -= self.pivot
            self._posed[frame] = p
            # how far the pose reaches: the box any facing fits in (for hit_rect)
            horiz = float(np.sqrt(p[:, 0] ** 2 + p[:, 1] ** 2).max())
            self._reach[frame] = (horiz, float(p[:, 2].min()), float(p[:, 2].max()))
        return p

    def reach_box(self, frame, scale, elevation_deg=VIEW_ELEVATION_DEG):
        """(dx, dy, w, h) from the feet that holds this frame's outline at any facing: cheap, a little
        bigger than the outline."""
        self.posed(frame)
        horiz, zmin, zmax = self._reach[frame]
        e = math.radians(elevation_deg)
        r = horiz * scale + 2
        top = -zmax * scale * math.cos(e) - horiz * scale * math.sin(e) - 2
        bottom = -zmin * scale * math.cos(e) + horiz * scale * math.sin(e) + 2
        return (-r, top, 2 * r, bottom - top)

    def outline(self, frame, yaw_deg, scale, elevation_deg=VIEW_ELEVATION_DEG):
        yaw_key = int(round(float(yaw_deg))) % 360
        key = (frame, yaw_key, round(float(scale), 4), round(float(elevation_deg), 2))
        found = self._outlines.get(key)
        if found is not None:
            self._outlines.move_to_end(key)
            return found
        p = self.posed(frame)
        yaw = math.radians(yaw_key)
        c, s = math.cos(yaw), math.sin(yaw)
        e = math.radians(elevation_deg)
        se, ce = math.sin(e), math.cos(e)
        gy = -(p[:, 0] * s + p[:, 1] * c) * scale
        gz = p[:, 2] * scale
        sx = np.floor((p[:, 0] * c - p[:, 1] * s) * scale).astype(np.int32)
        sy = np.floor(gy * se - gz * ce).astype(np.int32)
        depth = gy * ce + gz * se
        x0, y0 = int(sx.min()) - 1, int(sy.min()) - 1
        w, h = int(sx.max()) - x0 + 3, int(sy.max()) - y0 + 3
        order = np.argsort(depth).astype(np.int32)               # far first: nearer writes last
        base = (sy[order] - y0) * w + (sx[order] - x0)
        offsets = _SPLATS[SPLAT][:, 1] * w + _SPLATS[SPLAT][:, 0]
        keys = (base[:, None] + offsets[None, :]).ravel()        # each point's block together, far first
        labels = np.full(h * w, -1, dtype=np.int32)
        labels[keys] = np.repeat(order, len(offsets))           # one write: the last (nearest) wins
        labels = labels.reshape(h, w)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        alpha = pygame.surfarray.pixels_alpha(surf)
        alpha[:] = ((labels >= 0) * 255).astype(np.uint8).T
        del alpha
        found = Outline(pygame.mask.from_surface(surf), x0, y0, labels)
        self._outlines[key] = found
        if len(self._outlines) > OUTLINE_CACHE:
            self._outlines.popitem(last=False)
        return found


def _even_subset(rest, target):
    """Indices of about `target` vertices spread evenly: one per cell of a grid over the rest pose,
    the grid coarsened until it gives at most `target`."""
    span = float(np.ptp(rest, axis=0).max())
    cell = span / 120.0
    while True:
        cells = np.floor(rest / cell).astype(np.int64)
        _, idx = np.unique(cells, axis=0, return_index=True)
        if len(idx) <= target:
            return np.sort(idx)
        cell *= 1.15


def cloud(pack):
    """The one PointCloud of a pack."""
    found = _CLOUDS.get(pack.name)
    if found is None:
        found = PointCloud(pack)
        _CLOUDS[pack.name] = found
    return found
