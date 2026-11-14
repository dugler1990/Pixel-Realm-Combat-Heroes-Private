"""The item card: base stats (Graphics/Standard_Items/item_bases.json), the property rows (Code/item_properties.py)
and the card text made from them (Code/item_card.py). No hand-written stat text: every line here comes from a
base number through a property row."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pytest  # noqa: E402

import equipment  # noqa: E402
import item_card  # noqa: E402
import item_properties as P  # noqa: E402

ITEMS = REPO_ROOT / "Graphics" / "Standard_Items" / "outfit_items.json"
BASES = P.load_bases()


def outfit_item(item_id):
    for e in json.loads(ITEMS.read_text(encoding="utf-8")):
        if e["item_id"] == item_id:
            return SimpleNamespace(**e)
    pytest.skip(f"{item_id} not in outfit_items.json")


# --- the loader --------------------------------------------------------------------------------------------

def test_every_outfit_item_names_a_base_that_exists():
    if not ITEMS.is_file():
        pytest.skip("no outfit_items.json")
    for e in json.loads(ITEMS.read_text(encoding="utf-8")):
        assert e.get("base") in BASES, e["item_id"]


def test_every_base_field_is_a_known_property():
    for base_id, base in BASES.items():
        assert P.unknown_fields(base) == [], base_id
        assert set(base.get("coverage", [])) <= set(P.REGIONS), base_id


def test_left_and_right_pieces_share_a_base():
    assert equipment.piece_base("boot_l", "plate") == equipment.piece_base("boot_r", "plate") == "plate_boot"
    assert equipment.piece_base("chest", "plate") == "plate_chest"
    assert equipment.piece_base("loincloth") == "loincloth"
    for piece, (_, _, side) in equipment.PIECES.items():
        assert not equipment.piece_base(piece).endswith(("_l", "_r")), piece


def test_property_rows_are_well_formed():
    for p in P.PROPERTIES:
        assert p.group in ("physical", "element", "cost", "state"), p.id
        assert p.format in ("int", "number", "percent", "yes-no", "list"), p.id
        assert p.better in ("higher", "lower") and p.card in ("line", "detail"), p.id
    assert len(P.BY_ID) == len(P.PROPERTIES)


# --- the card ----------------------------------------------------------------------------------------------

def test_plate_chest_card():
    card = item_card.build(outfit_item("barb_fullplate_chest"))
    assert card.name == "Plate chest"
    assert card.type_line == "Chest · Heavy · Fullplate set"
    assert card.verdicts == ()
    assert card.lines == ("Covers: chest, back", "Weight 12", "Stopping power 40", "Cushions 15% of force",
                          "Conducts lightning", "Durability 300 / 300")
    assert ("Insulation", "20%") in card.detail and ("Sealed", "no") in card.detail
    assert len(card.detail) == len(BASES["plate_chest"]) - sum(k in P.IDENTITY for k in BASES["plate_chest"])


def test_loincloth_card():
    card = item_card.build(outfit_item("barb_loincloth_loincloth"))
    assert card.name == "Loincloth"
    assert card.type_line == "Waist · Light"                       # no set
    assert card.lines == ("Covers: waist", "Weight 0.3", "Cushions 5% of force", "Catches fire",
                          "Durability 40 / 40")                   # stopping power 0: no line


def test_sides_and_durability_now_show():
    boot = outfit_item("barb_fullplate_boot_l")
    boot.durability = 75
    card = item_card.build(boot)
    assert card.type_line.startswith("Boot (left) · Heavy") and card.lines[-1] == "Durability 75 / 120"


def test_a_number_change_changes_the_card(monkeypatch):
    base = dict(BASES["plate_chest"], conductivity=0.1, stopping_power=55)
    monkeypatch.setattr(P, "_bases", {"x": base})
    lines = item_card.build(SimpleNamespace(base="x", effect_type="armour_equip", effect={"slot": "armor"})).lines
    assert "Stopping power 55" in lines and "Conducts lightning" not in lines


def test_an_item_with_no_base_shows_name_and_description():
    card = item_card.build(SimpleNamespace(item_id="frost_potion", description="Restores 25 health."))
    assert card.name == "Frost potion" and card.flavour == "Restores 25 health."
    assert card.type_line == "" and card.lines == () and card.detail == ()


def test_the_panel_builds_once_per_item_not_per_frame(monkeypatch):
    import pygame
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    os.chdir(CODE_DIR)                                   # the kit loads its pictures from ../Graphics
    import legion_ui as L
    from inventory_view import CardPanel
    from render_backend import CPUBackend
    backend = CPUBackend(screen)
    kit = L.kit_for(backend)
    calls = []
    real = item_card.build
    monkeypatch.setattr(item_card, "build", lambda item: calls.append(item) or real(item))
    chest, panel = outfit_item("barb_fullplate_chest"), CardPanel()
    rect = pygame.Rect(800, 100, 200, 500)
    for _ in range(3):
        panel.draw(backend, kit, rect, chest, False)
    assert len(calls) == 1
    chest.durability = 250                               # the item changed: built again
    panel.draw(backend, kit, rect, chest, False)
    panel.draw(backend, kit, rect, chest, True)          # detail view
    assert len(calls) == 3
