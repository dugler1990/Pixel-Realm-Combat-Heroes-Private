from dataclasses import dataclass, field
import json
import os
from typing import Any, Dict, Optional, Set, Tuple

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
        self.default_retaliation_window_ms = 12000
        self.unknown_faction_behavior = "reject"
        self._unknown_teams_warned: Set[str] = set()
        self.archetypes: Dict[str, Dict[str, Any]] = {}
        self.factions: Dict[str, Dict[str, Any]] = {}
        self.relations_defaults: Dict[str, str] = {
            "same_faction": "ally",
            "same_archetype": "neutral",
            "fallback": "neutral",
        }
        self.archetype_relations: Dict[str, Dict[str, str]] = {}
        self.pair_relations: Dict[Tuple[str, str], str] = {}
        self._load_external_config()

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
            "Unknown faction team_id=%r encountered; behavior=%s",
            team_id,
            self.unknown_faction_behavior,
        )

    def _coerce_mode(self, value: Any, allowed: Set[str], default_value: str, label: str) -> str:
        if isinstance(value, str):
            norm = value.strip().lower()
            if norm in allowed:
                return norm
        if value is not None:
            _interaction_log.warning("%s must be one of %s, got %r; using %r", label, sorted(allowed), value, default_value)
        return default_value

    def _load_external_config(self):
        path = self._config_path()
        if not os.path.exists(path):
            raise RuntimeError(f"Faction policy config not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to load faction policy config {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Faction policy config {path} must be a top-level object")

        schema_version = payload.get("schema_version")
        if schema_version != 2:
            raise RuntimeError(
                f"Faction policy schema_version must be 2, got {schema_version!r}"
            )

        params = payload.get("policy_params")
        if not isinstance(params, dict):
            raise RuntimeError("Faction policy requires policy_params object")
        unknown_behavior = params.get("unknown_faction_behavior", "reject")
        self.unknown_faction_behavior = self._coerce_mode(
            unknown_behavior,
            {"reject"},
            "reject",
            "policy_params.unknown_faction_behavior",
        )
        default_window = params.get("default_retaliation_window_ms", 12000)
        if not isinstance(default_window, int) or default_window < 0:
            raise RuntimeError("policy_params.default_retaliation_window_ms must be a non-negative int")
        self.default_retaliation_window_ms = default_window

        archetypes = payload.get("archetypes")
        if not isinstance(archetypes, dict) or not archetypes:
            raise RuntimeError("Faction policy requires non-empty archetypes object")
        self.archetypes = {}
        for archetype_id, raw in archetypes.items():
            if not isinstance(raw, dict):
                raise RuntimeError(f"archetypes[{archetype_id!r}] must be an object")
            aggro_mode = self._coerce_mode(
                raw.get("aggro_mode", "hostile_only"),
                {"never", "hostile_only", "retaliate_only", "all"},
                "hostile_only",
                f"archetypes.{archetype_id}.aggro_mode",
            )
            damage_mode = self._coerce_mode(
                raw.get("damage_mode", "hostile_only"),
                {"none", "hostile_only", "all_except_allies", "all"},
                "hostile_only",
                f"archetypes.{archetype_id}.damage_mode",
            )
            retaliation_window = raw.get(
                "retaliation_window_ms",
                self.default_retaliation_window_ms,
            )
            if not isinstance(retaliation_window, int) or retaliation_window < 0:
                raise RuntimeError(
                    f"archetypes[{archetype_id!r}].retaliation_window_ms must be non-negative int"
                )
            self.archetypes[str(archetype_id)] = {
                "aggro_mode": aggro_mode,
                "damage_mode": damage_mode,
                "retaliation_window_ms": retaliation_window,
            }

        factions = payload.get("factions")
        if not isinstance(factions, dict) or not factions:
            raise RuntimeError("Faction policy requires non-empty factions object")
        self.factions = {}
        for faction_id, raw in factions.items():
            if not isinstance(raw, dict):
                raise RuntimeError(f"factions[{faction_id!r}] must be an object")
            archetype = str(raw.get("archetype", "")).strip()
            if not archetype:
                raise RuntimeError(f"factions[{faction_id!r}] missing archetype")
            if archetype not in self.archetypes:
                raise RuntimeError(
                    f"factions[{faction_id!r}] archetype {archetype!r} not defined in archetypes"
                )
            faction_data = {
                "archetype": archetype,
                "aggro_mode": self._coerce_mode(
                    raw.get("aggro_mode"),
                    {"never", "hostile_only", "retaliate_only", "all"},
                    self.archetypes[archetype]["aggro_mode"],
                    f"factions.{faction_id}.aggro_mode",
                ),
                "damage_mode": self._coerce_mode(
                    raw.get("damage_mode"),
                    {"none", "hostile_only", "all_except_allies", "all"},
                    self.archetypes[archetype]["damage_mode"],
                    f"factions.{faction_id}.damage_mode",
                ),
                "retaliation_window_ms": raw.get(
                    "retaliation_window_ms",
                    self.archetypes[archetype]["retaliation_window_ms"],
                ),
            }
            if (
                not isinstance(faction_data["retaliation_window_ms"], int)
                or faction_data["retaliation_window_ms"] < 0
            ):
                raise RuntimeError(
                    f"factions[{faction_id!r}].retaliation_window_ms must be non-negative int"
                )
            self.factions[str(faction_id)] = faction_data

        relations = payload.get("relations")
        if not isinstance(relations, dict):
            raise RuntimeError("Faction policy requires relations object")
        defaults = relations.get("defaults")
        if not isinstance(defaults, dict):
            raise RuntimeError("relations.defaults must be an object")
        for key in ("same_faction", "same_archetype", "fallback"):
            relation = defaults.get(key)
            if relation not in {"ally", "neutral", "hostile"}:
                raise RuntimeError(f"relations.defaults.{key} must be ally|neutral|hostile")
            self.relations_defaults[key] = relation

        self.archetype_relations = {}
        raw_archetype_relations = relations.get("archetype_relations", {})
        if raw_archetype_relations is not None:
            if not isinstance(raw_archetype_relations, dict):
                raise RuntimeError("relations.archetype_relations must be an object")
            for source_arch, target_map in raw_archetype_relations.items():
                if not isinstance(target_map, dict):
                    raise RuntimeError(
                        f"relations.archetype_relations[{source_arch!r}] must be an object"
                    )
                src = str(source_arch)
                self.archetype_relations[src] = {}
                for target_arch, relation in target_map.items():
                    if relation not in {"ally", "neutral", "hostile"}:
                        raise RuntimeError(
                            f"relations.archetype_relations[{src!r}][{target_arch!r}] must be ally|neutral|hostile"
                        )
                    self.archetype_relations[src][str(target_arch)] = relation

        self.pair_relations = {}
        raw_pairs = relations.get("pairs", [])
        if not isinstance(raw_pairs, list):
            raise RuntimeError("relations.pairs must be a list")
        for idx, pair in enumerate(raw_pairs):
            if not isinstance(pair, dict):
                raise RuntimeError(f"relations.pairs[{idx}] must be an object")
            a = str(pair.get("a", "")).strip()
            b = str(pair.get("b", "")).strip()
            relation = pair.get("relation")
            if not a or not b:
                raise RuntimeError(f"relations.pairs[{idx}] requires non-empty a and b")
            if relation not in {"ally", "neutral", "hostile"}:
                raise RuntimeError(
                    f"relations.pairs[{idx}].relation must be ally|neutral|hostile"
                )
            if a not in self.factions or b not in self.factions:
                raise RuntimeError(
                    f"relations.pairs[{idx}] references unknown faction(s): {a!r}, {b!r}"
                )
            key = tuple(sorted((a, b)))
            self.pair_relations[key] = relation

        _interaction_log.debug(
            "Faction policy v2 loaded factions=%d archetypes=%d config=%s",
            len(self.factions),
            len(self.archetypes),
            path,
        )

    def resolve_faction(self, faction_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if faction_id is None:
            return None
        if faction_id in self.factions:
            return self.factions[faction_id]
        self._warn_unknown_team(str(faction_id))
        return None

    def resolve_relation(self, source_id: Optional[str], target_id: Optional[str]) -> str:
        if source_id is None or target_id is None:
            return self.relations_defaults["fallback"]
        source = self.resolve_faction(source_id)
        target = self.resolve_faction(target_id)
        if source is None or target is None:
            return self.relations_defaults["fallback"]
        if source_id == target_id:
            return self.relations_defaults["same_faction"]
        pair_key = tuple(sorted((source_id, target_id)))
        if pair_key in self.pair_relations:
            return self.pair_relations[pair_key]
        source_archetype = source["archetype"]
        target_archetype = target["archetype"]
        source_arch_rules = self.archetype_relations.get(source_archetype, {})
        if target_archetype in source_arch_rules:
            return source_arch_rules[target_archetype]
        target_arch_rules = self.archetype_relations.get(target_archetype, {})
        if source_archetype in target_arch_rules:
            return target_arch_rules[source_archetype]
        if source_archetype == target_archetype:
            return self.relations_defaults["same_archetype"]
        return self.relations_defaults["fallback"]

    def can_apply_damage(self, source_id: Optional[str], target_id: Optional[str], ctx: InteractionContext) -> bool:
        if ctx.kind != "damage":
            return True
        source = self.resolve_faction(source_id)
        target = self.resolve_faction(target_id)
        if source is None or target is None:
            return False
        relation = self.resolve_relation(source_id, target_id)
        damage_mode = source.get("damage_mode", "hostile_only")
        if damage_mode == "none":
            return False
        if damage_mode == "all":
            return True
        if damage_mode == "all_except_allies":
            return relation != "ally"
        return relation == "hostile"

    def should_aggro(self, source: Any, target: Any) -> bool:
        source_id = getattr(source, "team_id", None)
        target_id = getattr(target, "team_id", None)
        source_faction = self.resolve_faction(source_id)
        target_faction = self.resolve_faction(target_id)
        if source_faction is None or target_faction is None:
            return False
        relation = self.resolve_relation(source_id, target_id)
        aggro_mode = source_faction.get("aggro_mode", "hostile_only")
        if aggro_mode == "never":
            return False
        if aggro_mode == "all":
            return True
        if aggro_mode == "hostile_only":
            return relation == "hostile"
        if aggro_mode == "retaliate_only":
            retaliate_team = getattr(source, "retaliate_team_id", None)
            retaliate_until = getattr(source, "retaliate_until_ms", 0)
            return retaliate_team == target_id and retaliate_until > 0
        return relation == "hostile"

    def register_retaliation(self, target: Any, attacker_team: Optional[str], now_ms: int):
        if attacker_team is None:
            return
        target_team = getattr(target, "team_id", None)
        target_faction = self.resolve_faction(target_team)
        if target_faction is None:
            return
        if target_faction.get("aggro_mode") != "retaliate_only":
            return
        retaliation_window_ms = target_faction.get(
            "retaliation_window_ms",
            self.default_retaliation_window_ms,
        )
        setattr(target, "retaliate_team_id", attacker_team)
        setattr(target, "retaliate_until_ms", now_ms + retaliation_window_ms)


class InteractionResolver:
    def __init__(self, telemetry_sink: Any = None, faction_policy: Optional[FactionPolicy] = None):
        self.telemetry_sink = telemetry_sink
        self.faction_policy = faction_policy or FactionPolicy()

    def set_telemetry_sink(self, telemetry_sink: Any):
        self.telemetry_sink = telemetry_sink

    def set_faction_policy(self, faction_policy: FactionPolicy):
        self.faction_policy = faction_policy

    def is_known_team(self, team_id: Optional[str]) -> bool:
        if team_id is None:
            return False
        return self.faction_policy.resolve_faction(team_id) is not None

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

    def _record_prefilter(self, skipped: bool):
        sink = self.telemetry_sink
        if sink is not None and hasattr(sink, "record_interaction_prefilter"):
            sink.record_interaction_prefilter(skipped)

    def can_potentially_affect(self, source_team: Optional[str], target_team: Optional[str], kind: str = "damage") -> bool:
        if kind != "damage":
            return True
        probe_ctx = InteractionContext(kind="damage", source_kind="prefilter")
        allowed = self.faction_policy.can_apply_damage(source_team, target_team, probe_ctx)
        self._record_prefilter(skipped=not allowed)
        return allowed

    def can_team_interact(self, source_team: Optional[str], target_team: Optional[str], ctx: InteractionContext) -> bool:
        return self.faction_policy.can_apply_damage(source_team, target_team, ctx)

    def can_aggro(self, source: Any, target: Any) -> bool:
        allowed = self.faction_policy.should_aggro(source, target)
        self._record_aggro_check(allowed)
        return allowed

    def apply(self, ctx: InteractionContext) -> bool:
        self._record_emitted()
        target = ctx.target
        if target is None:
            _interaction_log.debug(
                "interaction reject reason=missing_target source_kind=%r source_team=%r kind=%r attack_type=%r amount=%r",
                ctx.source_kind,
                ctx.source_team,
                ctx.kind,
                ctx.attack_type,
                ctx.amount,
            )
            self._record_rejected_target()
            self._record_rejected_reason("missing_target")
            return False
        target_team = getattr(target, "team_id", None)
        if not self.can_team_interact(ctx.source_team, target_team, ctx):
            _interaction_log.debug(
                "interaction reject reason=team_policy source_kind=%r source_team=%r target_team=%r kind=%r attack_type=%r amount=%r",
                ctx.source_kind,
                ctx.source_team,
                target_team,
                ctx.kind,
                ctx.attack_type,
                ctx.amount,
            )
            self._record_rejected_team()
            self._record_rejected_reason("team_policy")
            return False
        if hasattr(target, "can_receive_interaction") and not target.can_receive_interaction(ctx):
            _interaction_log.debug(
                "interaction reject reason=target_gate source_kind=%r source_team=%r target_team=%r kind=%r attack_type=%r amount=%r",
                ctx.source_kind,
                ctx.source_team,
                target_team,
                ctx.kind,
                ctx.attack_type,
                ctx.amount,
            )
            self._record_rejected_target()
            self._record_rejected_reason("target_gate")
            return False
        if not hasattr(target, "receive_interaction"):
            _interaction_log.debug(
                "interaction reject reason=no_receive_interaction source_kind=%r source_team=%r target_team=%r kind=%r attack_type=%r amount=%r",
                ctx.source_kind,
                ctx.source_team,
                target_team,
                ctx.kind,
                ctx.attack_type,
                ctx.amount,
            )
            self._record_rejected_target()
            self._record_rejected_reason("no_receive_interaction")
            return False
        target.receive_interaction(ctx)
        # Neutral retaliation registration happens after a successful hostile damage interaction.
        if ctx.kind == "damage" and ctx.source_team is not None:
            self.faction_policy.register_retaliation(target, ctx.source_team, self._now_ms())
        _interaction_log.debug(
            "interaction resolved source_kind=%r source_team=%r target_team=%r kind=%r attack_type=%r amount=%r",
            ctx.source_kind,
            ctx.source_team,
            target_team,
            ctx.kind,
            ctx.attack_type,
            ctx.amount,
        )
        self._record_resolved(ctx)
        return True

    def _now_ms(self) -> int:
        try:
            import pygame  # local import to avoid hard dependency for non-game usages
            return pygame.time.get_ticks()
        except Exception:
            import time
            return int(time.time() * 1000)
