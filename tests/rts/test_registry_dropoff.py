import pygame

from rts.entities import DropoffBuilding
from rts.registry import RtsWorldRegistry
from rts.tmx_config import dropoff_config


def test_find_nearest_dropoff_picks_closest():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    near_cfg = dropoff_config("ice_cutting_post", "eskimo")
    far_cfg = dropoff_config("ice_cutting_post", "eskimo")
    near = DropoffBuilding((100, 100), [], near_cfg, registry)
    far = DropoffBuilding((500, 500), [], far_cfg, registry)

    chosen = registry.find_nearest_dropoff(
        "eskimo", "ice_cutting_post", (120, 120)
    )
    assert chosen is near
    assert chosen is not far


def test_register_dropoff_keeps_multiple():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    cfg = dropoff_config("ice_cutting_post", "eskimo")
    a = DropoffBuilding((0, 0), [], cfg, registry)
    b = DropoffBuilding((200, 0), [], cfg, registry)
    assert len(registry.dropoffs_for_kind("eskimo", "ice_cutting_post")) == 2
    assert a in registry.dropoffs_for_kind("eskimo", "ice_cutting_post")
    assert b in registry.dropoffs_for_kind("eskimo", "ice_cutting_post")
