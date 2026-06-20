"""Stage B2: proper server-side obstacle collision.

The server validates each broadcast position against the map's obstacles using
the REAL game QuadTree (built from geometry uploaded at join) and the SHARED
`collision_core` push-out -- the same rect math `Entity` runs. Covers: the
shared math (conformance to the original formula), the quadtree-backed server
resolve, and an end-to-end check over real sockets.
"""

import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pygame  # noqa: E402

import collision_core  # noqa: E402
from QuadTree import QuadTree, QuadTreeManager  # noqa: E402
from hashRect import HashableRect  # noqa: E402
from common import GameState, ServerPlayerState, _OVERLAP_TOLERANCE  # noqa: E402
from obstacle_mask import is_irregular, pack_mask, unpack_mask  # noqa: E402
from network import MultiplayerClient, MSG_PLAYER_JOINED, MSG_STATE_UPDATE  # noqa: E402
from server import GameServer  # noqa: E402


def _index(obstacles, w=4000, h=4000):
    items = [HashableRect(pygame.Rect(int(x), int(y), int(ww), int(hh)), _id=i)
             for i, (x, y, ww, hh) in enumerate(obstacles)]
    return QuadTree(items=items, depth=8, bounding_rect=pygame.Rect(0, 0, w, h),
                    manager=QuadTreeManager())


def _player(x, y, w=40.0, h=40.0):
    return ServerPlayerState(player_id="p", character="c", x=x, y=y, hitbox_w=w, hitbox_h=h)


def _max_overlap(p, obstacles):
    """Deepest min-axis overlap of the player's hitbox with any obstacle."""
    left, right = p.x - p.hitbox_w / 2, p.x + p.hitbox_w / 2
    top, bottom = p.y - p.hitbox_h / 2, p.y + p.hitbox_h / 2
    worst = 0.0
    for ox, oy, ow, oh in obstacles:
        ax = min(right, ox + ow) - max(left, ox)
        ay = min(bottom, oy + oh) - max(top, oy)
        if ax > 0 and ay > 0:
            worst = max(worst, min(ax, ay))
    return worst


# -- shared math conformance (client formula == collision_core) ---------------

def _reference_pushout(rect, obstacles, max_push, base=1.0):
    """Independent re-impl of Entity._resolve_obstacle_collisions' rect math."""
    tdx = tdy = 0.0
    max_pen = 0.0
    for o in obstacles:
        px = max(0, rect.right - o.left, o.right - rect.left)
        py = max(0, rect.bottom - o.top, o.bottom - rect.top)
        pen = math.sqrt(px ** 2 + py ** 2) ** 1.5
        ang = math.atan2(o.centery - rect.centery, o.centerx - rect.centerx) + math.pi
        tdx += math.cos(ang)
        tdy += math.sin(ang)
        max_pen = max(max_pen, pen)
    mag = math.sqrt(tdx ** 2 + tdy ** 2)
    if mag > 0:
        tdx /= mag
        tdy /= mag
    scaled = min(base + max_pen, max_push)
    return scaled * tdx, scaled * tdy


def test_collision_core_matches_original_formula():
    rect = pygame.Rect(100, 100, 40, 40)
    obstacles = [pygame.Rect(110, 90, 40, 40), pygame.Rect(80, 130, 30, 30)]
    for max_push in (4.0, 8.0, 1000.0):
        got = collision_core.obstacle_pushout(rect, obstacles, max_push)
        ref = _reference_pushout(rect, obstacles, max_push)
        assert got == pytest.approx(ref), f"max_push={max_push}"


def test_entity_rect_collision_unchanged_by_refactor():
    # Singleplayer regression: the refactored Entity._resolve_obstacle_collisions
    # rect path (self_mask=None) must apply exactly the shared push-out -- i.e.
    # the same displacement as the original inline formula.
    import logging
    from types import SimpleNamespace
    from Entity import Entity

    self_rect = pygame.Rect(100, 100, 40, 40)
    self_hitbox = pygame.Rect(100, 100, 40, 40)
    obstacles = [SimpleNamespace(rect=pygame.Rect(110, 90, 40, 40), mask=None),
                 SimpleNamespace(rect=pygame.Rect(80, 130, 30, 30), mask=None)]
    speed = 7
    Entity._resolve_obstacle_collisions(
        SimpleNamespace(), obstacles, self_rect, self_hitbox, None,
        self_rect.centerx, self_rect.centery, speed,
        logging.getLogger("game.collision.mask"),
    )
    exp_dx, exp_dy = _reference_pushout(self_rect, [o.rect for o in obstacles], speed)
    assert self_hitbox.left == pytest.approx(100 + exp_dx, abs=1.5)
    assert self_hitbox.top == pytest.approx(100 + exp_dy, abs=1.5)


# -- server resolve via the real quadtree + shared push-out -------------------

def test_resolve_pushes_player_out_of_wall():
    obstacles = [(100, 80, 40, 40)]
    p = _player(130, 100)
    p.resolve_obstacle_collision(_index(obstacles))
    assert _max_overlap(p, obstacles) <= _OVERLAP_TOLERANCE + 1.0


def test_resolve_no_op_when_clear():
    p = _player(800, 800)
    p.resolve_obstacle_collision(_index([(100, 80, 40, 40)]))
    assert (p.x, p.y) == (800, 800)


def test_resolve_invariant_single_obstacle_sweep():
    wall = [(200, 200, 80, 80)]
    idx = _index(wall)
    for sx in range(170, 310, 11):
        for sy in range(170, 310, 11):
            p = _player(sx, sy, 30, 30)
            p.resolve_obstacle_collision(idx)
            assert _max_overlap(p, wall) <= _OVERLAP_TOLERANCE + 1.0, f"({sx},{sy})->({p.x},{p.y})"


def test_resolve_invariant_perpendicular_corner():
    walls = [(0, 200, 800, 24), (200, 0, 24, 800)]
    idx = _index(walls)
    for sx in range(208, 280, 9):
        for sy in range(208, 280, 9):
            p = _player(sx, sy, 30, 30)
            p.resolve_obstacle_collision(idx)
            assert _max_overlap(p, walls) <= _OVERLAP_TOLERANCE + 1.0, f"({sx},{sy})->({p.x},{p.y})"


def test_tolerance_skips_a_graze():
    # Overlap of ~1px (<= tolerance) must NOT move the player.
    wall = [(100, 100, 40, 40)]            # x:100-140, y:100-160
    p = _player(80.5, 130, 40, 40)         # x:60.5-100.5 -> 0.5px into the wall
    p.resolve_obstacle_collision(_index(wall))
    assert p.x == 80.5 and p.y == 130


def test_disabled_when_no_hitbox_size():
    p = ServerPlayerState(player_id="p", character="c", x=130, y=100)  # hitbox 0
    p.apply_update(130, 100, 1.0, 0.0, False, _index([(100, 80, 40, 40)]))
    assert (p.x, p.y) == (130, 100)


def test_apply_update_validates_and_keeps_status():
    p = _player(130, 100)
    p.apply_update(130, 100, 1.0, 0.0, False, _index([(100, 80, 40, 40)]))
    assert _max_overlap(p, [(100, 80, 40, 40)]) <= _OVERLAP_TOLERANCE + 1.0
    assert p.status == "right"


# -- integration: real server builds a quadtree and corrects in-wall reports --

@pytest.fixture
def server():
    srv = GameServer(host="127.0.0.1", port=0)
    port = srv.listen_socket.getsockname()[1]
    threading.Thread(target=srv.run, daemon=True).start()
    yield srv, port


def _wait_for(client, msg_type, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in client.poll():
            if m["type"] == msg_type:
                return m
        time.sleep(0.01)
    raise AssertionError(f"never received {msg_type}")


def test_server_builds_quadtree_and_corrects_in_wall_report(server):
    srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0,
                    hitbox_w=40.0, hitbox_h=40.0, obstacles=[[100, 80, 40, 40]],
                    map_width=1000, map_height=1000)
    _wait_for(alice, MSG_PLAYER_JOINED)
    assert srv.game_state.obstacle_quad_tree is not None  # quadtree was built

    alice.send_state(130.0, 100.0, 1.0, 0.0, False)  # inside the wall

    deadline = time.monotonic() + 5.0
    corrected = None
    while time.monotonic() < deadline:
        for m in alice.poll():
            if m["type"] == MSG_STATE_UPDATE and "alice" in m["players"]:
                snap = m["players"]["alice"]
                if (snap["x"], snap["y"]) != (130.0, 100.0):
                    corrected = snap
                    break
        if corrected:
            break
        time.sleep(0.01)

    assert corrected is not None, "server never corrected the in-wall position"
    # corrected position is clear of the wall
    assert _max_overlap(_player(corrected["x"], corrected["y"]), [(100, 80, 40, 40)]) <= _OVERLAP_TOLERANCE + 1.0
    alice.close()


def test_clear_position_passes_through_unchanged(server):
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0,
                    hitbox_w=40.0, hitbox_h=40.0, obstacles=[[100, 80, 40, 40]],
                    map_width=1000, map_height=1000)
    _wait_for(alice, MSG_PLAYER_JOINED)
    alice.send_state(700.0, 700.0, 1.0, 0.0, False)

    deadline = time.monotonic() + 5.0
    seen = None
    while time.monotonic() < deadline:
        for m in alice.poll():
            if m["type"] == MSG_STATE_UPDATE and m["players"].get("alice", {}).get("x") == 700.0:
                seen = m["players"]["alice"]
                break
        if seen:
            break
        time.sleep(0.01)

    assert seen is not None and (seen["x"], seen["y"]) == (700.0, 700.0)
    alice.close()


# -- Stage B2.5: irregular obstacles ship a pixel mask; the server gates on the
#    silhouette so a position the client legitimately allowed in the obstacle's
#    transparent area is NOT falsely corrected (which the other client sees pop) --

def _left_half_mask(w=40, h=40, solid_cols=20):
    """A pygame mask whose left `solid_cols` columns are solid, rest transparent
    (an irregular obstacle, e.g. a tree trunk)."""
    mask = pygame.mask.Mask((w, h))
    for x in range(solid_cols):
        for y in range(h):
            mask.set_at((x, y), 1)
    return mask


def _left_half_grid(w=40, h=40, solid_cols=20):
    """The same silhouette as a numpy grid -- what the server stores after
    unpacking (so tests build server obstacles the way build_obstacle_index does)."""
    grid = numpy.zeros((h, w), dtype=bool)
    grid[:, :solid_cols] = True
    return grid


def _index_one(rect, grid=None, w=4000, h=4000):
    item = HashableRect(pygame.Rect(*rect), _id=0, mask=grid)
    return QuadTree(items=[item], depth=8, bounding_rect=pygame.Rect(0, 0, w, h),
                    manager=QuadTreeManager())


def test_obstacle_mask_round_trips_exactly():
    src = _left_half_mask(37, 53, solid_cols=11)
    grid = unpack_mask(37, 53, pack_mask(src))           # (h, w) numpy bool grid
    assert grid.shape == (53, 37)
    assert int(grid.sum()) == src.count()
    assert all(bool(grid[y, x]) == bool(src.get_at((x, y)))
               for y in range(53) for x in range(37))


def test_is_irregular_only_for_holed_same_size_masks():
    assert is_irregular(_left_half_mask(40, 40), 40, 40) is True
    assert is_irregular(pygame.mask.Mask((40, 40), fill=True), 40, 40) is False  # solid tile
    assert is_irregular(None, 40, 40) is False                                   # no mask
    assert is_irregular(_left_half_mask(40, 40), 30, 30) is False                # size mismatch


def test_resolve_skips_transparent_area_of_masked_obstacle():
    # Obstacle rect 100-140; only its LEFT half (x:100-120) is solid. A player
    # whose hitbox overlaps the bounding rect but only the transparent RIGHT half
    # must NOT be pushed -- the client allowed it there, so the server must agree.
    idx = _index_one((100, 100, 40, 40), grid=_left_half_grid())
    p = _player(150, 120)                     # rect x:130-170 -> overlaps only x>=120 (transparent)
    p.resolve_obstacle_collision(idx)
    assert (p.x, p.y) == (150, 120)


def test_rect_only_obstacle_would_have_false_corrected_same_spot():
    # The same geometry WITHOUT a mask DOES move the player -- proving the mask
    # gate (not a lucky no-overlap) is what prevents the false correction above.
    idx = _index_one((100, 100, 40, 40), grid=None)
    p = _player(150, 120)
    p.resolve_obstacle_collision(idx)
    assert (p.x, p.y) != (150, 120)


def test_resolve_pushes_out_of_solid_part_of_masked_obstacle():
    idx = _index_one((100, 100, 40, 40), grid=_left_half_grid())
    p = _player(110, 120)                     # rect x:90-130 -> overlaps solid x:100-120
    p.resolve_obstacle_collision(idx)
    # cleared of the SOLID half (x < 120); player hitbox right edge now <= ~120
    assert p.x + p.hitbox_w / 2 <= 120 + _OVERLAP_TOLERANCE + 1.0


def test_build_obstacle_index_unpacks_a_masked_entry():
    gs = GameState()
    packed = pack_mask(_left_half_mask(40, 40))
    gs.build_obstacle_index([(100, 100, 40, 40, packed), (200, 200, 40, 40)], 1000, 1000)
    items = list(gs.obstacle_quad_tree.hit(HashableRect(pygame.Rect(0, 0, 4000, 4000), _id=-1)))
    grids = {item.rect.topleft: item.mask for item in items}
    assert grids[(100, 100)] is not None and int(grids[(100, 100)].sum()) == 20 * 40
    assert grids[(200, 200)] is None         # plain rect entry -> no mask


def test_masked_obstacle_e2e_transparent_passes_through(server):
    srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    packed = pack_mask(_left_half_mask(40, 40))
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0,
                    hitbox_w=40.0, hitbox_h=40.0,
                    obstacles=[[100, 100, 40, 40, packed]],
                    map_width=1000, map_height=1000)
    _wait_for(alice, MSG_PLAYER_JOINED)

    alice.send_state(150.0, 120.0, 1.0, 0.0, False)  # in the transparent half

    deadline = time.monotonic() + 5.0
    seen = None
    while time.monotonic() < deadline and seen is None:
        for m in alice.poll():
            if m["type"] == MSG_STATE_UPDATE and m["players"].get("alice", {}).get("x") == 150.0:
                seen = m["players"]["alice"]
                break
        time.sleep(0.01)

    assert seen is not None and (seen["x"], seen["y"]) == (150.0, 120.0), \
        "server false-corrected a position in the obstacle's transparent area"
    alice.close()
