import argparse
import json
from dataclasses import dataclass

from Interaction import InteractionContext, InteractionResolver


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    details: str


class StubTarget:
    def __init__(self, team_id="neutral", allow=True):
        self.team_id = team_id
        self.allow = allow
        self.received = []
        self.health = 100
        self.effect_state = {}

    def can_receive_interaction(self, ctx):
        return bool(self.allow)

    def receive_interaction(self, ctx):
        self.received.append(ctx)
        if ctx.kind == "damage" and ctx.amount is not None:
            self.health -= float(ctx.amount)
        if ctx.kind == "effect_state":
            key = ctx.effect_key
            if key:
                if ctx.phase == "end":
                    self.effect_state.pop(key, None)
                else:
                    self.effect_state[key] = {"phase": ctx.phase}


def _run_player_attack_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="enemy", allow=True)
    ctx = InteractionContext(
        kind="damage",
        source_kind="player_attack",
        source_team="player",
        target=target,
        amount=7,
        attack_type="weapon",
        tags={"player"},
    )
    ok = resolver.apply(ctx)
    passed = ok and len(target.received) == 1 and target.health == 93
    return ScenarioResult(
        "PlayerAttackRoute",
        passed,
        f"apply={ok} received={len(target.received)} health={target.health}",
    )


def _run_enemy_projectile_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="player", allow=True)
    ctx = InteractionContext(
        kind="damage",
        source_kind="enemy_projectile",
        source_team="enemy",
        target=target,
        amount=11,
        attack_type="magic",
        tags={"projectile"},
    )
    ok = resolver.apply(ctx)
    passed = ok and len(target.received) == 1 and target.health == 89
    return ScenarioResult(
        "EnemyProjectileRoute",
        passed,
        f"apply={ok} received={len(target.received)} health={target.health}",
    )


def _run_enemy_melee_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="player", allow=True)
    ctx = InteractionContext(
        kind="damage",
        source_kind="enemy_melee",
        source_team="enemy",
        target=target,
        amount=9,
        attack_type="melee",
        tags={"enemy_melee"},
    )
    ok = resolver.apply(ctx)
    passed = ok and len(target.received) == 1 and target.health == 91
    return ScenarioResult(
        "EnemyMeleeRoute",
        passed,
        f"apply={ok} received={len(target.received)} health={target.health}",
    )


def _run_special_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="enemy", allow=True)
    ctx = InteractionContext(
        kind="damage",
        source_kind="special",
        source_team="player",
        target=target,
        amount=5,
        attack_type="explosion",
        tags={"special"},
    )
    ok = resolver.apply(ctx)
    passed = ok and len(target.received) == 1 and target.health == 95
    return ScenarioResult(
        "SpecialRoute",
        passed,
        f"apply={ok} received={len(target.received)} health={target.health}",
    )


def _run_environment_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="player", allow=True)
    allowed_ctx = InteractionContext(
        kind="damage",
        source_kind="environment",
        source_team="environment",
        target=target,
        amount=3,
        attack_type="heat",
        tags={"environment"},
    )
    allowed = resolver.apply(allowed_ctx)

    blocked_target = StubTarget(team_id="enemy", allow=True)
    blocked_ctx = InteractionContext(
        kind="damage",
        source_kind="enemy_projectile",
        source_team="enemy",
        target=blocked_target,
        amount=3,
        attack_type="magic",
        tags={"projectile"},
    )
    blocked = resolver.apply(blocked_ctx)

    passed = (
        allowed
        and not blocked
        and len(target.received) == 1
        and len(blocked_target.received) == 0
    )
    return ScenarioResult(
        "EnvironmentRoute",
        passed,
        (
            f"env_allowed={allowed} env_received={len(target.received)} "
            f"same_team_allowed={blocked} same_team_received={len(blocked_target.received)}"
        ),
    )


def _run_slippery_lifecycle_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="player", allow=True)
    begin_ctx = InteractionContext(
        kind="effect_state",
        source_kind="environment",
        source_team="environment",
        target=target,
        effect_key="slippery",
        phase="begin",
        tags={"environment", "effect_state", "slippery"},
    )
    tick_ctx = InteractionContext(
        kind="effect_state",
        source_kind="environment",
        source_team="environment",
        target=target,
        effect_key="slippery",
        phase="tick",
        tags={"environment", "effect_state", "slippery"},
    )
    end_ctx = InteractionContext(
        kind="effect_state",
        source_kind="environment",
        source_team="environment",
        target=target,
        effect_key="slippery",
        phase="end",
        tags={"environment", "effect_state", "slippery"},
    )
    ok_begin = resolver.apply(begin_ctx)
    ok_tick = resolver.apply(tick_ctx)
    ok_end = resolver.apply(end_ctx)
    passed = ok_begin and ok_tick and ok_end and "slippery" not in target.effect_state
    return ScenarioResult(
        "SlipperyLifecycleRoute",
        passed,
        (
            f"begin={ok_begin} tick={ok_tick} end={ok_end} "
            f"effect_present={'slippery' in target.effect_state}"
        ),
    )


def _run_mixed_effect_route():
    resolver = InteractionResolver()
    target = StubTarget(team_id="player", allow=True)
    heat_ctx = InteractionContext(
        kind="damage",
        source_kind="environment",
        source_team="environment",
        target=target,
        amount=2,
        attack_type="heat",
        effect_key="heat",
        tags={"environment", "heat"},
    )
    slippery_ctx = InteractionContext(
        kind="effect_state",
        source_kind="environment",
        source_team="environment",
        target=target,
        effect_key="slippery",
        phase="begin",
        tags={"environment", "effect_state", "slippery"},
    )
    ok_heat = resolver.apply(heat_ctx)
    ok_slip = resolver.apply(slippery_ctx)
    passed = ok_heat and ok_slip and target.health == 98 and "slippery" in target.effect_state
    return ScenarioResult(
        "MixedEffectRoute",
        passed,
        (
            f"heat={ok_heat} slippery={ok_slip} "
            f"health={target.health} effect_present={'slippery' in target.effect_state}"
        ),
    )


def _run_faction_policy_route():
    resolver = InteractionResolver()
    enemy1_target = StubTarget(team_id="enemy_1", allow=True)
    enemy2_target = StubTarget(team_id="enemy_2", allow=True)
    enemy3_target = StubTarget(team_id="enemy_3", allow=True)
    ally4_target = StubTarget(team_id="ally_4", allow=True)
    neutral_passive = StubTarget(team_id="neutral_passive", allow=True)
    player_target = StubTarget(team_id="player", allow=True)

    enemy1_to_enemy2 = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="enemy_projectile",
            source_team="enemy_1",
            target=enemy2_target,
            amount=4,
            attack_type="magic",
        )
    )
    enemy3_to_enemy1 = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="enemy_projectile",
            source_team="enemy_3",
            target=enemy1_target,
            amount=4,
            attack_type="magic",
        )
    )
    ally4_to_enemy3 = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="special",
            source_team="ally_4",
            target=enemy3_target,
            amount=4,
            attack_type="magic",
        )
    )
    ally4_to_player = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="special",
            source_team="ally_4",
            target=player_target,
            amount=4,
            attack_type="magic",
        )
    )
    neutral_passive_to_enemy1 = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="neutral_attack",
            source_team="neutral_passive",
            target=enemy1_target,
            amount=4,
            attack_type="magic",
        )
    )
    env_to_ally4 = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="environment",
            source_team="environment",
            target=ally4_target,
            amount=2,
            attack_type="heat",
        )
    )

    passed = (
        not enemy1_to_enemy2
        and enemy3_to_enemy1
        and ally4_to_enemy3
        and not ally4_to_player
        and not neutral_passive_to_enemy1
        and env_to_ally4
    )
    return ScenarioResult(
        "FactionPolicyRoute",
        passed,
        (
            f"e1_e2={enemy1_to_enemy2} e3_e1={enemy3_to_enemy1} "
            f"a4_e3={ally4_to_enemy3} a4_p={ally4_to_player} "
            f"npass_e1={neutral_passive_to_enemy1} env_a4={env_to_ally4}"
        ),
    )


def _run_aggro_policy_route():
    resolver = InteractionResolver()

    class AggroActor:
        def __init__(self, team_id):
            self.team_id = team_id

    enemy = AggroActor("enemy")
    player = AggroActor("player")
    neutral = AggroActor("neutral_passive")
    neutral_chaotic = AggroActor("neutral_chaotic")
    ally4 = AggroActor("ally_4")
    enemy1 = AggroActor("enemy_1")
    enemy2 = AggroActor("enemy_2")
    enemy3 = AggroActor("enemy_3")

    # Baseline aggro rules
    enemy_to_player = resolver.can_aggro(enemy, player)
    enemy1_to_enemy2 = resolver.can_aggro(enemy1, enemy2)
    enemy1_to_enemy3 = resolver.can_aggro(enemy1, enemy3)
    ally4_to_enemy3 = resolver.can_aggro(ally4, enemy3)
    ally4_to_player = resolver.can_aggro(ally4, player)
    player_to_neutral_passive = resolver.can_aggro(player, neutral)
    chaotic_to_enemy1 = resolver.can_aggro(neutral_chaotic, enemy1)
    chaotic_to_player = resolver.can_aggro(neutral_chaotic, player)

    # Neutral retaliation behavior
    policy = resolver.faction_policy
    policy.register_retaliation(neutral, "enemy_1", 1000)
    faction_def = policy.resolve_faction("neutral_passive") or {}
    retaliation_window = int(faction_def.get("retaliation_window_ms", 0))
    setattr(neutral, "retaliate_until_ms", 1000 + retaliation_window)
    neutral_to_enemy_after_hit = resolver.can_aggro(neutral, enemy1)

    passed = (
        enemy_to_player
        and not enemy1_to_enemy2
        and enemy1_to_enemy3
        and ally4_to_enemy3
        and not ally4_to_player
        and not player_to_neutral_passive
        and chaotic_to_enemy1
        and chaotic_to_player
        and neutral_to_enemy_after_hit
    )
    return ScenarioResult(
        "AggroPolicyRoute",
        passed,
        (
            f"e_p={enemy_to_player} e1_e2={enemy1_to_enemy2} e1_e3={enemy1_to_enemy3} "
            f"a4_e3={ally4_to_enemy3} a4_p={ally4_to_player} p_np={player_to_neutral_passive} "
            f"nc_e1={chaotic_to_enemy1} nc_p={chaotic_to_player} nret_e1={neutral_to_enemy_after_hit}"
        ),
    )


def _run_multifaction_spawner_route():
    resolver = InteractionResolver()

    a_target = StubTarget(team_id="enemy_1", allow=True)
    b_target = StubTarget(team_id="enemy_3", allow=True)
    a_to_b = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="enemy_projectile",
            source_team="enemy_1",
            target=b_target,
            amount=6,
            attack_type="magic",
        )
    )
    a_to_a = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="enemy_projectile",
            source_team="enemy_1",
            target=a_target,
            amount=6,
            attack_type="magic",
        )
    )

    class AggroActor:
        def __init__(self, team_id):
            self.team_id = team_id

    tribe_a = AggroActor("enemy_1")
    tribe_b = AggroActor("enemy_3")
    aggro_a_b = resolver.can_aggro(tribe_a, tribe_b)
    aggro_a_a = resolver.can_aggro(tribe_a, tribe_a)

    passed = a_to_b and not a_to_a and aggro_a_b and not aggro_a_a
    return ScenarioResult(
        "MultiFactionSpawnerRoute",
        passed,
        (
            f"a_to_b={a_to_b} a_to_a={a_to_a} "
            f"aggro_a_b={aggro_a_b} aggro_a_a={aggro_a_a}"
        ),
    )


def _run_prefilter_route():
    resolver = InteractionResolver()
    can_enemy1_hit_enemy2 = resolver.can_potentially_affect("enemy_1", "enemy_2", "damage")
    can_enemy3_hit_enemy1 = resolver.can_potentially_affect("enemy_3", "enemy_1", "damage")
    can_ally4_hit_player = resolver.can_potentially_affect("ally_4", "player", "damage")
    can_env_hit_enemy1 = resolver.can_potentially_affect("environment", "enemy_1", "damage")
    passed = (
        not can_enemy1_hit_enemy2
        and can_enemy3_hit_enemy1
        and not can_ally4_hit_player
        and can_env_hit_enemy1
    )
    return ScenarioResult(
        "PrefilterRoute",
        passed,
        (
            f"e1_e2={can_enemy1_hit_enemy2} e3_e1={can_enemy3_hit_enemy1} "
            f"a4_p={can_ally4_hit_player} env_e1={can_env_hit_enemy1}"
        ),
    )


def _run_owner_inheritance_route():
    class Owner:
        def __init__(self, team_id):
            self.team_id = team_id

    owner = Owner("friendly")
    particle = type(
        "ParticleStub",
        (),
        {"owner": owner, "source_team": owner.team_id, "source_kind": "enemy_projectile"},
    )()
    target = StubTarget(team_id="enemy", allow=True)
    resolver = InteractionResolver()
    ok = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind=getattr(particle, "source_kind", "enemy_projectile"),
            source=particle,
            owner=owner,
            source_team=getattr(particle, "source_team", None),
            target=target,
            amount=5,
            attack_type="magic",
        )
    )
    passed = ok and target.health == 95
    return ScenarioResult(
        "OwnerInheritanceRoute",
        passed,
        (
            f"apply={ok} source_team={getattr(particle, 'source_team', None)} "
            f"target_health={target.health}"
        ),
    )


def run_validation_suite():
    scenarios = [
        _run_player_attack_route(),
        _run_enemy_projectile_route(),
        _run_enemy_melee_route(),
        _run_special_route(),
        _run_environment_route(),
        _run_slippery_lifecycle_route(),
        _run_mixed_effect_route(),
        _run_faction_policy_route(),
        _run_aggro_policy_route(),
        _run_multifaction_spawner_route(),
        _run_prefilter_route(),
        _run_owner_inheritance_route(),
    ]
    passed = all(s.passed for s in scenarios)
    return {
        "ok": passed,
        "scenarios": [
            {"name": s.name, "passed": s.passed, "details": s.details} for s in scenarios
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run deterministic interaction validation scenarios."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    args = parser.parse_args()
    result = run_validation_suite()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Interaction validation results")
        for row in result["scenarios"]:
            status = "PASS" if row["passed"] else "FAIL"
            print(f"- {row['name']}: {status} ({row['details']})")
        print(f"Overall: {'PASS' if result['ok'] else 'FAIL'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
