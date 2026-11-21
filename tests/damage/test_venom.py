"""Venom (damage chunk 8, docs/damage/PLAN_venom_holy.md): starts only on flesh, immune bodies,
phases of damage and debuffs, doses, the floor, cures by venom and by class."""
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Code"))

import venom  # noqa: E402
from conditions import bonus  # noqa: E402
from damage_data import DamageDataError, attack, body, load_venoms  # noqa: E402
from defence_profile import build_profile, natural_profile  # noqa: E402

BASES = json.loads((ROOT / "Graphics" / "Standard_Items" / "item_bases.json").read_text(encoding="utf-8"))
PLATE = [n for n, b in BASES.items() if not n.startswith("_") and b.get("set") == "fullplate"]


class _Resolver:
    def apply(self, ctx):
        ctx.target.health -= ctx.amount


def _hero(plate=False, card="barb", health=1000):
    level = SimpleNamespace(interaction_resolver=_Resolver())
    c = body(card)
    defence = build_profile(c, [(n, BASES[n], None) for n in PLATE]) if plate else natural_profile(c)
    return SimpleNamespace(body_def=c, defence=defence, stats={"vitality": 20, "speed": 5},
                           conditions={}, health=health, level=level)


def _run(hero, until_ms, step=venom.TICK_MS):
    for now in range(step, until_ms + 1, step):
        venom.tick(hero.level, now)


def _dart(hero):
    """A blowgun dart through the real pricing and the start rule (no save)."""
    from hit_resolve import apply_venom, resolve
    ctx = SimpleNamespace(kind="damage", attack_def=attack("blowgun_dart"), target=hero, source=None,
                          scale=1.0, contact=None, toward=None)
    apply_venom(ctx, resolve(ctx, 0), 0)


def test_a_dart_on_plate_starts_nothing_and_on_skin_starts_frog_venom():
    plated, naked = _hero(plate=True), _hero()
    _dart(plated)
    _dart(naked)
    assert not getattr(plated, "venoms", None)
    assert "frog_venom" in naked.venoms


def test_an_immune_body_never_takes_it():
    snake = _hero(card="snake")
    assert venom.start(snake, "snake_venom", 1, 0) is False


def test_a_passed_save_shrugs_it_off():
    class Lucky:
        def randrange(self, a, b):
            return 20
    hero = _hero()
    assert venom.start(hero, "plant_venom", 1, 0, rng=Lucky()) is False     # 20 + 20 >= 30
    assert venom.start(hero, "frog_venom", 1, 0, rng=Lucky()) is True       # 40 < 45


def test_a_burst_and_a_creeping_venom_hurt_at_their_own_times():
    burst, creep = _hero(), _hero()
    venom.start(burst, "scorpion_venom", 1, 0)
    venom.start(creep, "snake_venom", 1, 0)
    _run(burst, 4000)
    _run(creep, 4000)
    assert 1000 - burst.health == 32               # 8 per second for 4 s
    assert 1000 - creep.health == 2                # 0.5 per second
    assert bonus(creep, "speed") == -1
    _run(creep, 35000)
    assert 1000 - creep.health == 7 + 40           # 15 s at 0.5, then 20 s at 2
    assert "snake_venom" not in creep.venoms        # past its last phase
    assert bonus(creep, "speed") == 0


def test_doses_raise_the_strength_up_to_max_dose():
    hero = _hero()
    for _ in range(6):
        venom.start(hero, "scorpion_venom", 1, 0)
    assert hero.venoms["scorpion_venom"].strength == 3
    _run(hero, 1000)
    assert 1000 - hero.health == 24


def test_a_mild_venom_stops_at_its_floor():
    hero = _hero(health=25)
    venom.start(hero, "plant_venom", 5, 0)
    _run(hero, 30000)
    assert hero.health == 20


def test_cures_by_class_and_by_venom():
    hero = _hero()
    venom.start(hero, "snake_venom", 1, 0)
    venom.start(hero, "frog_venom", 1, 0)
    antivenom = [{"class": "snake", "strength": 1}]
    venom.cure(hero, antivenom, 0)
    assert hero.venoms["snake_venom"].strength == pytest.approx(0.2)      # class_cure 0.8
    venom.cure(hero, [{"class": "frog", "strength": 1}], 0)
    assert hero.venoms["frog_venom"].strength == 1                        # class_cure 0
    venom.cure(hero, [{"venom": "frog_venom", "strength": 1}], 0)
    assert "frog_venom" not in hero.venoms                               # its own cure ends it


def test_the_antivenom_item_is_a_belt_potion_with_a_snake_class_cure():
    items = json.loads((ROOT / "Graphics" / "Standard_Items" / "standard_items.json").read_text(encoding="utf-8"))
    potion = next(i for i in items if i["item_id"] == "antivenom")
    assert potion["belt_allowed"] and potion["effect"] == {"cure": [{"class": "snake", "strength": 1}]}


def test_a_bad_row_is_refused(tmp_path):
    path = tmp_path / "venoms.json"
    path.write_text(json.dumps({"venoms": {"x": {"class": "snake", "floor": 0, "save": 1,
                                                   "class_cure": 2, "max_dose": 1,
                                                   "phases": [{"ms": 1, "damage_per_s": 1}]}}}))
    with pytest.raises(DamageDataError):
        load_venoms(str(path))
