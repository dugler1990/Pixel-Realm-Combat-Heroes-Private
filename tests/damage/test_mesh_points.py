"""mesh_points: a mesh body's hit outline from its real vertices (damage chunk 4b)."""
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

import mesh_points  # noqa: E402
from mesh_boss import MeshBossPack  # noqa: E402
from Settings import VIEW_ELEVATION_DEG  # noqa: E402

PACK = MeshBossPack.get("barb")
SCALE = 100.0 / PACK.height_units


@pytest.fixture(scope="module")
def cloud():
    return mesh_points.PointCloud(PACK)


def _screen(cloud, frame, yaw):
    p = cloud.posed(frame)
    y = math.radians(yaw)
    c, s = math.cos(y), math.sin(y)
    e = math.radians(VIEW_ELEVATION_DEG)
    gy = -(p[:, 0] * s + p[:, 1] * c) * SCALE
    gz = p[:, 2] * SCALE
    sx = np.floor((p[:, 0] * c - p[:, 1] * s) * SCALE).astype(int)
    sy = np.floor(gy * math.sin(e) - gz * math.cos(e)).astype(int)
    return sx, sy, gy * math.cos(e) + gz * math.sin(e)


def test_a_few_thousand_points_spread_over_the_body(cloud):
    assert 1000 < cloud.count <= mesh_points.TARGET_POINTS
    assert set(cloud.owner.tolist()) >= {c["bone"] for c in PACK.capsules}     # every bone has points


@pytest.mark.parametrize("frame, yaw", [(0, 0), (60, 150), (200, 270), (295, 150)])
def test_every_point_is_in_its_outline_and_the_nearest_wins(cloud, frame, yaw):
    o = cloud.outline(frame, yaw, SCALE)
    sx, sy, depth = _screen(cloud, frame, yaw)
    for i in range(0, cloud.count, 7):
        x, y = sx[i] - o.dx, sy[i] - o.dy
        assert o.mask.get_at((x, y))
        shown = o.labels[y, x]
        assert depth[shown] >= depth[i] - 1e-9          # what shows there is no farther than this point


def test_point_at_finds_the_label_or_a_neighbour(cloud):
    o = cloud.outline(0, 0, SCALE)
    ys, xs = np.nonzero(o.labels >= 0)
    x, y = int(xs[0]), int(ys[0])
    assert o.point_at(x + o.dx + 0.5, y + o.dy + 0.5) == int(o.labels[y, x])
    assert o.point_at(o.dx - 50, o.dy - 50) is None


def test_reach_box_holds_the_outline_at_every_facing(cloud):
    for frame in (0, 100, 295):
        dx, dy, w, h = cloud.reach_box(frame, SCALE)
        box = pygame.Rect(math.floor(dx), math.floor(dy), math.ceil(w) + 1, math.ceil(h) + 1)
        for yaw in range(0, 360, 30):
            o = cloud.outline(frame, yaw, SCALE)
            rects = o.mask.get_bounding_rects()
            pixels = rects[0].unionall(rects[1:]).move(o.dx, o.dy)
            assert box.contains(pixels), (frame, yaw)


def test_outlines_are_kept(cloud):
    assert cloud.outline(10, 45, SCALE) is cloud.outline(10, 45, SCALE)
    assert cloud.outline(10, 45, SCALE) is not cloud.outline(11, 45, SCALE)
