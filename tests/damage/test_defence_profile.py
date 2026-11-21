"""Defence profiles: worn pieces + natural hide -> layers per region slot (damage chunk 4).

Worn items are the real ones (Graphics/Standard_Items/outfit_items.json) with their real bases
(item_bases.json)."""
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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

import defence_profile as dp  # noqa: E402
import item_properties  # noqa: E402
from damage_data import DamageDataError, body, body_of  # noqa: E402
from Entity import knockback_scale  # noqa: E402
from Inventory import Inventory  # noqa: E402
from Player import BasePlayer as Player  # noqa: E402
from Settings import monster_data  # noqa: E402

OUTFIT = json.loads((ROOT / "Graphics" / "Standard_Items" / "outfit_items.json").read_text(encoding="utf-8"))
BARB = body("barb")


def _item(item_id):
    row = next(r for r in OUTFIT if r["item_id"] == item_id)
    return SimpleNamespace(item_id=row["item_id"], effect_type=row["effect_type"], effect=row["effect"],
                           base=row.get("base"), image_path=None)


FULLPLATE = [r["item_id"] for r in OUTFIT if r["item_id"].startswith("barb_fullplate_")]
HELMET = SimpleNamespace(item_id="plate_helmet_test", effect_type="armour_equip",
                         effect={"slot": "helmet"}, base="plate_helmet", image_path=None)


def _profile(*items):
    return dp.build_profile(BARB, dp.worn_from_items(items))


def _names(profile, region, side=None):
    return [layer.name for layer in profile.layers_at(dp.region_slot(region, side))]


def test_slots_are_the_item_regions_with_sides_for_limbs():
    assert len(dp.SLOTS) == 17
    assert dp.region_slot("chest") == dp.region_slot("chest", "l")      # side ignored on the trunk
    assert dp.region_slot("forearm", "l") != dp.region_slot("forearm", "r")
    with pytest.raises(KeyError):
        dp.region_slot("forearm")
    assert {r for r, _ in dp.SLOTS} == set(item_properties.REGIONS)


def test_full_plate_covers_everything_but_the_head_plate_over_skin():
    profile = _profile(*map(_item, FULLPLATE))
    assert len(FULLPLATE) == 10 and profile.worn
    for region, side in dp.SLOTS:
        names = _names(profile, region, side)
        if region in ("head", "neck"):               # no helmet item yet
            assert names == ["barb"], (region, side)
        else:
            assert names[0].startswith("plate_") and names[1:] == ["barb"], (region, side, names)
    assert profile.weight == pytest.approx(31.0)


def test_a_helmet_covers_head_and_neck():
    profile = _profile(HELMET)
    assert _names(profile, "head") == _names(profile, "neck") == ["plate_helmet", "barb"]
    assert profile.weight == pytest.approx(3.0)


def test_plate_chest_alone():
    profile = _profile(_item("barb_fullplate_chest"))
    covered = {(r, s) for r, s in dp.SLOTS if len(_names(profile, r, s)) == 2}
    assert covered == {("chest", None), ("back", None)}


def test_loincloth_covers_the_waist_only():
    profile = _profile(_item("barb_loincloth_loincloth"))
    assert _names(profile, "waist") == ["loincloth", "barb"]
    assert sum(len(layers) for layers in profile.layers) == len(dp.SLOTS) + 1


def test_a_sided_piece_covers_its_own_side():
    profile = _profile(_item("barb_fullplate_shoulder_l"))
    assert _names(profile, "upper_arm", "l") == ["plate_shoulder", "barb"]
    assert _names(profile, "upper_arm", "r") == ["barb"]


def test_a_piece_with_no_side_covers_both():
    sleeves = {"name": "Sleeves", "stopping_power": 5, "coverage": ["forearm"]}
    profile = dp.build_profile(BARB, [("test_sleeves", sleeves, None)])
    assert _names(profile, "forearm", "l") == _names(profile, "forearm", "r") == ["test_sleeves", "barb"]


def test_harder_layer_goes_outside():
    gambeson = {"name": "Gambeson", "stopping_power": 8, "absorb": 0.5, "weight": 4,
                "coverage": ["chest", "back"]}
    worn = [("test_gambeson", gambeson, None)] + dp.worn_from_items([_item("barb_fullplate_chest")])
    profile = dp.build_profile(BARB, worn)
    assert _names(profile, "chest") == ["plate_chest", "test_gambeson", "barb"]
    assert profile.weight == pytest.approx(16.0)


def test_layers_carry_the_base_numbers_and_are_made_once():
    layer = _profile(_item("barb_fullplate_chest")).layers_at(dp.region_slot("chest"))[0]
    assert (layer.stopping_power, layer.absorb, layer.conductivity, layer.weight) == (40, 0.15, 0.9, 12)
    again = _profile(_item("barb_fullplate_chest")).layers_at(dp.region_slot("back"))[0]
    assert again is layer


def test_unknown_region_or_field_in_a_base_fails():
    with pytest.raises(DamageDataError, match="unknown region 'tail'"):
        dp.build_profile(BARB, [("test_tail", {"coverage": ["tail"]}, None)])
    with pytest.raises(DamageDataError, match=r"unknown layer field\(s\) \['shine'\]"):
        dp.build_profile(BARB, [("test_shine", {"shine": 1, "coverage": ["chest"]}, None)])


def test_weapons_and_items_without_a_base_add_nothing():
    sword = SimpleNamespace(item_id="sword", effect_type="weapon", effect={}, base=None)
    belt = SimpleNamespace(item_id="simple_belt", effect_type="waist_equip", effect={"belt_slots": 1}, base=None)
    assert dp.worn_from_items([sword, belt, None]) == []
    assert _profile(sword, belt) is dp.natural_profile(BARB)


def test_nothing_worn_is_the_shared_natural_profile():
    profile = dp.natural_profile(BARB)
    assert not profile.worn and profile.weight == 0
    assert all(layers == (BARB.natural,) for layers in profile.layers)
    assert dp.build_profile(BARB, []) is profile
    assert dp.natural_profile(None) is None


def test_enemies_of_one_body_share_one_profile():
    a = dp.natural_profile(body_of(monster_data["warrior_00"]))
    b = dp.natural_profile(body_of(monster_data["warrior_13"]))
    assert a is b and a.body.name == "warrior"


# --- the hero: equip rebuilds his profile and his gear weight -------------------------------

def _hero():
    hero = SimpleNamespace(has_belt=False, belt_capacity=0, body_def=BARB,
                           defence=dp.natural_profile(BARB), gear_weight=0.0, mass=90)
    hero.refresh_equipment = types.MethodType(Player.refresh_equipment, hero)
    hero.inventory = Inventory(hero, SimpleNamespace())
    return hero


def test_equip_and_unequip_rebuild_the_heros_profile_and_weight():
    hero = _hero()
    for item_id in FULLPLATE:
        assert hero.inventory.wear(_item(item_id))
    assert hero.defence.worn and hero.gear_weight == pytest.approx(31.0)
    assert _names(hero.defence, "shin", "r") == ["plate_boot", "barb"]
    chest = hero.inventory.slot("armor")
    assert hero.inventory.lift(chest)
    assert _names(hero.defence, "chest") == ["barb"]
    assert hero.gear_weight == pytest.approx(19.0)


def test_full_plate_shoves_the_barb_less():
    hero = _hero()
    bare = knockback_scale(hero)
    for item_id in FULLPLATE:
        hero.inventory.wear(_item(item_id))
    assert knockback_scale(hero) == pytest.approx(bare * 90 / 121)


def test_player_class_starts_with_the_barb_hide():
    assert Player.BODY == "barb"
