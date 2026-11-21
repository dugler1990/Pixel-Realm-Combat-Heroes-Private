"""hit_resolve picks the layers and the damage number; apply sets ctx.amount (damage chunk 5)."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

import body_regions  # noqa: E402
import hit_resolve  # noqa: E402
from Entity import Entity  # noqa: E402
from Interaction import LANDED, InteractionContext, InteractionResolver  # noqa: E402
from damage_data import LayerDef, attack, body  # noqa: E402
from damage_rules import Physical, landed  # noqa: E402
from defence_profile import DefenceProfile, natural_profile, region_slot  # noqa: E402
from hit_resolve import resolve  # noqa: E402

HIDE = body("barb").natural
PLATE = LayerDef("plate_test", stopping_power=40, absorb=0.15)
GAMBESON = LayerDef("gambeson_test", stopping_power=5, absorb=0.5)
CHEST = region_slot("chest")


def _worn():
    profile = natural_profile(body("barb"))
    layers = list(profile.layers)
    layers[CHEST] = (PLATE, GAMBESON, HIDE)
    defence = DefenceProfile(body("barb"), tuple(layers), 10.0, True)
    return SimpleNamespace(body_def=body("barb"), defence=defence, team_id="player")


def _ctx(target, **fields):
    base = dict(kind="damage", source_kind="test", source_team="enemy_1", target=target)
    base.update(fields)
    return InteractionContext(**base)


def test_no_attack_and_holy_are_priced_flat_and_fire_here():
    target = _worn()
    assert resolve(_ctx(target, amount=9)) is None
    assert resolve(_ctx(target, attack_def=attack("curse_bolt"))) is None
    flame = resolve(_ctx(target, attack_def=attack("flame")))
    assert flame is not None and landed(flame) == 0


def test_unarmoured_uses_the_hide_and_does_not_look_up_a_region(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("hit_layers")

    monkeypatch.setattr(body_regions, "hit_layers", boom)
    target = SimpleNamespace(body_def=body("barb"), defence=natural_profile(body("barb")),
                             team_id="player")
    result = resolve(_ctx(target, attack_def=attack("arrow"), contact=(1, 2)))
    assert result.reached_flesh is True
    assert landed(result) == 6


def test_the_share_scales_the_def_and_the_stat(monkeypatch):
    seen = {}

    def fake(delivery, damage, penetration, force, layers):
        seen["damage"] = damage
        return Physical(damage, 0.0, True, None)

    monkeypatch.setattr(hit_resolve, "physical", fake)
    source = SimpleNamespace(stats={"attack": 10})
    resolve(_ctx(_worn(), attack_def=attack("sword"), source=source, scale=0.5))
    assert seen["damage"] == (15 + 10) * 0.5


def test_a_player_sword_adds_the_attack_stat(monkeypatch):
    seen = {}

    def fake(delivery, damage, penetration, force, layers):
        seen["damage"] = damage
        seen["layers"] = layers
        return Physical(damage, 0.0, True, None)

    monkeypatch.setattr(hit_resolve, "physical", fake)
    source = SimpleNamespace(stats={"attack": 10}, rect=pygame.Rect(0, 0, 4, 4))
    resolve(_ctx(_worn(), attack_def=attack("sword"), source=source))
    assert seen["damage"] == 25
    assert seen["layers"][0] is PLATE


def test_points_front_piece_then_the_region_under_it(monkeypatch):
    seen = {}

    def fake(delivery, damage, penetration, force, layers):
        seen["layers"] = layers
        return Physical(0.0, 0.0, False, layers[0])

    def spot(hero, contact, toward=None):
        return body_regions.HitSpot(CHEST, (PLATE, HIDE), "barb_fullplate_chest", point=object())

    monkeypatch.setattr(hit_resolve, "physical", fake)
    monkeypatch.setattr(body_regions, "hit_layers", spot)
    resolve(_ctx(_worn(), attack_def=attack("arrow"), contact=(3, 4)))
    assert seen["layers"] == (PLATE, GAMBESON, HIDE)


def test_a_skin_pixel_is_the_hide_only(monkeypatch):
    seen = {}

    def fake(delivery, damage, penetration, force, layers):
        seen["layers"] = layers
        return Physical(0.0, 0.0, True, None)

    def spot(hero, contact, toward=None):
        return body_regions.HitSpot(CHEST, (HIDE,), None, point=object())

    monkeypatch.setattr(hit_resolve, "physical", fake)
    monkeypatch.setattr(body_regions, "hit_layers", spot)
    resolve(_ctx(_worn(), attack_def=attack("arrow"), contact=(3, 4)))
    assert seen["layers"] == (HIDE,)


def test_capsules_keep_the_spots_own_stack(monkeypatch):
    seen = {}

    def fake(delivery, damage, penetration, force, layers):
        seen["layers"] = layers
        return Physical(0.0, 0.0, False, None)

    def spot(hero, contact, toward=None):
        return body_regions.HitSpot(CHEST, (GAMBESON, HIDE), None, point=None)

    monkeypatch.setattr(hit_resolve, "physical", fake)
    monkeypatch.setattr(body_regions, "hit_layers", spot)
    resolve(_ctx(_worn(), attack_def=attack("arrow"), contact=(3, 4)))
    assert seen["layers"] == (GAMBESON, HIDE)


def test_no_contact_uses_the_chest_stack(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("hit_layers")

    monkeypatch.setattr(body_regions, "hit_layers", boom)
    seen = {}

    def fake(delivery, damage, penetration, force, layers):
        seen["layers"] = layers
        return Physical(damage, 0.0, False, None)

    monkeypatch.setattr(hit_resolve, "physical", fake)
    resolve(_ctx(_worn(), attack_def=attack("leap_slam")))
    assert seen["layers"][0] is PLATE and HIDE in seen["layers"]


def test_apply_sets_the_landed_int_and_the_body_subtracts_it():
    target = SimpleNamespace(
        body_def=body("raccoon"), defence=natural_profile(body("raccoon")),
        team_id="enemy_1", health=100, hit_time=0,
        can_receive_interaction=lambda ctx: True, on_hurt=lambda ctx: None,
    )
    target.take_damage = lambda ctx: Entity.take_damage(target, ctx)
    target.receive_interaction = lambda ctx: Entity.receive_interaction(target, ctx)
    source = SimpleNamespace(
        stats={"attack": 10}, team_id="player", rect=pygame.Rect(0, 0, 8, 8),
    )
    ctx = InteractionContext(
        kind="damage", source_kind="player_attack", source=source, source_team="player",
        target=target, attack_type="weapon", attack_def=attack("sword"),
    )
    assert InteractionResolver().apply(ctx) is LANDED
    lost = 100 - target.health
    assert ctx.amount == lost and 0 < lost < 100
