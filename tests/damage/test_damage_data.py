"""Attack defs: config/damage/*.json, damage_data.py, and the "attack" keys in Settings (damage chunk 2)."""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = ROOT / "Code"
for path in (str(CODE_DIR), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import damage_data  # noqa: E402
from damage_data import ATTACKS, CATEGORIES, DamageDataError, attack, attack_of  # noqa: E402
from Settings import ability_data, magic_data, monster_data, weapon_data  # noqa: E402
from tools.entity_pipeline import wire  # noqa: E402

SPELL_ART = "demon_dog_projectile"


def _monster_attacks():
    """(monster, where, entry) for every attack a monster has in Settings."""
    for name, monster in monster_data.items():
        config = monster.get("combat_config", {})
        for i, entry in enumerate(config.get("melee_attacks", [])):
            yield name, f"melee_attacks[{i}]", entry
        for i, entry in enumerate(config.get("ranged_attacks", [])):
            yield name, f"ranged_attacks[{i}]", entry
        for entry in config.get("special_attacks", []):
            yield name, entry["name"], entry


def test_files_load_with_ids_in_order():
    assert [d.id for d in ATTACKS] == list(range(len(ATTACKS)))
    assert len({d.name for d in ATTACKS}) == len(ATTACKS)
    assert attack("sword") is attack("sword")
    assert attack("sword") is ATTACKS[attack("sword").id]


def test_unknown_name_names_it():
    with pytest.raises(KeyError, match="no_such_blow"):
        attack("no_such_blow")


def test_attack_of_reads_the_key_or_gives_none():
    assert attack_of({"attack": "arrow"}) is attack("arrow")
    assert attack_of({"residual_attack": "meteor_embers"}, "residual_attack") is attack("meteor_embers")
    assert attack_of({"damage": 5}) is None
    assert attack_of(None) is None


def test_magic_is_category_ids_and_mask_has_the_parents():
    fire = CATEGORIES.ids["fire"]
    elemental = CATEGORIES.ids["elemental"]
    meteor = attack("meteor_impact")
    assert meteor.magic == ((fire, 30),)
    assert meteor.magic_mask == (1 << fire) | (1 << elemental)
    assert attack("curse_bolt").magic_mask == 1 << CATEGORIES.ids["unholy"]
    assert attack("arrow").magic == () and attack("arrow").magic_mask == 0


def test_rows_read_as_written():
    arrow = attack("arrow")
    assert (arrow.delivery, arrow.damage, arrow.penetration, arrow.force, arrow.stops) == ("pierce", 6, 30, 4, True)
    assert attack("scorpion_sting").venom == ("scorpion_venom", 1)
    assert attack("tribal_club").delivery == "crush"
    assert attack("flame").delivery is None and attack("flame").scales_with == "magic"


def test_every_player_weapon_and_spell_and_ability_names_a_def():
    for name, entry in weapon_data.items():
        assert attack_of(entry) is attack(name), name
    for name in ("flame", "ice_ball"):
        assert attack_of(magic_data[name]) is attack(name)
    assert attack_of(ability_data["slide"]) is attack("dash_hit")
    assert attack_of(ability_data["create_ice_clone"]) is attack("ice_clone_burst")
    assert attack_of(ability_data["leap_slam"]) is attack("leap_slam")


def test_player_weapon_def_damage_matches_weapon_data():
    for name, entry in weapon_data.items():
        assert attack(name).damage == entry["damage"], name


def test_every_monster_attack_names_a_def():
    """No hookup forgotten: every melee, ranged and damaging special attack names one."""
    missing = []
    for monster, where, entry in _monster_attacks():
        if where in ("Teleport", "SummonIceGhosts"):
            continue  # no damage of their own
        if attack_of(entry) is None:
            missing.append(f"{monster} {where}")
    assert missing == []


def test_meteor_names_its_embers():
    meteor = monster_data["demon"]["combat_config"]["special_attacks"][0]
    assert attack_of(meteor) is attack("meteor_impact")
    assert attack_of(meteor, "residual_attack") is attack("meteor_embers")


def test_stops_matches_the_old_name_rule():
    """fire_projectile used to stop everything but the spell art at the first body."""
    for monster, where, entry in _monster_attacks():
        art = entry.get("type", entry.get("projectile_type"))
        if art is None:
            continue
        assert attack_of(entry).stops == (art != SPELL_ART), f"{monster} {where}"


@pytest.mark.parametrize("warrior, expected", [
    ("warrior_00", "arrow"), ("warrior_07", "scimitar"), ("warrior_13", "tribal_club"),
    ("warrior_16", "curse_bolt"), ("warrior_17", "sun_bolt"), ("warrior_18", "catapult_shot"),
    ("warrior_19", "scorpion_sting"),
])
def test_warriors_carry_their_weapons_attack(warrior, expected):
    config = monster_data[warrior]["combat_config"]
    entry = (config["melee_attacks"] or config["ranged_attacks"])[0]
    assert entry["attack"] == expected


def test_wire_names_only_real_defs():
    names = {name for _, name in wire.RANGED_ATTACKS + wire.MELEE_ATTACKS}
    names |= {wire.RANGED_FALLBACK, wire.MELEE_FALLBACK}
    for name in names:
        attack(name)
    assert wire.attack_for("Warrior with club/mace", "melee") == "tribal_club"
    assert wire.attack_for("High Priest", "ranged") == "sun_bolt"
    assert wire.attack_for("Catapult Machine", "ranged") == "catapult_shot"
    assert wire.attack_for("Catapult Crewmember", "ranged") == "stone"
    assert wire.attack_for("Tribal Archer", "ranged") == "arrow"


def test_wire_writes_the_attack_key():
    score = {"speed": 5, "damage": 5, "bulk": 5}
    melee = wire.adjust_entry({"combat_config": {}}, {**score, "reach": "melee", "label": "Scimitar Infantryman"})
    assert melee["combat_config"]["melee_attacks"][0]["attack"] == "scimitar"
    ranged = wire.adjust_entry({"combat_config": {}}, {**score, "reach": "ranged", "label": "Magic-User"})
    shot = ranged["combat_config"]["ranged_attacks"][0]
    assert (shot["attack"], shot["type"]) == ("curse_bolt", SPELL_ART)


# --- bad files: the error names the file and the row ---------------------------------------

def _write(tmp_path, attacks):
    path = tmp_path / "attacks.json"
    path.write_text(json.dumps({"schema_version": 1, "attacks": attacks}), encoding="utf-8")
    return path


@pytest.mark.parametrize("row, message", [
    ({"delivery": "pierce", "sharpness": 3}, "unknown field"),
    ({"magic": {"shadow": 5}}, "unknown magic category 'shadow'"),
    ({"delivery": "slash"}, "unknown delivery 'slash'"),
    ({"damage": 5}, "needs a delivery, magic or venom"),
    ({"delivery": "crush", "force": -1}, "force must be a number"),
    ({"delivery": "crush", "stops": "yes"}, "stops must be true or false"),
    ({"venom": {"id": "x"}}, "venom must be"),
    ({"delivery": "crush", "scales_with": "luck"}, "scales_with must be one of"),
])
def test_bad_row_fails_naming_file_and_row(tmp_path, row, message):
    path = _write(tmp_path, {"good": {"delivery": "crush"}, "bad_row": row})
    with pytest.raises(DamageDataError) as err:
        damage_data.load_attacks(path, CATEGORIES)
    assert str(path) in str(err.value)
    assert "'bad_row'" in str(err.value)
    assert message in str(err.value)


def test_bad_schema_version_fails(tmp_path):
    path = tmp_path / "attacks.json"
    path.write_text(json.dumps({"schema_version": 2, "attacks": {}}), encoding="utf-8")
    with pytest.raises(DamageDataError, match="schema_version"):
        damage_data.load_attacks(path, CATEGORIES)


def test_category_with_unknown_parent_fails(tmp_path):
    path = tmp_path / "categories.json"
    path.write_text(json.dumps({"schema_version": 1, "deliveries": ["crush"],
                                "categories": {"fire": "elemental"}}), encoding="utf-8")
    with pytest.raises(DamageDataError, match="'fire': unknown parent 'elemental'"):
        damage_data.load_categories(path)
