from dataclasses import dataclass, field
import json
import os
from typing import Any, Dict, Optional, Set

from game_logging import get_debug_logger

_interaction_log = get_debug_logger("combat")


@dataclass
class InteractionContext:
    kind: str
    source_kind: str
    source: Any = None
    owner: Any = None
    source_team: Optional[str] = None
    target: Any = None
    amount: Optional[float] = None
    attack_type: Optional[str] = None
    phase: Optional[str] = None
    effect_key: Optional[str] = None
    effect_area_id: Optional[Any] = None
    tags: Set[str] = field(default_factory=set)


class FactionPolicy:
    """Central faction policy for interaction permissions and aggro selection."""

    def __init__(self):
        self.teams = ["player", "enemy", "neutral", "friendly", "environment"]
        self.strict_matrix_only = False
        self.neutral_retaliation_window_ms = 12000
        self._unknown_teams_warned: Set[str] = set()
        self.damage_matrix = self._build_default_damage_matrix(self.teams)
        self.aggro_matrix = self._build_default_aggro_matrix(self.teams)
        self._load_external_config()

    def _build_default_damage_matrix(self, teams):
        matrix: Dict[str, Dict[str, bool]] = {
            source: {target: (source != target) for target in teams} for source in teams
        }
        if "environment" in matrix:
            matrix["environment"] = {target: True for target in teams}
        return matrix

    def _build_default_aggro_matrix(self, teams):
        matrix: Dict[str, Dict[str, bool]] = {
            source: {target: False for target in teams} for source in teams
        }
        # Preserve current baseline aggro semantics for default teams.
        if "player" in matrix and "enemy" in matrix["player"]:
            matrix["player"]["enemy"] = True
        if "enemy" in matrix:
            if "player" in matrix["enemy"]:
                matrix["enemy"]["player"] = True
            if "friendly" in matrix["enemy"]:
                matrix["enemy"]["friendly"] = True
        if "friendly" in matrix and "enemy" in matrix["friendly"]:
            matrix["friendly"]["enemy"] = True
        return matrix

    def _config_path(self):
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config",
            "faction_policy.json",
        )

    def _warn_unknown_team(self, team_id: str):
        if team_id in self._unknown_teams_warned:
            return
        self._unknown_teams_warned.add(team_id)
        _interaction_log.warning(
            "Unknown faction team_id=%r encountered; using %s behavior",
            team_id,
            "strict deny" if self.strict_matrix_only else "fallback permissive",
        )

    def _coerce_bool_matrix(self, raw_matrix, matrix_name):
        if not isinstance(raw_matrix, dict):
            _interaction_log.warning(
                "Faction policy %s must be an object; keeping defaults",
                matrix_name,
            )
            return None
        result: Dict[str, Dict[str, bool]] = {}
        for source, source_rules in raw_matrix.items():
            source_id = str(source)
            if not isinstance(source_rules, dict):
                _interaction_log.warning(
                    "Faction policy %s[%r] must be an object; skipping row",
                    matrix_name,
                    source_id,
                )
                continue
            result[source_id] = {}
            for target, allowed in source_rules.items():
                target_id = str(target)
                if not isinstance(allowed, bool):
                    _interaction_log.warning(
                        "Faction policy %s[%r][%r] must be bool; got %r (skipped)",
                        matrix_name,
                        source_id,
                        target_id,
                        allowed,
                    )
                    continue
                result[source_id][target_id] = allowed
        return result

    def _load_external_config(self):
        path = self._config_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            _interaction_log.warning(
                "Failed to load faction policy config %s: %s (keeping defaults)",
                path,
                exc,
            )
            return
        if not isinstance(payload, dict):
            _interaction_log.warning(
                "Faction policy config %s must be a top-level object (keeping defaults)",
                path,
            )
            return

        configured_teams = payload.get("teams")
        if isinstance(configured_teams, list) and configured_teams:
            parsed_teams = []
            for raw in configured_teams:
                team = str(raw).strip()
                if team and team not in parsed_teams:
                    parsed_teams.append(team)
            if parsed_teams:
                self.teams = parsed_teams
                self.damage_matrix = self._build_default_damage_matrix(self.teams)
                self.aggro_matrix = self._build_default_aggro_matrix(self.teams)
        elif configured_teams is not None:
            _interaction_log.warning(
                "Faction policy teams must be a non-empty list of team ids; keeping defaults"
            )

        params = payload.get("policy_params", {})
        if isinstance(params, dict):
            retaliation_ms = params.get("neutral_retaliation_window_ms")
            if isinstance(retaliation_ms, int) and retaliation_ms >= 0:
                self.neutral_retaliation_window_ms = retaliation_ms
            strict_mode = params.get("strict_matrix_only")
            if isinstance(strict_mode, bool):
                self.strict_matrix_only = strict_mode
        elif params is not None:
            _interaction_log.warning(
                "Faction policy policy_params must be an object; keeping defaults"
            )

        damage_raw = payload.get("damage_matrix")
        parsed_damage = self._coerce_bool_matrix(damage_raw, "damage_matrix")
        if parsed_damage is not None:
            for source, source_rules in parsed_damage.items():
                if source not in self.damage_matrix:
                    self.damage_matrix[source] = {}
                    if source not in self.teams:
                        self._warn_unknown_team(source)
                for target, allowed in source_rules.items():
                    if target not in self.teams:
                        self._warn_unknown_team(target)
                    self.damage_matrix[source][target] = allowed

        aggro_raw = payload.get("aggro_matrix")
        parsed_aggro = self._coerce_bool_matrix(aggro_raw, "aggro_matrix")
        if parsed_aggro is not None:
            for source, source_rules in parsed_aggro.items():
                if source not in self.aggro_matrix:
                    self.aggro_matrix[source] = {}
                    if source not in self.teams:
                        self._warn_unknown_team(source)
                for target, allowed in source_rules.items():
                    if target not in self.teams:
                        self._warn_unknown_team(target)
                    self.aggro_matrix[source][target] = allowed
        _interaction_log.debug(
            "Faction policy loaded strict=%s retaliation_ms=%s teams=%s config=%s",
            self.strict_matrix_only,
            self.neutral_retaliation_window_ms,
            self.teams,
            path,
        )

    def allows_damage(self, source_team: Optional[str], target_team: Optional[str], ctx: InteractionContext) -> bool:
        if ctx.kind != "damage":
            return True
        # Preserve compatibility by default; strict mode can enforce matrix-only teams.
        if source_team is None or target_team is None:
            return True
        if source_team not in self.teams:
            self._warn_unknown_team(source_team)
            if self.strict_matrix_only:
                return False
        if target_team not in self.teams:
            self._warn_unknown_team(target_team)
            if self.strict_matrix_only:
                return False
        source_rules = self.damage_matrix.get(source_team)
        if source_rules is None:
            if self.strict_matrix_only:
                return False
            return source_team != target_team
        if target_team in source_rules:
            return bool(source_rules[target_team])
        if self.strict_matrix_only:
            return False
        return source_team != target_team

    def should_aggro(self, source: Any, target: Any) -> bool:
        source_team = getattr(source, "team_id", None)
        target_team = getattr(target, "team_id", None)
        if source_team is None or target_team is None:
            return False
        if source_team not in self.teams:
            self._warn_unknown_team(source_team)
            if self.strict_matrix_only:
                return False
        if target_team not in self.teams:
            self._warn_unknown_team(target_team)
            if self.strict_matrix_only:
                return False
        source_rules = self.aggro_matrix.get(source_team, {})
        allowed = bool(source_rules.get(target_team, False))
        if allowed:
            return True
        # Neutrals can retaliate if recently attacked.
        if source_team == "neutral":
            retaliate_team = getattr(source, "retaliate_team_id", None)
            retaliate_until = getattr(source, "retaliate_until_ms", 0)
            if retaliate_team == target_team and retaliate_until > 0:
                return True
        return False

    def register_retaliation(self, target: Any, attacker_team: Optional[str], now_ms: int):
        if attacker_team is None:
            return
        if getattr(target, "team_id", None) != "neutral":
            return
        setattr(target, "retaliate_team_id", attacker_team)
        setattr(target, "retaliate_until_ms", now_ms + self.neutral_retaliation_window_ms)


class InteractionResolver:
    def __init__(self, telemetry_sink: Any = None, faction_policy: Optional[FactionPolicy] = None):
        self.telemetry_sink = telemetry_sink
        self.faction_policy = faction_policy or FactionPolicy()

    def set_telemetry_sink(self, telemetry_sink: Any):
        self.telemetry_sink = telemetry_sink

    def set_faction_policy(self, faction_policy: FactionPolicy):
        self.faction_policy = faction_policy

    def _record_emitted(self):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_interaction_emitted"):
            sink.record_interaction_emitted()

    def _record_resolved(self, ctx: InteractionContext):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_interaction_resolved"):
            sink.record_interaction_resolved(ctx)

    def _record_rejected_team(self):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_interaction_rejected_team"):
            sink.record_interaction_rejected_team()

    def _record_rejected_reason(self, reason: str):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_interaction_rejected_reason"):
            sink.record_interaction_rejected_reason(reason)

    def _record_rejected_target(self):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_interaction_rejected_target"):
            sink.record_interaction_rejected_target()

    def _record_aggro_check(self, allowed: bool):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_aggro_check"):
            sink.record_aggro_check(allowed)

    def can_team_interact(self, source_team: Optional[str], target_team: Optional[str], ctx: InteractionContext) -> bool:
        return self.faction_policy.allows_damage(source_team, target_team, ctx)

    def can_aggro(self, source: Any, target: Any) -> bool:
        allowed = self.faction_policy.should_aggro(source, target)
        self._record_aggro_check(allowed)
        return allowed

    def apply(self, ctx: InteractionContext) -> bool:
        self._record_emitted()
        target = ctx.target
        if target is None:
            self._record_rejected_target()
            self._record_rejected_reason("missing_target")
            return False
        if not self.can_team_interact(ctx.source_team, getattr(target, "team_id", None), ctx):
            self._record_rejected_team()
            self._record_rejected_reason("team_policy")
            return False
        if hasattr(target, "can_receive_interaction") and not target.can_receive_interaction(ctx):
            self._record_rejected_target()
            self._record_rejected_reason("target_gate")
            return False
        if not hasattr(target, "receive_interaction"):
            self._record_rejected_target()
            self._record_rejected_reason("no_receive_interaction")
            return False
        target.receive_interaction(ctx)
        # Neutral retaliation registration happens after a successful hostile damage interaction.
        if ctx.kind == "damage" and ctx.source_team is not None:
            self.faction_policy.register_retaliation(target, ctx.source_team, self._now_ms())
        self._record_resolved(ctx)
        return True

    def _now_ms(self) -> int:
        try:
            import pygame  # local import to avoid hard dependency for non-game usages
            return pygame.time.get_ticks()
        except Exception:
            import time
            return int(time.time() * 1000)
