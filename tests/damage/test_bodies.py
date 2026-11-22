"""Body defs: config/damage/bodies.json + kinds.json, damage_data, the "body" keys (damage chunk 4)."""
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
import item_properties  # noqa: E402
from damage_data import BODIES, KINDS, DamageDataError, body, body_of  # noqa: E402
from Settings import monster_data  # noqa: E402
from tools.entity_pipeline import wire  # noqa: E402

# The pyramid3 sheet's labels (generated/entity_pipeline/pyramid3/stats.json, not in git).
WARRIOR_LABELS = {
    "00": "Egyptian Archer", "01": "Egyptian Spearman", "02": "Egyptian Shield Bearer",
    "03": "Jaguar Warrior", "04": "Pharaoh's Elite Guard", "05": "Camel-Mounted Spearman",
    "06": "Camel-Mounted Archer", "07": "Desert Chieftain", "08": "Tribal Spearman",
    "09": "Camel-Mounted Standard Bearer", "10": "Scimitar Infantryman", "11": "Hooded Scimitar Fighter",
    "12": "Tribal Archer", "13": "Warrior with Mace", "14": "Large-Shield Spearman",
    "15": "Catapult Crewmember", "16": "Magic-User", "17": "High Priest", "18": "Catapult Machine",
    "19": "Scorpid Creature",
}


def test_bodies_load_with_ids_in_order_and_known_kinds():
    assert [b.id for b in BODIES] == list(range(len(BODIES)))
    assert len({b.name for b in BODIES}) == len(BODIES)
    assert all(b.kind in KINDS for b in BODIES)


def test_every_monster_names_a_body_that_exists():
    for name, entry in monster_data.items():
        assert "body" in entry, name
        assert body_of(entry) is body(entry["body"]), name


def test_body_lookup():
    assert body("demon").kind == "demon"
    assert body_of({}) is None and body_of(None) is None
    with pytest.raises(KeyError, match="nope"):
        body("nope")


@pytest.mark.parametrize("name, numbers", [
    ("barb", (0, 0.05, 0.2, 0)),
    ("demon", (30, 0.3, 0, 0.2)),
    ("tribesman", (10, 0.1, 0.5, 0)),
    ("siege", (30, 0.4, 0.8, 0)),
    ("scorpion", (25, 0.1, 0, 0)),
])
def test_natural_layers_read_as_written(name, numbers):
    n = body(name).natural
    assert (n.stopping_power, n.absorb, n.flammability, n.conductivity) == numbers
    assert n.weight == 0 and n.sealed is False


def test_layer_fields_are_item_properties():
    ids = {p.id for p in item_properties.PROPERTIES} - {"coverage"}
    assert set(damage_data.LAYER_NUMBERS) | {"sealed"} == ids


@pytest.mark.parametrize("warrior, expected, mass", [
    ("03", "beastman", 70), ("05", "camel_rider", 500), ("06", "camel_rider", 500),
    ("07", "camel_rider", 500), ("09", "camel_rider", 500), ("11", "robed", 70), ("16", "robed", 70),
    ("17", "robed", 70), ("18", "siege", 800), ("19", "scorpion", 30), ("00", "warrior", 70),
    ("13", "warrior", 70), ("15", "warrior", 70),
])
def test_warriors_bodies_and_masses(warrior, expected, mass):
    entry = monster_data[f"warrior_{warrior}"]
    assert entry["body"] == expected and entry["mass"] == mass


def test_workers_and_chiefs():
    assert {monster_data[n]["body"] for n in ("eskimo_worker", "eskimo_chief")} == {"eskimo"}
    assert {monster_data[n]["body"] for n in ("jungle_worker", "jungle_chief")} == {"tribesman"}


# --- wire.py: new units get a body from their label --------------------------------------

def test_wire_names_only_real_bodies():
    for _, name, _ in wire.BODIES:
        body(name)
    body(wire.BODY_FALLBACK)


def test_wire_body_for_agrees_with_settings_except_the_hidden_camel():
    for n, label in WARRIOR_LABELS.items():
        entry = monster_data[f"warrior_{n}"]
        name, mass = wire.body_for(label)
        if n == "07":                       # "Desert Chieftain" rides a camel; set by hand
            assert name == "warrior"
            continue
        assert name == entry["body"], (n, label)
        assert mass in (None, entry["mass"]), (n, label)


def test_wire_adjust_sets_a_body_only_when_there_is_none():
    score = {"speed": 5, "bulk": 5, "damage": 5, "reach": "melee", "label": "Camel-Mounted Spearman"}
    fresh = wire.adjust_entry({"mass": 70, "combat_config": {}}, score)
    assert fresh["body"] == "camel_rider" and fresh["mass"] == 500
    kept = wire.adjust_entry({"mass": 500, "body": "camel_rider", "combat_config": {}},
                             {**score, "label": "Desert Chieftain"})
    assert kept["body"] == "camel_rider" and kept["mass"] == 500


# --- bad files fail loudly ---------------------------------------------------------------

def _write(tmp_path, bodies):
    path = tmp_path / "bodies.json"
    path.write_text(json.dumps({"schema_version": 1, "bodies": bodies}), encoding="utf-8")
    return path


@pytest.mark.parametrize("row, message", [
    ({"kind": "elf"}, "unknown kind 'elf'"),
    ({"kind": "living", "mass": 5}, r"unknown field\(s\) \['mass'\]"),
    ({"kind": "living", "natural": {"toughness": 1}}, r"unknown layer field\(s\) \['toughness'\]"),
    ({"kind": "living", "natural": {"absorb": 1.5}}, "absorb must be 0..1"),
    ({"kind": "living", "natural": {"stopping_power": -1}}, "stopping_power must be a number >= 0"),
    ({"kind": "living", "natural": {"sealed": 1}}, "sealed must be true or false"),
])
def test_bad_body_fails_naming_file_and_body(tmp_path, row, message):
    path = _write(tmp_path, {"good": {"kind": "living"}, "bad_body": row})
    with pytest.raises(DamageDataError, match=message) as info:
        damage_data.load_bodies(path, kinds=KINDS)
    assert "bodies.json" in str(info.value) and "'bad_body'" in str(info.value)


def test_kinds_must_be_names(tmp_path):
    path = tmp_path / "kinds.json"
    path.write_text(json.dumps({"schema_version": 1, "kinds": []}), encoding="utf-8")
    with pytest.raises(DamageDataError, match="kinds must be a list of names"):
        damage_data.load_kinds(path)
