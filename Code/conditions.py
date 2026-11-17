"""Conditions and buffs (damage chunk 6, docs/damage/NOTES_damage_and_armour.md).

Read once at import from config/damage/conditions.json. A condition has a start and an end. The level
owns one ConditionClock and peeks its heap once a frame. A buff adds to a stat while it is read;
nothing writes the stat and subtracts later. No pygame here.
"""
import heapq
import json
import os
import random

from damage_data import DamageDataError

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "damage")
CONDITIONS_PATH = os.path.join(CONFIG_DIR, "conditions.json")
SCHEMA_VERSION = 1

_ROW_FIELDS = frozenset(("kind", "stat", "amount", "duration_ms", "stack"))
_KINDS = frozenset(("buff",))
_STACKS = frozenset(("refresh",))
# Names a buff may add to. A row that names anything else fails the load.
STATS = frozenset((
    "health", "energy", "attack", "magic", "speed",
    "strength", "intelligence", "agility", "charisma", "vitality",
))


class ConditionDef:
    """One condition def. Shared: never change one after load."""

    __slots__ = ("id", "name", "kind", "stat", "amount", "duration_ms", "stack")

    def __init__(self, id, name, kind, stat, amount, duration_ms, stack):
        self.id = id
        self.name = name
        self.kind = kind
        self.stat = stat
        self.amount = amount
        self.duration_ms = duration_ms
        self.stack = stack

    def __repr__(self):
        return f"ConditionDef({self.name!r})"


class Instance:
    """One condition on one body. `gen` dies with it, so curing it leaves its heap entry stale."""

    __slots__ = ("cond_id", "gen", "start_ms", "end_ms", "strength")

    def __init__(self, cond_id, gen, start_ms, end_ms, strength):
        self.cond_id = cond_id
        self.gen = gen
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.strength = strength


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DamageDataError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise DamageDataError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    return data


def _number(where, field, value, whole=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise DamageDataError(f"{where}: {field} must be a number >= 0, got {value!r}")
    if whole and isinstance(value, float):
        raise DamageDataError(f"{where}: {field} must be a whole number of ms, got {value!r}")
    return value


def _condition_def(path, cond_id, name, row):
    where = f"{path}: condition {name!r}"
    if not isinstance(row, dict):
        raise DamageDataError(f"{where}: must be an object")
    unknown = set(row) - _ROW_FIELDS
    if unknown:
        raise DamageDataError(f"{where}: unknown field(s) {sorted(unknown)}")
    kind = row.get("kind")
    if kind not in _KINDS:
        raise DamageDataError(f"{where}: unknown kind {kind!r}")
    if "stat" not in row or row["stat"] is None:
        raise DamageDataError(f"{where}: a buff needs a stat")
    stat = row["stat"]
    if stat not in STATS:
        raise DamageDataError(f"{where}: unknown stat {stat!r}")
    stack = row.get("stack")
    if stack not in _STACKS:
        raise DamageDataError(f"{where}: unknown stack {stack!r}")
    amount = _number(where, "amount", row.get("amount"))
    duration_ms = _number(where, "duration_ms", row.get("duration_ms"), whole=True)
    return ConditionDef(cond_id, name, kind, stat, amount, duration_ms, stack)


def load_conditions(path=CONDITIONS_PATH):
    """The condition defs in file order; ids are 0..n-1."""
    data = _read(path)
    rows = data.get("conditions")
    if not isinstance(rows, dict):
        raise DamageDataError(f"{path}: conditions must be a name -> row map")
    return [
        _condition_def(path, cond_id, name, row)
        for cond_id, (name, row) in enumerate(rows.items())
    ]


CONDITIONS = load_conditions()
_BY_NAME = {d.name: d for d in CONDITIONS}
_BY_ID = CONDITIONS


def condition(name):
    """The shared ConditionDef called `name`. KeyError naming it when there is none."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"no condition {name!r}") from None


def bonus(entity, stat, defs=None):
    """Sum of the strength of live buffs on `stat`. No conditions: 0, and nothing is allocated."""
    conds = getattr(entity, "conditions", None)
    if not conds:
        return 0
    table = CONDITIONS if defs is None else defs
    total = 0
    for inst in conds.values():
        defn = table[inst.cond_id]
        if defn.kind == "buff" and defn.stat == stat:
            total += inst.strength
    return total


def speed_of(entity):
    """The speed to move at: the stat, plus any live haste. With no buff this is the stat."""
    return entity.stats["speed"] + bonus(entity, "speed")


def save_succeeds(rng, stat, difficulty):
    """A d20 plus the stat, against the difficulty. Nothing in play calls this yet."""
    return rng.randrange(1, 21) + stat >= difficulty


def notify_death(entity):
    """Drop every condition on `entity` when its level has a clock. No clock: nothing to drop."""
    level = getattr(entity, "level", None)
    if level is None:
        ctx = getattr(entity, "combat_context", None)
        if isinstance(ctx, dict):
            level = ctx.get("level")
    clock = getattr(level, "condition_clock", None) if level is not None else None
    if clock is not None:
        clock.on_death(entity)


class ConditionClock:
    """One heap for a level. The head is the next end. A stale entry (cured, refreshed, dead, gone) is skipped."""

    def __init__(self, seed=0, defs=None):
        self.defs = tuple(defs) if defs is not None else CONDITIONS
        self.by_name = {d.name: d for d in self.defs}
        self.rng = random.Random(seed)
        self._heap = []
        self._seq = 0

    def _defn(self, name):
        try:
            return self.by_name[name]
        except KeyError:
            raise KeyError(f"no condition {name!r}") from None

    def _ensure(self, entity):
        if not hasattr(entity, "conditions"):
            entity.conditions = {}
        if not hasattr(entity, "condition_gen"):
            entity.condition_gen = 0

    def _push(self, entity, inst):
        self._seq += 1
        heapq.heappush(
            self._heap,
            (inst.end_ms, self._seq, entity.id, entity.condition_gen, inst.cond_id, inst.gen),
        )

    def start(self, entity, name, now, strength=None, duration_ms=None):
        """Put `name` on `entity`. Already there: refresh the end and the strength (the old entry goes stale)."""
        defn = self._defn(name)
        self._ensure(entity)
        prev = entity.conditions.get(defn.id)
        gen = 1 if prev is None else prev.gen + 1
        inst = Instance(
            defn.id,
            gen,
            now,
            now + (defn.duration_ms if duration_ms is None else duration_ms),
            defn.amount if strength is None else strength,
        )
        entity.conditions[defn.id] = inst
        self._push(entity, inst)
        return inst

    def tick(self, now, entity_id_map):
        """Pop ends that are due. Empty heap: return. A match deletes that one instance."""
        heap = self._heap
        if not heap:
            return
        while heap and heap[0][0] <= now:
            _due, _seq, entity_id, body_gen, cond_id, inst_gen = heapq.heappop(heap)
            entity = entity_id_map.get(entity_id)
            if entity is None or getattr(entity, "condition_gen", None) != body_gen:
                continue
            inst = entity.conditions.get(cond_id)
            if inst is None or inst.gen != inst_gen:
                continue
            del entity.conditions[cond_id]

    def cure(self, entity, name):
        """Drop that one condition. Its gen dies with it; every other condition on the body keeps running."""
        defn = self._defn(name)
        self._ensure(entity)
        entity.conditions.pop(defn.id, None)

    def on_death(self, entity):
        """Every entry for this life is stale, and the dict is clear."""
        self._ensure(entity)
        entity.condition_gen += 1
        entity.conditions.clear()

    def bonus(self, entity, stat):
        return bonus(entity, stat, self.defs)

    def speed_of(self, entity):
        return speed_of(entity)

    def records(self, entity):
        """`(cond_id, start_ms, end_ms, strength)` for each live condition, in id order."""
        self._ensure(entity)
        rows = [
            (inst.cond_id, inst.start_ms, inst.end_ms, inst.strength)
            for inst in entity.conditions.values()
        ]
        rows.sort()
        return tuple(rows)

    def apply_records(self, entity, records, now):
        """Clear and start again from `records`, scheduling each end. Same numbers, same bonus."""
        self._ensure(entity)
        entity.condition_gen += 1
        entity.conditions.clear()
        for cond_id, start_ms, end_ms, strength in records:
            inst = Instance(cond_id, 1, start_ms, end_ms, strength)
            entity.conditions[cond_id] = inst
            self._push(entity, inst)
