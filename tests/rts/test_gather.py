import pygame

from hashRect import HashableRect
from navigation.walk_grid import WalkGrid
from QuadTree import QuadTree, QuadTreeManager
from rts.categories import FOOD, MATERIAL
from rts.entities import DropoffBuilding, ResourceNode, RtsWorker
from rts.gather.controller import GatherController
from rts.registry import RtsWorldRegistry
from rts.resources import ResourceWallet
from rts.tmx_config import dropoff_config, resource_node_config


def _wall_grid_and_quad_tree():
    cols, rows, cell = 10, 6, 50
    blocked = [[False] * cols for _ in range(rows)]
    wall_col = 4
    gap_row = 0
    for row in range(rows):
        if row == gap_row:
            continue
        blocked[row][wall_col] = True
    grid = WalkGrid(blocked, cell, cols * cell, rows * cell)

    wall = pygame.sprite.Sprite()
    wall.rect = pygame.Rect(wall_col * cell, cell, cell, (rows - 1) * cell)
    items = [HashableRect(wall.rect)]
    quad = QuadTree(
        items=items,
        depth=4,
        bounding_rect=pygame.Rect(0, 0, cols * cell, rows * cell),
        manager=QuadTreeManager(),
    )
    return grid, quad, wall


def test_gather_assign_delivers_to_wallet():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "jungle_tribe", "worker_jungle")
    node_cfg = resource_node_config("fruit_grove", "jungle_tribe")
    node_cfg["gather_duration"] = 0.1
    node = ResourceNode((40, 0), [], node_cfg, registry)
    drop_cfg = dropoff_config("village_hearth", "jungle_tribe")
    dropoff = DropoffBuilding((0, 40), [], drop_cfg, registry)
    wallet = ResourceWallet()
    controller = GatherController(registry)

    controller.assign(worker, node, wallet)
    for _ in range(120):
        controller.update(0.05, obstacle_sprites=None, wallet=wallet)
    assert wallet.get(FOOD) >= 20


def test_gather_moves_when_worker_in_obstacle_group():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    obstacles = pygame.sprite.Group()
    registry = RtsWorldRegistry()
    worker = RtsWorker((200, 200), [obstacles], "eskimo", "worker_eskimo")
    node_cfg = resource_node_config("seal_hole", "eskimo")
    node_cfg["gather_duration"] = 0.1
    node = ResourceNode((80, 200), [], node_cfg, registry)
    obstacles.add(node)
    drop_cfg = dropoff_config("smoking_rack", "eskimo")
    dropoff = DropoffBuilding((200, 80), [], drop_cfg, registry)
    obstacles.add(dropoff)
    wallet = ResourceWallet()
    controller = GatherController(registry)
    start = pygame.math.Vector2(worker.rect.center)

    controller.assign(worker, node, wallet)
    for _ in range(200):
        controller.update(0.05, obstacles, wallet=wallet)
    assert worker.rect.center != tuple(start)
    assert wallet.get(FOOD) >= 20


def test_gather_paths_around_wall():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    grid, quad, wall = _wall_grid_and_quad_tree()
    obstacles = pygame.sprite.Group()
    obstacles.add(wall)

    registry = RtsWorldRegistry()
    worker = RtsWorker((25, 150), [obstacles], "eskimo", "worker_eskimo")
    node_cfg = resource_node_config("seal_hole", "eskimo")
    node_cfg["gather_duration"] = 0.1
    node = ResourceNode((425, 150), [], node_cfg, registry)
    drop_cfg = dropoff_config("smoking_rack", "eskimo")
    dropoff = DropoffBuilding((25, 50), [], drop_cfg, registry)
    wallet = ResourceWallet()
    controller = GatherController(registry)
    controller.set_navigation(walk_grid=grid, obstacle_quad_tree=quad)

    assert controller.assign(worker, node, wallet)
    assert len(worker._path) >= 2

    for _ in range(400):
        controller.update(0.05, obstacles, wallet=wallet)
    assert wallet.get(FOOD) >= 20
    assert not worker.gather_lost


def test_gather_lost_without_dropoff():
    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo", "worker_eskimo")
    node_cfg = resource_node_config("seal_hole", "eskimo")
    node = ResourceNode((100, 0), [], node_cfg, registry)
    wallet = ResourceWallet()
    controller = GatherController(registry)
    controller.assign(worker, node, wallet)
    for _ in range(30):
        controller.update(0.1, obstacle_sprites=None, wallet=wallet)
    assert worker.gather_lost or id(worker) not in controller.tasks


def test_ice_shelf_delivers_to_ice_cutting_post():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo", "worker_eskimo")
    node_cfg = resource_node_config("ice_shelf", "eskimo")
    node_cfg["gather_duration"] = 0.1
    node = ResourceNode((40, 0), [], node_cfg, registry)
    drop_cfg = dropoff_config("ice_cutting_post", "eskimo")
    dropoff = DropoffBuilding((0, 40), [], drop_cfg, registry)
    wallet = ResourceWallet()
    controller = GatherController(registry)

    controller.assign(worker, node, wallet)
    for _ in range(120):
        controller.update(0.05, obstacle_sprites=None, wallet=wallet)
    assert wallet.get(MATERIAL) >= 25
    assert node.dropoff_kind == "ice_cutting_post"
