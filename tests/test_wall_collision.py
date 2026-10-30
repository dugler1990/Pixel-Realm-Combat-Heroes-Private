"""Walls block the feet, and the client and the server use the same code on the same walls.

Covers the footprint (a ground ellipse at the drawn feet), `collision_core.blocked_step`
(stop flush, slide, turned tries for angled walls, already-inside, masked obstacles),
`Entity.move` against a SAM-like polygon wall, and the server's `accept_report`: an honest
client walking along walls is never corrected, a report inside a wall is dropped, both
directly and over real sockets.
"""

import math
import os
import sys
import threading
import time
from pathlib import Path

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
from Entity import Entity  # noqa: E402
from Settings import VIEW_ELEVATION_DEG  # noqa: E402
from common import ServerPlayerState  # noqa: E402
from network import MultiplayerClient, MSG_PLAYER_JOINED, MSG_STATE_UPDATE  # noqa: E402
from server import GameServer  # noqa: E402

# A pyramid wall piece exactly as SAM wrote it to map.tmx (great_pyramid_wall_19): a
# ragged diagonal edge from (116, 0) down to (0, 108), solid below-right of it.
PYRAMID_WALL_19 = [
    (116, 0), (113, 3), (111, 3), (111, 5), (107, 7), (78, 37), (75, 37), (56, 57),
    (49, 59), (49, 61), (43, 65), (42, 69), (37, 71), (36, 74), (29, 79), (28, 83),
    (16, 92), (15, 95), (0, 108), (0, 145), (116, 145),
]


# -- walls ---------------------------------------------------------------------

def _tree(items, w=4000, h=4000):
    return QuadTree(items=items, depth=8, bounding_rect=pygame.Rect(0, 0, w, h),
                    manager=QuadTreeManager())


def _solid(x, y, w, h, _id=0):
    """A wall with no mask: the whole rect is solid."""
    return HashableRect(pygame.Rect(x, y, w, h), _id=_id)


def _masked(rect, mask, _id=0):
    return HashableRect(pygame.Rect(rect), _id=_id, mask=mask)


def _polygon(points, origin, scale=1, _id=0):
    """A wall from polygon points, the way the TMX loader turns SAM polygons into masks."""
    pts = [(int(x * scale), int(y * scale)) for x, y in points]
    w = max(x for x, _ in pts) + 1
    h = max(y for _, y in pts) + 1
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.polygon(surf, (255, 255, 255, 255), pts)
    return _masked((origin[0], origin[1], w, h), pygame.mask.from_surface(surf), _id)


def _half_plane(angle_deg, origin=(200, 200), size=600, _id=0):
    """Solid below a line through `origin` that descends to the right at `angle_deg`."""
    ox, oy = origin
    rect = pygame.Rect(ox - size // 2, oy - size // 2, size, size)
    mask = pygame.Mask(rect.size)
    slope = math.tan(math.radians(angle_deg))
    for x in range(size):
        line_y = (oy - rect.y) + (x - (ox - rect.x)) * slope
        for y in range(max(0, int(math.ceil(line_y))), size):
            mask.set_at((x, y), 1)
    return _masked(rect, mask, _id)


FOOT = (0, 0, 24, 17)  # a footprint of R = 12 at the 45° camera: 24 x round(24 * sin 45°)


def _foot_at(x, y):
    return collision_core.foot_rect(pygame.Rect(x, y, 1, 1), FOOT)


def _walk(foot, step, tree, frames):
    """Push the footprint by `step` every frame; return its path. Never inside a wall."""
    path = [foot.topleft]
    for _ in range(frames):
        took = collision_core.blocked_step(foot, step[0], step[1], tree)
        foot = foot.move(took)
        assert not collision_core.hits_wall(foot, tree), f"inside a wall at {foot}"
        path.append(foot.topleft)
    return foot, path


# -- the footprint ---------------------------------------------------------------

class _Walker(Entity):
    """A minimal real Entity: a solid 40x60 sprite, feet at its bottom edge."""

    def __init__(self, x, y, radius=12):
        super().__init__([])
        self.combat_config = {"collision_ground_radius_px": radius}
        self.image = pygame.Surface((40, 60), pygame.SRCALPHA)
        self.image.fill((200, 50, 50, 255))
        self.mask = pygame.mask.from_surface(self.image)
        self.rect = self.image.get_rect(topleft=(x, y))
        self.hitbox = self.rect.inflate(0, -10)
        self.status = "idle"
        self.sprite_type = "player"
        self.plant_sprite_on_hitbox()


class _NoEntities:
    def hit(self, _query):
        return set()


def _step_entity(entity, direction, tree, frames, speed=6):
    """Drive Entity.move; return the hitbox centres it reported each frame."""
    reports = []
    for _ in range(frames):
        entity.direction = pygame.math.Vector2(direction)
        entity.move(speed, tree, _NoEntities())
        foot = collision_core.foot_rect(entity.hitbox, entity.wall_foot())
        assert not collision_core.hits_wall(foot, tree), f"feet inside a wall at {foot}"
        reports.append(entity.hitbox.center)
    return reports


def test_footprint_is_a_ground_ellipse_at_the_drawn_feet():
    walker = _Walker(100, 100, radius=12)
    dx, dy, w, h = walker.wall_foot()
    assert (w, h) == (24, round(24 * math.sin(math.radians(VIEW_ELEVATION_DEG))))
    feet_x, feet_y = walker.hitbox.midbottom[0], walker.hitbox.midbottom[1] + walker.anchor_offset
    foot = collision_core.foot_rect(walker.hitbox, walker.wall_foot())
    assert foot.centerx == feet_x
    assert abs(foot.centery - feet_y) <= 1


def test_a_wall_your_head_overlaps_on_screen_does_not_block_and_your_feet_stop_at_its_base():
    walker = _Walker(100, 300)                            # sprite y: 300..360, feet at 360
    wall = _solid(60, 250, 120, 80)                       # y: 250..330 -- overlaps the head
    tree = _tree([wall])
    assert walker.rect.colliderect(wall.rect)
    # Sideways, with the head over the wall on screen: not blocked.
    start_x = walker.hitbox.x
    _step_entity(walker, (1, 0), tree, 5)
    assert walker.hitbox.x > start_x
    # Up: the feet stop flush at the wall's base.
    _step_entity(walker, (0, -1), tree, 40)
    foot = collision_core.foot_rect(walker.hitbox, walker.wall_foot())
    assert not collision_core.hits_wall(foot, tree)
    assert collision_core.hits_wall(foot.move(0, -1), tree)


def test_wall_foot_stays_the_same_across_animation_frames():
    walker = _Walker(100, 100)
    before = walker.wall_foot()
    # A wider attack frame with a different mask must not change what blocks walls.
    walker.image = pygame.Surface((90, 60), pygame.SRCALPHA)
    walker.image.fill((200, 50, 50, 255))
    walker.mask = pygame.mask.from_surface(walker.image)
    walker.plant_sprite_on_hitbox()
    assert walker.wall_foot() == before


# -- blocked_step ------------------------------------------------------------------

def test_stops_flush_with_no_gap_and_no_overlap():
    tree = _tree([_solid(100, 0, 50, 400)])
    foot = _foot_at(60, 100)                     # right edge at 84, 16 px from the wall
    took = collision_core.blocked_step(foot, 30, 0, tree)
    foot = foot.move(took)
    assert foot.right == 100                     # flush
    assert not collision_core.hits_wall(foot, tree)
    assert collision_core.hits_wall(foot.move(1, 0), tree)


def test_slides_along_horizontal_and_vertical_walls():
    floor = _tree([_solid(0, 200, 400, 50)])
    foot = _foot_at(100, 200 - FOOT[3])          # standing flush on the floor
    assert collision_core.blocked_step(foot, 5, 5, floor) == (5, 0)

    side = _tree([_solid(200, 0, 50, 400)])
    foot = _foot_at(200 - FOOT[2], 100)          # flush against the wall's left face
    assert collision_core.blocked_step(foot, 5, 5, side) == (0, 5)


@pytest.mark.parametrize("angle", [35, 45, 60])
def test_pushing_straight_into_an_angled_wall_slides_along_it(angle):
    # Push straight down into a wall that descends to the right. 35° is a 45° ground wall
    # as the 45° camera draws it: 55° off the push, which one ±45° try could not slide on.
    tree = _tree([_half_plane(angle, origin=(300, 300))])
    foot = _foot_at(288, 220)                    # centred over the line's origin, above it
    assert not collision_core.hits_wall(foot, tree)
    foot, _ = _walk(foot, (0, 6), tree, 10)      # reach the wall
    start = foot.topleft
    foot, path = _walk(foot, (0, 6), tree, 40)
    progress = foot.x - start[0]
    assert progress > 40, f"{angle}° wall: slid only {progress}px in 40 frames"


@pytest.mark.parametrize("step", [(6, 0), (2, 0), (0, 6), (0, 2)])
def test_pushing_square_into_a_flat_wall_stops_without_drifting(step):
    tree = _tree([_solid(200, 0, 50, 400), _solid(0, 300, 400, 50, _id=1)])
    foot = _foot_at(200 - FOOT[2], 100) if step[0] else _foot_at(100, 300 - FOOT[3])
    for _ in range(20):
        assert collision_core.blocked_step(foot, step[0], step[1], tree) == (0, 0)


def test_a_body_already_inside_moves_freely_until_clear():
    tree = _tree([_solid(100, 100, 60, 60)])
    foot = _foot_at(110, 110)
    assert collision_core.hits_wall(foot, tree)
    assert collision_core.blocked_step(foot, -7, 3, tree) == (-7, 3)


def test_the_transparent_part_of_a_masked_obstacle_does_not_block():
    mask = pygame.Mask((100, 100))
    for x in range(50):                           # only the left half is solid
        for y in range(100):
            mask.set_at((x, y), 1)
    tree = _tree([_masked((100, 100, 100, 100), mask)])
    foot = _foot_at(160, 140)                     # inside the rect, in the transparent half
    assert not collision_core.hits_wall(foot, tree)
    took = collision_core.blocked_step(foot, -30, 0, tree)
    assert foot.move(took).left == 150            # stops flush at the solid half


def test_a_query_never_shares_an_id_with_the_static_walls():
    # Every static obstacle carries _id -1, and QuadTree.hit skips items with the query's id.
    tree = _tree([_solid(100, 0, 50, 400, _id=-1)])
    assert collision_core.hits_wall(_foot_at(110, 100), tree)


# -- Entity.move ---------------------------------------------------------------------

@pytest.mark.parametrize("scale", [1, 3])
def test_entity_slides_along_a_sam_polygon_wall_without_overlapping(scale):
    # Scale 1 is the wall exactly as SAM wrote it; its edge has 3-4 px jogs that only the
    # sidestep gets past. Scale 3 makes the same jogs 12 px.
    wall = _polygon(PYRAMID_WALL_19, origin=(400, 300), scale=scale)
    tree = _tree([wall])
    walker = _Walker(250, 300 + 100 * scale - 60)  # feet level with the diagonal edge
    reports = _step_entity(walker, (1, 0), tree, 150)
    # Pushing right into an edge that rises to the right: it slides up along the stone.
    ys = [y for _x, y in reports]
    assert min(ys) < ys[0] - 60, f"barely slid: y {ys[0]} -> {min(ys)}"


def test_entity_velocity_is_cut_to_the_step_the_wall_allowed():
    tree = _tree([_solid(300, 0, 50, 1000)])
    walker = _Walker(200, 300)
    _step_entity(walker, (1, 0), tree, 40)
    assert walker.velocity.x == 0.0                # pressed flush: no stored push, no bounce


def test_a_stuck_entity_moves_again_once_its_wall_is_removed():
    # A stuck step is remembered and skips the checks; changing the walls must forget it.
    tree = _tree([])
    wall = _solid(1990, 1900, 20, 200, _id=-10000)  # spans the tree's centre: one node holds it
    tree.insert(wall, alive=True)
    walker = _Walker(1900, 1900)
    _step_entity(walker, (1, 0), tree, 30)
    assert walker.step_against_walls(6, 0, tree) == (0, 0)
    assert walker.step_against_walls(6, 0, tree) == (0, 0)
    assert walker._stuck_at is not None
    tree.manager.remove(wall._id)
    assert walker.step_against_walls(6, 0, tree) == (6, 0)


# -- the server -------------------------------------------------------------------------

def _server_player(entity):
    return ServerPlayerState(
        player_id="p", character="c",
        x=float(entity.hitbox.centerx), y=float(entity.hitbox.centery),
        hitbox_w=float(entity.hitbox.width), hitbox_h=float(entity.hitbox.height),
        wall_foot=entity.wall_foot(),
    )


def test_client_equals_server_an_honest_walk_along_walls_is_never_corrected():
    tree = _tree([
        _polygon(PYRAMID_WALL_19, origin=(400, 300), scale=3, _id=0),
        _solid(150, 700, 600, 40, _id=1),
        _solid(100, 200, 40, 600, _id=2),
    ])
    walker = _Walker(250, 520)
    player = _server_player(walker)
    reports = []
    for direction in [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]:
        reports += _step_entity(walker, direction, tree, 25)
    for cx, cy in reports:
        player.apply_update(cx, cy, 0.0, 0.0, False)
        assert player.accept_report(tree) is False
        assert (player.x, player.y) == (cx, cy)


def test_report_inside_a_wall_is_dropped_and_the_player_stays_at_the_last_accepted():
    tree = _tree([_solid(300, 0, 100, 1000)])
    walker = _Walker(200, 300)
    player = _server_player(walker)
    last = (player.x, player.y)
    player.apply_update(last[0] + 150, last[1], 1.0, 0.0, False)   # deep in the wall
    assert player.accept_report(tree) is True
    assert (player.x, player.y) == last
    assert player.reported_x is None                                # consumed, not retried


def test_an_unchecked_report_is_never_what_the_server_holds():
    walker = _Walker(200, 300)
    player = _server_player(walker)
    start = (player.x, player.y)
    player.apply_update(start[0] + 5, start[1], 1.0, 0.0, False)
    assert (player.x, player.y) == start                            # waits for accept_report
    player.accept_report(_tree([]))
    assert (player.x, player.y) == (start[0] + 5, start[1])


def test_no_footprint_means_the_report_is_relayed_unchecked():
    player = ServerPlayerState(player_id="p", character="c", x=0.0, y=0.0)
    player.apply_update(130.0, 100.0, 1.0, 0.0, False)
    assert player.accept_report(_tree([_solid(100, 80, 60, 60)])) is False
    assert (player.x, player.y) == (130.0, 100.0)
    assert player.status == "right"


# -- end to end, over real sockets --------------------------------------------------------

WALL = _solid(300, 0, 100, 1000)


@pytest.fixture
def server():
    srv = GameServer(host="127.0.0.1", port=0, run_world_sim=False)
    srv.game_state.obstacle_quad_tree = _tree([WALL])   # what _build_server_level sets
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


def _join(port, walker):
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", walker.hitbox.centerx, walker.hitbox.centery,
                    hitbox_w=walker.hitbox.width, hitbox_h=walker.hitbox.height,
                    wall_foot=walker.wall_foot())
    _wait_for(alice, MSG_PLAYER_JOINED)
    return alice


def _broadcast_position(client, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in client.poll():
            if m["type"] == MSG_STATE_UPDATE and "alice" in m["players"]:
                snap = m["players"]["alice"]
                if predicate((snap["x"], snap["y"])):
                    return snap["x"], snap["y"]
        time.sleep(0.01)
    return None


def test_e2e_clear_report_passes_through_unchanged(server):
    _srv, port = server
    walker = _Walker(100, 300)
    alice = _join(port, walker)
    target = (float(walker.hitbox.centerx + 20), float(walker.hitbox.centery))
    alice.send_state(target[0], target[1], 1.0, 0.0, False)
    assert _broadcast_position(alice, lambda xy: xy == target) == target
    alice.close()


def test_e2e_report_inside_a_wall_is_dropped(server):
    srv, port = server
    walker = _Walker(200, 300)
    alice = _join(port, walker)
    joined = (float(walker.hitbox.centerx), float(walker.hitbox.centery))
    inside = (joined[0] + 150, joined[1])
    alice.send_state(inside[0], inside[1], 1.0, 0.0, False)
    # Wait until the sim thread has checked it: the update arrived and its report is consumed.
    deadline = time.monotonic() + 5.0
    player = None
    while time.monotonic() < deadline:
        player = srv.game_state.players.get("alice")
        if player is not None and player.direction_x == 1.0 and player.reported_x is None:
            break
        time.sleep(0.01)
    assert player is not None and player.reported_x is None, "the report was never checked"
    assert (player.x, player.y) == joined
    assert _broadcast_position(alice, lambda xy: xy == inside, timeout=0.5) is None
    alice.close()
