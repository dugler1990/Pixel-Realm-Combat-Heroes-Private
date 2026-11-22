"""Venom on a body (damage chunk 8, docs/damage/PLAN_venom_holy.md).

A venom is a row of data (`config/damage/venoms.json`): phases of damage per second and stat
debuffs, a health floor, a save, how much a class cure works. A body holds `venoms`: name -> Dose.
A pierce that reached flesh `start`s one (immune bodies and a passed save shrug it off; another
dose raises the strength). The level's wake queue (`tick`) settles each poisoned body every
TICK_MS: the damage since the last settle goes through the resolver, never below the venom's
floor; a venom past its last phase ends. Debuffs are read by `conditions.bonus` (`debuff`).
`cure` lowers the strength by venom or by class. Healing does not touch it.
"""
import heapq
import itertools

from conditions import STATS, save_succeeds
from damage_data import VENOMS

TICK_MS = 500
IMMUNE = 100.0
_EPS = 1e-6
_seq = itertools.count()

for _v in VENOMS.values():
    for _ms, _dps, _debuffs in _v.phases:
        for _stat in _debuffs:
            if _stat not in STATS:
                raise ValueError(f"venom {_v.name!r}: debuff on unknown stat {_stat!r}")


class Dose:
    """One venom on one body: when it started, its strength, paid up to `paid_ms`, the owed fraction."""

    __slots__ = ("start_ms", "strength", "paid_ms", "owed")

    def __init__(self, now):
        self.start_ms = now
        self.strength = 0.0
        self.paid_ms = now
        self.owed = 0.0


def level_of(body):
    level = getattr(body, "level", None)
    if level is None:
        combat = getattr(body, "combat_context", None)
        if isinstance(combat, dict):
            level = combat.get("level")
    return level


def start(body, name, dose, now, rng=None):
    """A dose of `name` reached flesh. Returns True when the venom is on the body after it.
    Immune (`resist` venom or its class at 100): nothing. First dose: the vitality save (with an
    rng; none: no save). Already there: settle, then the strength rises (up to max_dose)."""
    defn = VENOMS[name]
    resist = _resist(body)
    if float(resist.get("venom", 0)) >= IMMUNE:
        return False
    cut = min(1.0, max(0.0, float(resist.get(defn.cls, 0)) / IMMUNE))
    if cut >= 1.0:
        return False
    venoms = _venoms(body)
    held = venoms.get(name)
    if held is None:
        if rng is not None and save_succeeds(rng, _vitality(body), defn.save):
            return False
        held = Dose(now)
        venoms[name] = held
    else:
        settle(body, now)
    held.strength = min(defn.max_dose, held.strength + dose * (1.0 - cut))
    _schedule(body, now)
    return True


def settle(body, now):
    """Pay every venom up to now (one resolver hit), end the ones past their last phase."""
    venoms = getattr(body, "venoms", None)
    if not venoms:
        return
    health = float(getattr(body, "health", 0) or 0)
    total = 0
    for name, held in list(venoms.items()):
        defn = VENOMS[name]
        held.owed += _area(defn, held.paid_ms - held.start_ms, now - held.start_ms) * held.strength
        held.paid_ms = now
        whole = int(held.owed)
        held.owed -= whole
        take = max(0, min(whole, int(health - defn.floor)))
        health -= take
        total += take
        if now - held.start_ms >= defn.length_ms:
            del venoms[name]
    if total > 0:
        resolver = getattr(level_of(body), "interaction_resolver", None)
        if resolver is not None:
            from Interaction import InteractionContext
            resolver.apply(InteractionContext(
                kind="damage", source_kind="venom", source_team="environment", target=body,
                amount=total, attack_type="venom", tags={"venom"},
            ))


def debuff(body, stat):
    """What the running venoms add to `stat` now (as of the last settle): the phase's debuff times
    the strength, summed."""
    venoms = getattr(body, "venoms", None)
    if not venoms:
        return 0.0
    total = 0.0
    for name, held in venoms.items():
        phase = _phase_at(VENOMS[name], held.paid_ms - held.start_ms)
        if phase is not None:
            total += phase[2].get(stat, 0) * held.strength
    return total


def cure(body, cures, now):
    """A cure item's list: each {"venom": name} or {"class": name}, with a "strength" share (1:
    ends it). A class cure's share is times the venom's class_cure."""
    venoms = getattr(body, "venoms", None)
    if not venoms:
        return
    settle(body, now)
    for entry in cures:
        share = float(entry.get("strength", 1.0))
        for name, held in list(venoms.items()):
            defn = VENOMS[name]
            if entry.get("venom") == name:
                cut = share
            elif entry.get("class") == defn.cls:
                cut = share * defn.class_cure
            else:
                continue
            held.strength *= max(0.0, 1.0 - cut)
            if held.strength <= _EPS:
                del venoms[name]


def forget(body):
    """A dead body: every venom goes, its wake is stale."""
    if getattr(body, "venoms", None):
        body.venoms = {}
    body.venom_wake = None


def tick(level, now):
    """Settle every body that is due, and wake it again while a venom runs."""
    heap = getattr(level, "venom_wakes", None)
    while heap and heap[0][0] <= now:
        due, _s, body = heapq.heappop(heap)
        if getattr(body, "venom_wake", None) != due:
            continue
        body.venom_wake = None
        settle(body, now)
        _schedule(body, now)


# --- inside -----------------------------------------------------------------------------------

def _venoms(body):
    venoms = getattr(body, "venoms", None)
    if venoms is None:
        venoms = {}
        body.venoms = venoms
    return venoms


def _resist(body):
    card = getattr(body, "body_def", None)
    return (getattr(card, "resist", None) or {}) if card is not None else {}


def _vitality(body):
    stats = getattr(body, "stats", None)
    return float(stats.get("vitality", 0) or 0) if isinstance(stats, dict) else 0.0


def _phase_at(defn, t):
    for phase in defn.phases:
        if t < phase[0]:
            return phase
        t -= phase[0]
    return None


def _area(defn, t0, t1):
    """Damage per second integrated from t0 to t1 ms after the start (strength 1)."""
    total = 0.0
    edge = 0.0
    for ms, dps, _debuffs in defn.phases:
        a, b = max(t0, edge), min(t1, edge + ms)
        if b > a:
            total += dps * (b - a) / 1000.0
        edge += ms
    return total


def _schedule(body, now):
    if not getattr(body, "venoms", None) or getattr(body, "venom_wake", None) is not None:
        return
    level = level_of(body)
    if level is None:
        return
    if getattr(level, "venom_wakes", None) is None:
        level.venom_wakes = []
    due = now + TICK_MS
    body.venom_wake = due
    heapq.heappush(level.venom_wakes, (due, next(_seq), body))
