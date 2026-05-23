import pygame

from rts.entities import ChiefNPC, ResourceNode
from rts.registry import RtsWorldRegistry
from rts.tmx_config import resource_node_config


def test_registry_faction_node_index():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    registry = RtsWorldRegistry()
    cfg = resource_node_config("seal_hole", "eskimo")
    ResourceNode((0, 0), [], cfg, registry)
    assert "eskimo" in registry.faction_node_index
    assert "food" in registry.faction_node_index["eskimo"]
    assert len(registry.faction_node_index["eskimo"]["food"]) == 1


def test_chief_population_idle():
    registry = RtsWorldRegistry()
    chief = ChiefNPC(
        (0, 0),
        [],
        {
            "chief_id": "c1",
            "faction_id": "eskimo",
            "population_total": 14,
            "population_workers": 2,
            "population_fighters": 2,
        },
        registry,
    )
    assert chief.population_idle == 10
