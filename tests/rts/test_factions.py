from pathlib import Path

from rts.categories import METAL
from rts.factions import get_profile, load_faction_profiles


REPO = Path(__file__).resolve().parents[2]
PROFILES = REPO / "levels" / "tmx" / "rts_faction_profiles.json"


def test_load_eskimo_and_jungle_profiles():
    profiles = load_faction_profiles(str(PROFILES))
    assert "eskimo" in profiles
    assert "jungle_tribe" in profiles
    eskimo = profiles["eskimo"]
    assert eskimo.signature_resource_name == "Ivory"
    assert eskimo.category_active(METAL)
    assert eskimo.display_name_for_category("material") == "Ice"
    jungle = profiles["jungle_tribe"]
    assert jungle.category_active(METAL)
    assert jungle.signature_resource_name == "Spice"


def test_source_for_entity_lookup():
    eskimo = get_profile("eskimo", str(PROFILES))
    row = eskimo.source_for_entity("whale_shore")
    assert row is not None
    assert row["yieldAmount"] == 180
    assert row["dropoffBuilding"] == "rendering_pit"


def test_legacy_entity_alias_still_resolves():
    eskimo = get_profile("eskimo", str(PROFILES))
    assert eskimo.source_for_entity("whale") is None
    from rts.tmx_config import resource_node_config

    cfg = resource_node_config("whale", "eskimo")
    assert cfg["dropoff_kind"] == "rendering_pit"
