"""How long walls take: a crowd on the real pyramid walls, the worst step, the server's check.

The walls are the great pyramid's SAM pieces from sunspine_7x6_play's map.tmx, built by the
game loader's own mask code (loading the whole level takes ~35 s; this takes well under one).
The crowd steps real Entities the way the game does, so a remembered stuck step counts; the
worst-step test calls blocked_step straight, with nothing remembered. Budgets are fractions of
a 60 fps frame, which is also the server's tick. Run with -s to see the numbers.
"""

import math
import os
import random
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pygame  # noqa: E402
import pytmx  # noqa: E402

import collision_core  # noqa: E402
from QuadTree import QuadTree, QuadTreeManager  # noqa: E402
from hashRect import HashableRect  # noqa: E402
from Entity import Entity  # noqa: E402
from Settings import TILESIZE  # noqa: E402
from tmx_layout_manager import LayoutManager  # noqa: E402
from common import ServerPlayerState  # noqa: E402

PYRAMID_MAP = REPO_ROOT / "levels" / "Frostreach" / "sunspine_7x6_play" / "map.tmx"

FRAME_S = 1.0 / 60
CROWD = 100
SPEED = 6               # px a frame
FOOT = (0, 0, 24, 17)   # a footprint of R = 12 at the 45° camera, as in test_wall_collision


@pytest.fixture(scope="module")
def pyramid():
    """The pyramid's walls in a quad-tree as the game builds it, and its floor polygon."""
    tmx = pytmx.TiledMap(str(PYRAMID_MAP))
    loader = SimpleNamespace(tmxdata=tmx, TILESIZE=TILESIZE)
    scale = TILESIZE / tmx.tilewidth                      # 120 px map tiles, 150 px game tiles
    walls, floor = [], None
    for obj in tmx.objects:
        name = obj.name or ""
        if name.startswith("great_pyramid_wall"):
            rect, mask, _ = LayoutManager._mask_and_rect_for_tmx_shape(loader, obj)
            walls.append(HashableRect(rect, _id=-1, mask=mask))  # -1, as every static obstacle
        elif name == "great_pyramid_chamber":
            floor = [(p.x * scale, p.y * scale) for p in obj.points]
    if len(walls) < 30 or not floor:
        pytest.skip("this map.tmx doesn't have the pyramid's SAM walls and chamber yet")
    bounds = pygame.Rect(0, 0, tmx.width * TILESIZE, tmx.height * TILESIZE)
    tree = QuadTree(items=walls, depth=8, bounding_rect=bounds, manager=QuadTreeManager())
    return tree, floor


def _on_floor(floor, x, y):
    inside = False
    for (x1, y1), (x2, y2) in zip(floor, floor[-1:] + floor[:-1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _crowd(tree, floor, n, seed=7):
    """`n` footprints at clear spots on the pyramid floor, each with a fixed step a frame."""
    rng = random.Random(seed)
    xs, ys = [x for x, _ in floor], [y for _, y in floor]
    crowd = []
    while len(crowd) < n:
        x, y = rng.randint(int(min(xs)), int(max(xs))), rng.randint(int(min(ys)), int(max(ys)))
        foot = collision_core.foot_rect(pygame.Rect(x, y, 1, 1), FOOT)
        if not _on_floor(floor, x, y) or collision_core.hits_wall(foot, tree):
            continue
        heading = rng.uniform(0, 2 * math.pi)
        step = (int(round(SPEED * math.cos(heading))), int(round(SPEED * math.sin(heading))))
        crowd.append([foot, step])
    return crowd


class _Walker(Entity):
    """A minimal real Entity with a FOOT-sized footprint, as in test_wall_collision."""

    def __init__(self):
        super().__init__([])
        self.combat_config = {"collision_ground_radius_px": 12}
        self.image = pygame.Surface((40, 60), pygame.SRCALPHA)
        self.image.fill((200, 50, 50, 255))
        self.mask = pygame.mask.from_surface(self.image)
        self.rect = self.image.get_rect()
        self.hitbox = self.rect.inflate(0, -10)
        self.status = "idle"
        self.sprite_type = "player"
        self.plant_sprite_on_hitbox()


def _walkers(crowd):
    """The crowd as Entities with their feet on those footprints."""
    walkers = []
    for foot, step in crowd:
        walker = _Walker()
        now = collision_core.foot_rect(walker.hitbox, walker.wall_foot())
        walker.hitbox.move_ip(foot.x - now.x, foot.y - now.y)
        walkers.append((walker, step))
    return walkers


def _entity_frames(walkers, tree, frames):
    """Step every Entity once a frame as the game does; frame seconds, share of steps cut."""
    times, cut = [], 0
    for _ in range(frames):
        start = time.perf_counter()
        for walker, step in walkers:
            cut += walker.step_against_walls(step[0], step[1], tree) != step
        times.append(time.perf_counter() - start)
    return times, cut / (frames * len(walkers))


def _frames(crowd, tree, frames):
    """Step the footprints once a frame; each frame's seconds, and the share of steps cut."""
    times, cut = [], 0
    for _ in range(frames):
        start = time.perf_counter()
        for walker in crowd:
            foot, step = walker
            took = collision_core.blocked_step(foot, step[0], step[1], tree)
            walker[0] = foot.move(took)
            cut += took != tuple(step)
        times.append(time.perf_counter() - start)
    return times, cut / (frames * len(crowd))


def _report(label, times):
    ms = sorted(t * 1000 for t in times)
    print(f"\n{label}: median {statistics.median(ms):.2f} ms, "
          f"p95 {ms[int(0.95 * (len(ms) - 1))]:.2f} ms, max {ms[-1]:.2f} ms "
          f"(frame {FRAME_S * 1000:.1f} ms)")


def test_a_hundred_walkers_pressing_into_the_pyramid_walls_take_under_a_quarter_frame(pyramid):
    tree, floor = pyramid
    walkers = _walkers(_crowd(tree, floor, CROWD))
    _entity_frames(walkers, tree, 400)                     # walk until they reach the walls
    times, cut = _entity_frames(walkers, tree, 120)
    _report(f"{CROWD} walkers in the pyramid, {cut:.0%} of steps cut by a wall", times)
    assert cut > 0.2                                       # timing walls, not open floor
    assert statistics.median(times) < FRAME_S / 4


def test_a_hundred_walkers_stuck_square_on_a_wall_take_under_half_a_frame():
    """The most a step costs, nothing remembered: x blocked, every turned try and sidestep too."""
    wall = HashableRect(pygame.Rect(1000, 0, 200, 4000), _id=-1)
    tree = QuadTree(items=[wall], depth=8, bounding_rect=pygame.Rect(0, 0, 4000, 4000),
                    manager=QuadTreeManager())
    crowd = []
    for i in range(CROWD):
        foot = collision_core.foot_rect(pygame.Rect(0, 100 + 30 * i, 1, 1), FOOT)
        crowd.append([foot.move(wall.rect.left - foot.right, 0), (SPEED, 0)])
    times, cut = _frames(crowd, tree, 60)
    _report(f"{CROWD} walkers stuck square on a wall", times)
    assert cut == 1.0 and all(foot.right == wall.rect.left for foot, _ in crowd)
    assert statistics.median(times) < FRAME_S / 2


def _lagged(foot, step, tree, frames=20):
    """A player 20 frames short of the first wall on its heading, and a report inside that wall."""
    hitbox = pygame.Rect(foot.centerx - 20, foot.centery - 50, 40, 50)
    wall_foot = (foot.x - hitbox.x, foot.y - hitbox.y, foot.width, foot.height)
    heading = math.atan2(step[1], step[0])
    ux, uy = math.cos(heading), math.sin(heading)
    for d in range(SPEED, 3000, SPEED):
        report = hitbox.move(round(d * ux), round(d * uy))
        if collision_core.hits_wall(collision_core.foot_rect(report, wall_foot), tree):
            back = max(0, d - frames * SPEED)
            last = hitbox.move(round(back * ux), round(back * uy))
            player = ServerPlayerState(
                player_id="p", character="c", x=float(last.centerx), y=float(last.centery),
                hitbox_w=40.0, hitbox_h=50.0, wall_foot=wall_foot,
            )
            return player, last.center, report.center
    return None


def test_the_server_drops_sixteen_lagged_reports_in_a_wall_within_a_tenth_of_a_tick(pyramid):
    """Every player's report jumps 20 frames of walking, into a wall, and is dropped."""
    tree, floor = pyramid
    lagged = [_lagged(foot, step, tree) for foot, step in _crowd(tree, floor, 16, seed=11)]
    lagged = [entry for entry in lagged if entry is not None]
    assert len(lagged) >= 12

    times = []
    for _ in range(30):
        for player, last, report in lagged:
            player.x, player.y = last
            player.apply_update(report[0], report[1], 0.0, 0.0, False)
        start = time.perf_counter()
        dropped = [player.accept_report(tree) for player, _, _ in lagged]
        times.append(time.perf_counter() - start)
        assert all(dropped)
    _report(f"server: {len(lagged)} in-wall reports dropped in one tick", times)
    assert statistics.median(times) < FRAME_S / 10
