import argparse
import json
from dataclasses import dataclass

from Interaction import FactionPolicy, InteractionContext, InteractionResolver


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
    neutral_target = StubTarget(team_id="neutral", allow=True)
    enemy_ctx = InteractionContext(
        kind="damage",
        source_kind="enemy_projectile",
        source_team="enemy",
        target=neutral_target,
        amount=4,
        attack_type="magic",
    )
    ok_enemy_neutral = resolver.apply(enemy_ctx)
    # Same-team is still blocked
    enemy_target = StubTarget(team_id="enemy", allow=True)
    enemy_friendly_fire = InteractionContext(
        kind="damage",
        source_kind="enemy_melee",
        source_team="enemy",
        target=enemy_target,
        amount=4,
        attack_type="melee",
    )
    ok_same_team = resolver.apply(enemy_friendly_fire)
    # Environment still applies to all.
    env_target = StubTarget(team_id="friendly", allow=True)
    env_ctx = InteractionContext(
        kind="damage",
        source_kind="environment",
        source_team="environment",
        target=env_target,
        amount=1,
        attack_type="heat",
    )
    ok_env = resolver.apply(env_ctx)

    passed = ok_enemy_neutral and not ok_same_team and ok_env
    return ScenarioResult(
        "FactionPolicyRoute",
        passed,
        (
            f"enemy_to_neutral={ok_enemy_neutral} same_team={ok_same_team} "
            f"env_to_friendly={ok_env}"
        ),
    )


def _run_aggro_policy_route():
    resolver = InteractionResolver()

    class AggroActor:
        def __init__(self, team_id):
            self.team_id = team_id

    enemy = AggroActor("enemy")
    player = AggroActor("player")
    neutral = AggroActor("neutral")
    friendly = AggroActor("friendly")
    enemy2 = AggroActor("enemy")

    # Baseline aggro rules
    enemy_to_player = resolver.can_aggro(enemy, player)
    enemy_to_neutral = resolver.can_aggro(enemy, neutral)
    friendly_to_enemy = resolver.can_aggro(friendly, enemy)
    enemy_to_enemy = resolver.can_aggro(enemy, enemy2)
    player_to_neutral = resolver.can_aggro(player, neutral)

    # Neutral retaliation behavior
    policy: FactionPolicy = resolver.faction_policy
    policy.register_retaliation(neutral, "enemy", 1000)
    setattr(neutral, "retaliate_until_ms", 1000 + policy.neutral_retaliation_window_ms)
    neutral_to_enemy = resolver.can_aggro(neutral, enemy)

    passed = (
        enemy_to_player
        and not enemy_to_neutral
        and friendly_to_enemy
        and not enemy_to_enemy
        and not player_to_neutral
        and neutral_to_enemy
    )
    return ScenarioResult(
        "AggroPolicyRoute",
        passed,
        (
            f"e_p={enemy_to_player} e_n={enemy_to_neutral} "
            f"f_e={friendly_to_enemy} e_e={enemy_to_enemy} p_n={player_to_neutral} "
            f"n_e_ret={neutral_to_enemy}"
        ),
    )


def _run_multifaction_spawner_route():
    policy = FactionPolicy()
    if "enemy_tribe_a" not in policy.teams:
        policy.teams.append("enemy_tribe_a")
    if "enemy_tribe_b" not in policy.teams:
        policy.teams.append("enemy_tribe_b")
    policy.strict_matrix_only = True
    policy.damage_matrix.setdefault("enemy_tribe_a", {})
    policy.damage_matrix.setdefault("enemy_tribe_b", {})
    policy.damage_matrix["enemy_tribe_a"]["enemy_tribe_a"] = False
    policy.damage_matrix["enemy_tribe_a"]["enemy_tribe_b"] = True
    policy.damage_matrix["enemy_tribe_b"]["enemy_tribe_a"] = True
    policy.damage_matrix["enemy_tribe_b"]["enemy_tribe_b"] = False
    policy.aggro_matrix.setdefault("enemy_tribe_a", {})
    policy.aggro_matrix.setdefault("enemy_tribe_b", {})
    policy.aggro_matrix["enemy_tribe_a"]["enemy_tribe_a"] = False
    policy.aggro_matrix["enemy_tribe_a"]["enemy_tribe_b"] = True
    policy.aggro_matrix["enemy_tribe_b"]["enemy_tribe_a"] = True
    policy.aggro_matrix["enemy_tribe_b"]["enemy_tribe_b"] = False

    resolver = InteractionResolver(faction_policy=policy)

    a_target = StubTarget(team_id="enemy_tribe_a", allow=True)
    b_target = StubTarget(team_id="enemy_tribe_b", allow=True)
    a_to_b = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="enemy_projectile",
            source_team="enemy_tribe_a",
            target=b_target,
            amount=6,
            attack_type="magic",
        )
    )
    a_to_a = resolver.apply(
        InteractionContext(
            kind="damage",
            source_kind="enemy_projectile",
            source_team="enemy_tribe_a",
            target=a_target,
            amount=6,
            attack_type="magic",
        )
    )

    class AggroActor:
        def __init__(self, team_id):
            self.team_id = team_id

    tribe_a = AggroActor("enemy_tribe_a")
    tribe_b = AggroActor("enemy_tribe_b")
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
