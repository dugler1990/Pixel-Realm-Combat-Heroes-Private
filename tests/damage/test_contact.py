"""Where a hit landed: touch_point, find_contacts, entry_point (damage chunk 3)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

import hit_core  # noqa: E402


def _mask_shape(w, h, x, y, fill=True):
    return hit_core.Shape(pygame.mask.Mask((w, h), fill=fill), x, y)


def _dot_shape(x, y):
    """A 1x1 shape: its only pixel is the contact."""
    return _mask_shape(1, 1, x, y)


def _in_shape(shape, point):
    x, y = point[0] - shape.rect.x, point[1] - shape.rect.y
    return 0 <= x < shape.rect.w and 0 <= y < shape.rect.h and shape.mask.get_at((x, y))


class _Body:
    def __init__(self, x, y, solid=True):
        self.rect = pygame.Rect(x, y, 10, 10)
        self.mask = pygame.mask.Mask((10, 10), fill=solid)


# --- touch_point -------------------------------------------------------------------------

def test_touch_point_is_the_shared_pixel_in_world_coords():
    body = _mask_shape(40, 40, 100, 200)
    assert hit_core.touch_point(_dot_shape(117, 223), body) == (117, 223)
    assert hit_core.touch_point(body, _dot_shape(117, 223)) == (117, 223)


def test_touch_point_none_when_nothing_is_shared():
    body = _mask_shape(40, 40, 100, 200)
    assert hit_core.touch_point(_dot_shape(10, 10), body) is None          # rects miss
    hollow = _mask_shape(40, 40, 100, 200, fill=False)
    assert hit_core.touch_point(_dot_shape(117, 223), hollow) is None      # rects meet, pixels don't
    assert hit_core.touch_point(None, body) is None


@pytest.mark.parametrize("a, b", [
    ((10, 10, 0, 0), (10, 10, 5, 5)),
    ((10, 10, 0, 0), (10, 10, 50, 50)),
    ((20, 4, 0, 0), (4, 20, 8, -8)),
])
def test_touching_agrees_with_touch_point(a, b):
    sa, sb = _mask_shape(*a), _mask_shape(*b)
    assert hit_core.touching(sa, sb) == (hit_core.touch_point(sa, sb) is not None)


def test_two_rect_bodies_meet_at_the_centre_of_their_overlap():
    a = hit_core.rect_shape(pygame.Rect(0, 0, 20, 20))
    b = hit_core.rect_shape(pygame.Rect(10, 6, 20, 20))
    assert a.solid and b.solid
    assert hit_core.touch_point(a, b) == pygame.Rect(10, 6, 10, 14).center


def test_rect_body_against_a_mask_gives_a_pixel_of_the_mask():
    rect_body = hit_core.rect_shape(pygame.Rect(0, 0, 40, 40))
    point = hit_core.touch_point(_dot_shape(31, 7), rect_body)
    assert point == (31, 7)


def test_mask_shapes_are_not_solid():
    assert _mask_shape(4, 4, 0, 0).solid is False


# --- find_contacts -----------------------------------------------------------------------

def test_find_contacts_matches_find_hits_and_points_lie_in_both_shapes():
    attack = _mask_shape(20, 20, 0, 0)
    near, also_near, owner = _Body(5, 5), _Body(12, 0), _Body(0, 0)
    far, hollow = _Body(100, 100), _Body(5, 5, solid=False)
    candidates = [far, near, hollow, object(), owner, near, also_near]
    hits = hit_core.find_hits(attack, candidates, exclude=(owner,))
    contacts = hit_core.find_contacts(attack, candidates, exclude=(owner,))
    assert [c[0] for c in contacts] == hits == [near, also_near]
    for sprite, point, body_shape in contacts:
        assert _in_shape(attack, point) and _in_shape(body_shape, point)
        assert body_shape.rect == sprite.rect


def test_find_contacts_with_a_footprint_body():
    attack = _mask_shape(20, 20, 0, 0)
    sprite = _Body(5, 5)
    contacts = hit_core.find_contacts(attack, [sprite], body=lambda s: _mask_shape(2, 2, 6, 6))
    assert contacts and contacts[0][1] == (6, 6)


def test_entry_points_walk_only_when_asked(monkeypatch):
    body = _body()
    sprite = object()
    found = [(sprite, (BODY[0] + 9, BODY[1] + 17), body)]
    calls = []
    real = hit_core.entry_point
    monkeypatch.setattr(hit_core, "entry_point", lambda *a: calls.append(a) or real(*a))
    points = hit_core.EntryPoints(found, (12, 0), 28)
    assert calls == []
    assert points.get(id(sprite)) == (BODY[0], BODY[1] + 17)
    assert points.get(12345) is None and len(calls) == 1


def test_find_contacts_none_shape():
    assert hit_core.find_contacts(None, [_Body(0, 0)]) == []


# --- entry_point -------------------------------------------------------------------------

BODY = (100, 200, 40, 40)   # x, y, w, h


def _body():
    return _mask_shape(BODY[2], BODY[3], BODY[0], BODY[1])


def test_shot_moving_right_enters_on_the_left_column():
    point = (BODY[0] + 9, BODY[1] + 17)
    assert hit_core.entry_point(point, (12, 0), _body()) == (BODY[0], BODY[1] + 17)


def test_shot_moving_left_enters_on_the_right_column():
    point = (BODY[0] + 30, BODY[1] + 5)
    assert hit_core.entry_point(point, (-12, 0), _body()) == (BODY[0] + BODY[2] - 1, BODY[1] + 5)


def test_shot_moving_down_enters_on_the_top_row():
    point = (BODY[0] + 20, BODY[1] + 11)
    assert hit_core.entry_point(point, (0, 12), _body()) == (BODY[0] + 20, BODY[1])


def test_diagonal_shot_enters_on_the_outline_near_its_line():
    body = _body()
    point = (BODY[0] + 20, BODY[1] + 12)
    ex, ey = hit_core.entry_point(point, (8, 8), body)
    assert _in_shape(body, (ex, ey))
    assert ex == BODY[0] + 8 and ey == BODY[1]          # back 12 along (-1,-1)/sqrt2 hits the top row
    # On the line through point with slope 1, within a pixel.
    assert abs((point[0] - ex) - (point[1] - ey)) <= 1


def test_ring_body_stops_at_the_outer_edge_not_the_hole():
    surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    pygame.draw.circle(surf, (255, 255, 255, 255), (20, 20), 20)
    pygame.draw.circle(surf, (0, 0, 0, 0), (20, 20), 8)
    ring = hit_core.Shape(pygame.mask.from_surface(surf), 0, 0)
    # Shot moving left; overlap pixel on the ring's right side, outside the hole.
    point = (34, 20)
    assert ring.mask.get_at(point)
    ex, ey = hit_core.entry_point(point, (-12, 0), ring)
    assert ey == 20 and ex == 39                      # outer right edge
    # Moving right from the same pixel: walks back to the hole's edge, the first gap behind it.
    ex, _ = hit_core.entry_point(point, (12, 0), ring)
    hole_edge = next(x for x in range(20, 40) if ring.mask.get_at((x, 20)))
    assert ex == hole_edge and hole_edge < point[0]


def test_entry_point_respects_max_steps_and_the_cap():
    big = _mask_shape(200, 10, 0, 0)
    assert hit_core.entry_point((150, 5), (1, 0), big, max_steps=10) == (140, 5)
    assert hit_core.entry_point((150, 5), (1, 0), big, max_steps=500) == (86, 5)   # capped at 64


def test_entry_point_returns_the_point_when_it_cannot_walk():
    body = _body()
    assert hit_core.entry_point((110, 210), (0, 0), body) == (110, 210)
    assert hit_core.entry_point((5, 5), (1, 0), body) == (5, 5)          # not on the body
    assert hit_core.entry_point((110, 210), (1, 0), None) == (110, 210)


# --- contact on the hit ------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402
from unittest.mock import Mock  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

import CombatStrategy as combat_strategy  # noqa: E402
import meteor_strike  # noqa: E402
from abilities import leap_slam as leap_slam_module  # noqa: E402
from abilities.dash import DashAbility  # noqa: E402
from abilities.leap_slam import ChargedLeapSlamAbility  # noqa: E402
from damage_data import attack  # noqa: E402
from Interaction import InteractionContext, InteractionResolver  # noqa: E402
from Level4_tmxdev import Level4  # noqa: E402
from Settings import ability_data  # noqa: E402


def _resolver_stub():
    return SimpleNamespace(apply=Mock(return_value=True), can_potentially_affect=lambda *a: True,
                           _now_ms=lambda: 0)


def _target(x=100, y=100, w=40, h=40):
    return SimpleNamespace(rect=pygame.Rect(x, y, w, h), mask=pygame.mask.Mask((w, h), fill=True),
                           team_id="enemy")


def _attack_sprite(rect, **extra):
    fields = dict(owner=None, interaction_kind="damage", source_kind="enemy_projectile",
                  source_team="enemy_1", amount=6, attack_type="magic", tags=set(), hits={},
                  rehit_ms=None, stops=False, attack_def=attack("arrow"),
                  rect=rect, mask=pygame.mask.Mask(rect.size, fill=True))
    fields.update(extra)
    return SimpleNamespace(**fields)


def test_strike_gives_each_context_its_targets_contact():
    resolver = _resolver_stub()
    a, b = SimpleNamespace(team_id="enemy"), SimpleNamespace(team_id="enemy")
    InteractionResolver.strike(resolver, [a, b], contacts={id(a): (1, 2), id(b): (3, 4)},
                               kind="damage", source_kind="x", amount=3)
    got = {id(c.args[0].target): c.args[0].contact for c in resolver.apply.call_args_list}
    assert got == {id(a): (1, 2), id(b): (3, 4)}


def test_strike_asks_for_no_contact_when_the_repeat_rule_skips_the_target():
    resolver = _resolver_stub()
    target = SimpleNamespace(team_id="enemy")
    contacts = Mock()
    InteractionResolver.strike(resolver, [target], hits={id(target): 0}, contacts=contacts,
                               kind="damage", source_kind="x", amount=3)
    contacts.get.assert_not_called()
    resolver.apply.assert_not_called()


def test_strike_without_contacts_leaves_contact_none():
    resolver = _resolver_stub()
    InteractionResolver.strike(resolver, [SimpleNamespace(team_id="enemy")], kind="damage",
                               source_kind="x", amount=3)
    assert resolver.apply.call_args.args[0].contact is None
    assert InteractionContext(kind="damage", source_kind="x").contact is None


def _strike_level(target):
    return SimpleNamespace(attackable_sprites=[target], interaction_resolver=Mock())


def _contact_of(level, target):
    return level.interaction_resolver.strike.call_args.kwargs["contacts"].get(id(target))


def test_arrow_moving_right_lands_on_the_bodys_left_edge():
    target = _target()
    # A 16x4 arrow whose tip is 10 px into the body after this frame's 12 px move.
    arrow = _attack_sprite(pygame.Rect(94, 118, 16, 4), is_moving=True,
                           movement=pygame.math.Vector2(12, 0))
    level = _strike_level(target)
    Level4._strike_with_attack_sprites(level, [arrow])
    contact = _contact_of(level, target)
    assert contact[0] == 100 and 118 <= contact[1] < 122


def test_arrow_moving_left_lands_on_the_bodys_right_edge():
    # pygame's scan finds the overlap's left-most pixels first, so this needs the walk back.
    target = _target()
    arrow = _attack_sprite(pygame.Rect(130, 118, 16, 4), is_moving=True,
                           movement=pygame.math.Vector2(-12, 0))
    level = _strike_level(target)
    Level4._strike_with_attack_sprites(level, [arrow])
    assert hit_core.touch_point(hit_core.shape_of(arrow), hit_core.shape_of(target))[0] < 139
    contact = _contact_of(level, target)
    assert contact[0] == 139 and 118 <= contact[1] < 122


def test_arrow_moving_up_lands_on_the_bodys_bottom_row():
    target = _target()
    arrow = _attack_sprite(pygame.Rect(118, 130, 4, 16), is_moving=True,
                           movement=pygame.math.Vector2(0, -12))
    level = _strike_level(target)
    Level4._strike_with_attack_sprites(level, [arrow])
    contact = _contact_of(level, target)
    assert contact[1] == 139 and 118 <= contact[0] < 122


def test_stopping_arrow_passes_its_contact_too():
    target = _target()
    arrow = _attack_sprite(pygame.Rect(94, 118, 16, 4), is_moving=True,
                           movement=pygame.math.Vector2(12, 0), stops=True, stop=Mock())
    level = _strike_level(target)
    Level4._strike_with_attack_sprites(level, [arrow])
    assert _contact_of(level, target)[0] == 100
    arrow.stop.assert_called_once()


def test_a_weapon_not_moving_lands_on_the_shared_pixel():
    target = _target()
    blade = _attack_sprite(pygame.Rect(130, 90, 20, 30))
    level = _strike_level(target)
    Level4._strike_with_attack_sprites(level, [blade])
    contact = _contact_of(level, target)
    assert contact == hit_core.touch_point(hit_core.shape_of(blade), hit_core.shape_of(target))
    assert pygame.Rect(130, 100, 10, 20).collidepoint(contact)


def test_enemy_melee_swing_passes_the_contact():
    target = _target()
    resolver = Mock()
    strategy = SimpleNamespace(combat_context={"level": SimpleNamespace(interaction_resolver=resolver)})
    enemy = SimpleNamespace(melee_swing={"attack": {"damage": 5}, "hits": {}}, status="attack",
                            frame_index=0, id=1, team_id="enemy_1",
                            rect=pygame.Rect(130, 90, 20, 30), mask=pygame.mask.Mask((20, 30), fill=True))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(combat_strategy.hit_core, "bodies_near", lambda tree, rect, eid: [])
        combat_strategy.CombatStrategy.land_melee_swing(strategy, enemy, target, None)
    contact = resolver.strike.call_args.kwargs["contacts"][id(target)]
    assert pygame.Rect(130, 100, 10, 20).collidepoint(contact)


def test_dash_passes_the_contact():
    target = _target()
    resolver = Mock()
    ability = DashAbility("slide", ability_data["slide"])
    entity = SimpleNamespace(level=SimpleNamespace(interaction_resolver=resolver), id=1, team_id="player",
                             rect=pygame.Rect(130, 90, 20, 30), mask=pygame.mask.Mask((20, 30), fill=True))
    runtime = {"damage": 5, "hits": {}, "hit_once_per_target": True, "rehit_ms": None,
               "attack_type": "weapon", "attack_def": attack("dash_hit")}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hit_core, "bodies_near", lambda tree, rect, eid: [target])
        ability._apply_damage_on_hit(entity, None, None, runtime)
    contact = resolver.strike.call_args.kwargs["contacts"][id(target)]
    assert pygame.Rect(130, 100, 10, 20).collidepoint(contact)


def test_leap_slam_blast_has_no_contact():
    target = SimpleNamespace(team_id="enemy")
    resolver = Mock()
    resolver.can_potentially_affect.return_value = True
    entity = SimpleNamespace(level=SimpleNamespace(attackable_sprites=[target], interaction_resolver=resolver),
                             team_id="player", hitbox=pygame.Rect(0, 0, 20, 10))
    ability = ChargedLeapSlamAbility("leap_slam", ability_data["leap_slam"])
    foot = hit_core.Shape(pygame.mask.Mask((10, 6), fill=True), 20, 0)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(leap_slam_module.hit_core, "find_hits", lambda *a, **k: [target])
        mp.setattr(leap_slam_module.hit_core, "foot_shape", lambda s: foot)
        ability._resolve_landing_aoe(entity, None, None, {"charge_ratio": 1.0})
    contexts = [c.args[0] for c in resolver.apply.call_args_list]
    assert contexts and all(c.contact is None for c in contexts)
    assert all(c.attack_def is attack("leap_slam") for c in contexts)


def test_meteor_blast_has_no_contact():
    resolver = Mock()
    resolver.can_potentially_affect.return_value = True
    target = SimpleNamespace(team_id="player")
    strike = SimpleNamespace(level=SimpleNamespace(interaction_resolver=resolver), source_team="enemy",
                             owner=None, attack_def=attack("meteor_impact"),
                             residual_attack_def=attack("meteor_embers"),
                             _hosts_in_radius=lambda: [target])
    meteor_strike.MeteorStrike._apply_damage(strike, 10, phase="impact")
    assert resolver.apply.call_args.args[0].contact is None


# --- debug dots --------------------------------------------------------------------------

import contact_debug  # noqa: E402


def _landed_hit(resolver, contact):
    target = SimpleNamespace(team_id="enemy", receive_interaction=Mock())
    ctx = InteractionContext(kind="damage", source_kind="x", source_team="player", target=target,
                             amount=1, contact=contact)
    assert resolver.apply(ctx)


@pytest.fixture
def debug_contacts(monkeypatch):
    contact_debug.clear()
    yield
    contact_debug.clear()


def test_flag_off_records_nothing(monkeypatch, debug_contacts):
    monkeypatch.setattr(contact_debug, "ENABLED", False)
    _landed_hit(InteractionResolver(), (5, 6))
    assert contact_debug.recent(10**9, keep_ms=10**9) == []


def test_flag_on_records_landed_contacts_and_drops_old_ones(monkeypatch, debug_contacts):
    monkeypatch.setattr(contact_debug, "ENABLED", True)
    resolver = InteractionResolver()
    monkeypatch.setattr(resolver, "_now_ms", lambda: 1000)
    _landed_hit(resolver, (5, 6))
    _landed_hit(resolver, None)                       # a blast: nothing to draw
    assert contact_debug.recent(1000) == [(5, 6)]
    assert contact_debug.recent(1600) == [(5, 6)]
    assert contact_debug.recent(1601) == []


def test_only_the_last_64_are_kept(debug_contacts):
    for i in range(100):
        contact_debug.record((i, 0), 0)
    kept = contact_debug.recent(0)
    assert len(kept) == 64 and kept[0] == (36, 0)


def test_camera_starts_with_the_settings_flag():
    import Settings
    import YsortCameraGroup
    assert Settings.DEBUG_DRAW_CONTACTS is False
    assert YsortCameraGroup.DEBUG_DRAW_CONTACTS is Settings.DEBUG_DRAW_CONTACTS
