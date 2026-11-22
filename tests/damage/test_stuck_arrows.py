"""Stuck arrows (damage chunk 11, docs/damage/PLAN_stuck_arrows.md): kept where they went in, not on
plate, capped, expired, placed by the mesh's own projection."""
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Code"))

import body_regions  # noqa: E402
import stuck_arrows  # noqa: E402
from damage_data import attack, layer_def  # noqa: E402
from damage_rules import STUCK_MAX, STUCK_MS  # noqa: E402

BASES = json.loads((ROOT / "Graphics" / "Standard_Items" / "item_bases.json").read_text(encoding="utf-8"))
EXTRA = ("name", "set", "coverage", "weight", "durability")


def _layer(name):
    return layer_def(name, BASES[name], name, extra=EXTRA)


def _hero(yaw=0.0):
    return SimpleNamespace(keeps_arrows=True, mesh_skin=SimpleNamespace(yaw_deg=lambda: yaw))


def _ctx(hero, travel=(1.0, 0.0)):
    return SimpleNamespace(target=hero, attack_def=attack("arrow"), contact=(10, 20), toward=travel)


@pytest.fixture(autouse=True)
def _spot(monkeypatch):
    monkeypatch.setattr(body_regions, "hit_layers",
                        lambda hero, contact, toward=None: body_regions.HitSpot(None, (), point=42))


def test_plate_glances_and_skin_and_cloth_catch():
    plate = next(n for n, b in BASES.items() if not n.startswith("_") and b.get("set") == "fullplate")
    assert _layer(plate).catches is False
    assert _layer("loincloth").catches is True
    assert stuck_arrows.caught(SimpleNamespace(reached_flesh=True, stopped_at=None))
    assert not stuck_arrows.caught(SimpleNamespace(reached_flesh=False, stopped_at=_layer(plate)))
    assert stuck_arrows.caught(SimpleNamespace(reached_flesh=False, stopped_at=_layer("loincloth")))


def test_kept_at_the_point_it_hit_in_the_body_frame():
    hero = _hero(yaw=90.0)
    stuck_arrows.keep(_ctx(hero), SimpleNamespace(reached_flesh=True, stopped_at=None), 0)
    (arrow,) = hero.stuck_arrows
    assert arrow.point == 42
    assert arrow.angle == pytest.approx(-math.pi / 2)          # travel 0 minus a 90 degree yaw
    assert arrow.shows == stuck_arrows.FLESH_SHOWS
    assert arrow.until_ms == STUCK_MS


def test_a_glancing_arrow_and_a_body_that_keeps_none_store_nothing():
    plate = next(n for n, b in BASES.items() if not n.startswith("_") and b.get("set") == "fullplate")
    hero = _hero()
    stuck_arrows.keep(_ctx(hero), SimpleNamespace(reached_flesh=False, stopped_at=_layer(plate)), 0)
    assert not getattr(hero, "stuck_arrows", None)
    monster = SimpleNamespace(mesh_skin=None)
    stuck_arrows.keep(_ctx(monster), SimpleNamespace(reached_flesh=True, stopped_at=None), 0)
    assert not getattr(monster, "stuck_arrows", None)


def test_the_cap_drops_the_oldest_and_they_expire():
    hero = _hero()
    for i in range(STUCK_MAX + 2):
        stuck_arrows.add(hero, i, 0.0, 0.5, 0)
    assert [a.point for a in hero.stuck_arrows] == list(range(2, STUCK_MAX + 2))
    stuck_arrows.placed(hero, STUCK_MS + 1)
    assert hero.stuck_arrows == []


def test_the_spot_follows_the_yaw():
    p = (10.0, 0.0, 50.0)
    x0, y0, _ = stuck_arrows.project(p, 0.0, 1.0)
    x1, y1, _ = stuck_arrows.project(p, math.pi, 1.0)
    assert x0 == 10 and x1 == -10                               # turned round: the other side
    assert y0 == y1
