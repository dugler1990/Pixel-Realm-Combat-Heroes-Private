"""A mesh body's hit outline from its real vertices: what is drawn is what is hit (damage chunk 4b).

The other way is body.json's capsules (mesh_boss.build_body_mask): round tubes fitted per bone, cheap,
but as deep as they are wide, so a flat chest seen from the side is a fat tube. This one takes the
mesh's own vertices:

- A few thousand of them, spread evenly (one per cell of a grid over the rest pose), with their skin
  weights. Each animation frame is posed once, the first time it is asked for (linear blend skinning,
  as the GPU does), and kept.
- Worn pieces (armour, loincloth: skinned packs on the body's skeleton) get points at the body's
  spacing and are posed about the body's pivot, as PlayerMesh.draw draws them.
- For a pose and facing: project like the camera (same pivot, yaw, scale and elevation as the draw),
  spread each point over a SPLAT x SPLAT block so the outline is solid, keep the nearest point per
  pixel. The result is the hit mask and, per pixel, the point in front there: its bone (owner) and
  whether it is the body (skin) or which worn piece (source). Kept in a small LRU.

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
POSED_CACHE = 128         # posed frames kept per cloud (float32)
# Each point covers SPLAT x SPLAT pixels so the outline is solid (2: a half-pixel rim, 3: one pixel).
SPLAT = 2
_SPLATS = {n: np.array([(dx, dy) for dy in range(n) for dx in range(n)], dtype=np.int32) - (n - 1) // 2
           for n in (2, 3)}

_CLOUDS = {}


class Outline:
    """One pose's hit outline, from the feet at (0, 0): mask at (dx, dy); labels[y, x] = the point in
    front there (-1: nothing). owner[point] = its bone; source[point] = 0 for the body, k for
    names[k], the worn piece it belongs to (names[0] is None)."""

    __slots__ = ("mask", "dx", "dy", "labels", "owner", "source", "names")

    def __init__(self, mask, dx, dy, labels, owner, source, names):
        self.mask = mask
        self.dx = dx
        self.dy = dy
        self.labels = labels
        self.owner = owner
        self.source = source
        self.names = names

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

    def piece_of(self, point):
        """The worn piece a point belongs to (its pack name), None for the body."""
        return self.names[int(self.source[point])]


class PointCloud:
    """The thinned vertices of one skinned pack, posed per frame on demand. `cell`: the grid spacing
    (default: coarsened until at most `target` points); `pivot`: what to pose about (default the
    pack's; a worn piece uses its body's)."""

    def __init__(self, pack, target=TARGET_POINTS, cell=None, pivot=None):
        data = np.load(os.path.join(pack.root, "skin.npz"))
        rest = np.asarray(data["rest_pos"], dtype=np.float64)
        joints = np.asarray(data["joints"]).astype(np.int64)
        weights = np.asarray(data["weights"], dtype=np.float64)
        idx, self.cell = _even_subset(rest, target, cell)
        self.pack = pack
        self.count = len(idx)
        self.rest_h = np.hstack([rest[idx], np.ones((len(idx), 1))])
        self.joints = joints[idx]
        self.weights = weights[idx]
        self.owner = self.joints[np.arange(len(idx)), np.argmax(self.weights, axis=1)].astype(np.int32)
        self.pivot = np.asarray(pack.pivot if pivot is None else pivot, dtype=np.float64)
        self._posed = OrderedDict()
        self._reach = {}
        self._outlines = OrderedDict()

    def _mats(self, frame):
        return np.asarray(self.pack.skin_mats[frame], dtype=np.float64)

    def _live(self):
        """Per weight slot, the points whose weight there is > 0 (made once)."""
        live = getattr(self, "_live_idx", None)
        if live is None:
            live = [np.nonzero(self.weights[:, k] > 0)[0] for k in range(self.weights.shape[1])]
            self._live_idx = live
        return live

    def posed(self, frame):
        """(N, 3) points of `frame`, minus the pivot. Posed once per frame (the last POSED_CACHE kept)."""
        p = self._posed.get(frame)
        if p is None:
            mats = self._mats(frame)[:, :3, :]                    # the last row is 0 0 0 1
            p = np.zeros((self.count, 3))
            for k, idx in enumerate(self._live()):
                # only the points with a weight in this slot (slot 0: all; 1-3: 31%, 15%, 10% on the barb)
                p[idx] += self.weights[idx, k:k + 1] * np.einsum(
                    "vij,vj->vi", mats[self.joints[idx, k]], self.rest_h[idx])
            p -= self.pivot
            p = p.astype(np.float32)
            self._posed[frame] = p
            if len(self._posed) > POSED_CACHE:
                self._posed.popitem(last=False)
            # how far the pose reaches: the box any facing fits in (for hit_rect)
            horiz = float(np.sqrt(p[:, 0] ** 2 + p[:, 1] ** 2).max())
            self._reach[frame] = (horiz, float(p[:, 2].min()), float(p[:, 2].max()))
        else:
            self._posed.move_to_end(frame)
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

    source = None          # per point: 0 the body, k = names[k] (WornCloud); None: all body
    names = (None,)

    def outline(self, frame, yaw_deg, scale, elevation_deg=VIEW_ELEVATION_DEG):
        """The outline of this pose."""
        yaw_key = int(round(float(yaw_deg))) % 360
        key = (frame, yaw_key, round(float(scale), 4), round(float(elevation_deg), 2))
        found = self._outlines.get(key)
        if found is not None:
            self._outlines.move_to_end(key)
            return found
        source = self.source if self.source is not None else np.zeros(self.count, dtype=np.int16)
        found = _build(self.posed(frame), yaw_key, scale, elevation_deg, self.owner, source, self.names)
        self._outlines[key] = found
        if len(self._outlines) > OUTLINE_CACHE:
            self._outlines.popitem(last=False)
        return found


def _build(p, yaw_deg, scale, elevation_deg, owner, source, names):
    yaw = math.radians(yaw_deg)
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
    return Outline(pygame.mask.from_surface(surf), x0, y0, labels, owner, source, names)


def _even_subset(rest, target, cell=None):
    """(indices, cell): one vertex per cell of a grid over the rest pose. Without `cell`, the grid is
    coarsened until it gives at most `target` vertices."""
    if cell is not None:
        _, idx = np.unique(np.floor(rest / cell).astype(np.int64), axis=0, return_index=True)
        return np.sort(idx), cell
    span = float(np.ptp(rest, axis=0).max())
    cell = span / 120.0
    while True:
        _, idx = np.unique(np.floor(rest / cell).astype(np.int64), axis=0, return_index=True)
        if len(idx) <= target:
            return np.sort(idx), cell
        cell *= 1.15


def cloud(pack):
    """The one PointCloud of a pack."""
    found = _CLOUDS.get(pack.name)
    if found is None:
        found = PointCloud(pack)
        _CLOUDS[pack.name] = found
    return found


def piece_cloud(piece_pack, body_pack):
    """The PointCloud of a worn piece: the body's point spacing, posed about the body's pivot."""
    key = (piece_pack.name, body_pack.name)
    found = _CLOUDS.get(key)
    if found is None:
        body = cloud(body_pack)
        found = PointCloud(piece_pack, cell=body.cell, pivot=body.pivot)
        _CLOUDS[key] = found
    return found


class WornCloud(PointCloud):
    """A body and the pieces it wears as one cloud, posed in one pass. `frame` is the body's frame; each
    piece uses the same clip and step in its own ranges (as PlayerMesh.piece_frames): the matrices of
    every pack for its frame are stacked, and each point indexes its own pack's."""

    def __init__(self, body_pack, pieces):
        body = cloud(body_pack)
        parts = [body] + [piece_cloud(pack, body_pack) for _, pack in pieces]
        self.pack = body_pack
        self.packs = [body_pack] + [pack for _, pack in pieces]
        self.names = (None,) + tuple(name for name, _ in pieces)
        self.cell = body.cell
        self.pivot = body.pivot
        self.count = sum(part.count for part in parts)
        self.rest_h = np.vstack([part.rest_h for part in parts])
        self.weights = np.vstack([part.weights for part in parts])
        self.owner = np.concatenate([part.owner for part in parts])
        self.source = np.repeat(np.arange(len(parts), dtype=np.int16), [part.count for part in parts])
        bones = [np.asarray(pack.skin_mats).shape[1] for pack in self.packs]
        offsets = np.cumsum([0] + bones[:-1])
        self.joints = np.vstack([part.joints + off for part, off in zip(parts, offsets)])
        self._posed = OrderedDict()
        self._reach = {}
        self._outlines = OrderedDict()

    def frames_of(self, frame):
        """Each pack's frame for the body's `frame`: the same clip and step in its own ranges."""
        body = self.packs[0]
        clip = next((name for name, (lo, hi) in body.ranges.items() if lo <= frame <= hi), None)
        out = [frame]
        for pack in self.packs[1:]:
            if clip is None or clip not in pack.ranges:
                out.append(frame)
            else:
                lo, hi = pack.ranges[clip]
                out.append(min(lo + frame - body.ranges[clip][0], hi))
        return out

    def _mats(self, frame):
        return np.concatenate([np.asarray(pack.skin_mats[f], dtype=np.float64)
                               for pack, f in zip(self.packs, self.frames_of(frame))])


def worn_cloud(body_pack, pieces):
    """The one cloud of `body_pack` wearing `pieces`: (name, pack) pairs; just the body's without any."""
    if not pieces:
        return cloud(body_pack)
    key = (body_pack.name,) + tuple(name for name, _ in pieces)
    found = _CLOUDS.get(key)
    if found is None:
        found = WornCloud(body_pack, pieces)
        _CLOUDS[key] = found
    return found
