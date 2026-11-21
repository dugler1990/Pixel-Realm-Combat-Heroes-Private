"""Every attack carries its AttackDef into the InteractionContext (damage chunk 2).

Driven against duck-typed stubs and the real unbound methods, as test_coop_player_damage does.
Nothing reads the def yet; these check it arrives, and that `stops` now comes from it.
"""
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

import CombatStrategy as combat_strategy  # noqa: E402
import Level4_tmxdev  # noqa: E402
import meteor_strike  # noqa: E402
from abilities.dash import DashAbility  # noqa: E402
from abilities.leap_slam import ChargedLeapSlamAbility  # noqa: E402
from damage_data import attack, attack_of  # noqa: E402
from Interaction import InteractionContext, InteractionResolver  # noqa: E402
from Level4_tmxdev import Level4  # noqa: E402
from Particles import ParticleEffect  # noqa: E402
from Settings import ability_data, monster_data  # noqa: E402
from SpecialAttacks import create_special_attack  # noqa: E402
from Weapon import Weapon  # noqa: E402


def _level_stub():
    stub = SimpleNamespace(
        animation_player=SimpleNamespace(create_particles=Mock()),
        enemy_attack_sprites="enemy_attack_sprites",
        layout_manager=SimpleNamespace(visible_sprites="visible", entity_quad_tree=None),
    )
    for name in ("calculate_angle", "round_angle", "get_direction_from_angle",
                 "_resolve_projectile_damage_payload"):
        setattr(stub, name, types.MethodType(getattr(Level4, name), stub))
    return stub


@pytest.mark.parametrize("art, def_name, stops", [
    ("arrow", "arrow", True),
    ("stone", "catapult_shot", True),
    ("demon_dog_projectile", "fire_spit", False),
    ("demon_dog_projectile", "sun_bolt", False),
])
def test_fire_projectile_puts_the_def_on_the_shot_and_stops_by_it(art, def_name, stops):
    level = _level_stub()
    Level4.fire_projectile(level, (0, 0), (100, 0), art, [], amount=5, attack_def=attack(def_name))
    kwargs = level.animation_player.create_particles.call_args.kwargs
    assert kwargs["attack_def"] is attack(def_name)
    assert kwargs["stops"] is stops


def test_fire_projectile_without_a_def_flies_through():
    level = _level_stub()
    Level4.fire_projectile(level, (0, 0), (100, 0), "arrow", [], amount=5)
    kwargs = level.animation_player.create_particles.call_args.kwargs
    assert kwargs["attack_def"] is None and kwargs["stops"] is False


def test_particle_effect_keeps_the_def():
    frames = [pygame.Surface((4, 4))]
    shot = ParticleEffect((0, 0), frames, [], attack_def=attack("arrow"), stops=True)
    assert shot.attack_def is attack("arrow") and shot.stops is True
    assert ParticleEffect((0, 0), frames, []).attack_def is None  # grass, death puffs


def test_weapon_carries_its_def():
    player = SimpleNamespace(weapon="sword", status="right_idle", rect=pygame.Rect(0, 0, 40, 60),
                             team_id="player")
    assert Weapon(player, []).attack_def is attack("sword")


def test_enemy_melee_strike_sends_the_def():
    entry = monster_data["warrior_13"]["combat_config"]["melee_attacks"][0]
    resolver = Mock()
    strategy = SimpleNamespace(combat_context={"level": SimpleNamespace(interaction_resolver=resolver)})
    enemy = SimpleNamespace(melee_swing={"attack": entry, "hits": {}}, status="attack", frame_index=0,
                            id=1, team_id="enemy_1")
    target = SimpleNamespace(team_id="player")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(combat_strategy.hit_core, "shape_of", lambda e: SimpleNamespace(rect=pygame.Rect(0, 0, 9, 9)))
        mp.setattr(combat_strategy.hit_core, "bodies_near", lambda tree, rect, eid: [])
        mp.setattr(combat_strategy.hit_core, "find_contacts",
                   lambda shape, bodies, exclude=(): [(target, (1, 2), None)])
        combat_strategy.CombatStrategy.land_melee_swing(strategy, enemy, target, None)
    assert resolver.strike.call_args.kwargs["attack_def"] is attack("tribal_club")


@pytest.mark.parametrize("strategy_cls", [combat_strategy.RangedCombatStrategy, combat_strategy.MixedCombatStrategy])
def test_enemy_ranged_shot_sends_the_def(strategy_cls):
    entry = monster_data["warrior_00"]["combat_config"]["ranged_attacks"][0]
    fire = Mock()
    strategy = SimpleNamespace(handle_special_attacks=lambda enemy, target: False, ranged_attacks=[entry],
                               combat_context={"fire_projectile": fire})
    enemy = SimpleNamespace(last_attack_action_time=-10**9, attack_cooldown=0, current_attack_type="ranged",
                            rect=pygame.Rect(0, 0, 10, 10), groups=[], team_id="enemy_1",
                            attack_sound=Mock(), direction=None)
    target = SimpleNamespace(rect=pygame.Rect(100, 0, 10, 10))
    strategy_cls.execute_attack(strategy, enemy, target)
    assert fire.call_args.kwargs["attack_def"] is attack("arrow")


def test_multishot_iceball_sends_ice_shard():
    config = next(s for s in monster_data["ice_mage"]["combat_config"]["special_attacks"]
                  if s["name"] == "MultiShotIceball")
    special = create_special_attack({**config, "chance": 1.0})
    fire = Mock()
    enemy = SimpleNamespace(rect=pygame.Rect(0, 0, 10, 10), groups=[], team_id="enemy", status="idle")
    special.execute(enemy, None, {"fire_projectile": fire})
    assert fire.call_count == config["num_shots"]
    assert all(call.kwargs["attack_def"] is attack("ice_shard") for call in fire.call_args_list)


def test_meteor_shower_hands_both_defs_to_the_strike():
    config = monster_data["demon"]["combat_config"]["special_attacks"][0]
    shower = create_special_attack(config)
    assert shower.attack_def is attack("meteor_impact")
    assert shower.residual_attack_def is attack("meteor_embers")


@pytest.mark.parametrize("phase, def_name", [("impact", "meteor_impact"), ("residual", "meteor_embers")])
def test_meteor_damage_names_the_def_of_its_phase(phase, def_name):
    resolver = Mock()
    target = SimpleNamespace(team_id="player")
    strike = SimpleNamespace(level=SimpleNamespace(interaction_resolver=resolver), source_team="enemy",
                             owner=None, attack_def=attack("meteor_impact"),
                             residual_attack_def=attack("meteor_embers"),
                             _hosts_in_radius=lambda: [target])
    meteor_strike.MeteorStrike._apply_damage(strike, 10, phase=phase)
    assert resolver.apply.call_args.args[0].attack_def is attack(def_name)


def test_dash_runtime_carries_the_def():
    ability = DashAbility("slide", ability_data["slide"])
    entity = SimpleNamespace(energy=100, _dash_runtime=None)
    ability.try_start(entity, None)
    assert entity._dash_runtime["attack_def"] is attack("dash_hit")


def test_leap_slam_reads_its_def():
    assert attack_of(ChargedLeapSlamAbility("leap_slam", ability_data["leap_slam"]).config) is attack("leap_slam")


def test_attack_sprite_strike_copies_the_def_into_the_context():
    target = SimpleNamespace(team_id="enemy")
    sprite = SimpleNamespace(owner=None, interaction_kind="damage", source_kind="enemy_projectile",
                             source_team="enemy_1", amount=6, attack_type="magic", tags=set(),
                             hits={}, rehit_ms=None, stops=False, attack_def=attack("arrow"))
    level = SimpleNamespace(attackable_sprites=[target], interaction_resolver=Mock())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Level4_tmxdev.hit_core, "shape_of", lambda s: "shape")
        mp.setattr(Level4_tmxdev.hit_core, "find_contacts",
                   lambda shape, bodies, exclude=(): [(target, (1, 2), None)])
        Level4._strike_with_attack_sprites(level, [sprite])
    assert level.interaction_resolver.strike.call_args.kwargs["attack_def"] is attack("arrow")


def test_resolver_strike_builds_contexts_with_the_def():
    resolver = SimpleNamespace(land=Mock(return_value=True), team_allows=lambda *a: True,
                               _record_prefilter=lambda skipped: None, _record_emitted=lambda: None,
                               _now_ms=lambda: 0)
    target = SimpleNamespace(team_id="enemy")
    InteractionResolver.strike(resolver, [target], kind="damage", source_kind="x", amount=3,
                               attack_def=attack("scimitar"))
    ctx = resolver.land.call_args.args[0]
    assert ctx.target is target and ctx.attack_def is attack("scimitar")


def test_a_context_without_a_def_is_as_before():
    ctx = InteractionContext(kind="damage", source_kind="x", amount=3)
    assert ctx.attack_def is None
