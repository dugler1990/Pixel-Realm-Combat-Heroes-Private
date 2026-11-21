"""How a blow meets layers (damage chunk 5) and how fire, cold and lightning land (chunk 7).

No pygame: the card and the resolver share this. `physical` and `elemental` do not mutate the
attack or the layers, and `elemental` does not search the world. Venom and wear are not here
(chunks 8, 10). A pierce that stops deals no wound, only a bruise from the force that arrived;
a point that gets through deals its full damage (partial penetration is later).
"""
from __future__ import annotations

import math

from damage_data import CATEGORIES

BRUISE_SCALE = 0.05  # force that becomes health. 2 is a speck; 120 still shows. Tune in play.


class Physical:
    """amount: the wound before rounding. bruise: health from the force that arrived.
    reached_flesh: a pierce got through the last layer (venom, chunk 8, will read this).
    stopped_at: the layer a pierce stopped on; None if it went through or was not a pierce."""

    __slots__ = ("amount", "bruise", "reached_flesh", "stopped_at")

    def __init__(self, amount, bruise, reached_flesh, stopped_at):
        self.amount = amount
        self.bruise = bruise
        self.reached_flesh = reached_flesh
        self.stopped_at = stopped_at

    def __repr__(self):
        return (f"Physical(amount={self.amount:g}, bruise={self.bruise:g}, "
                f"flesh={self.reached_flesh}, stopped={self.stopped_at!r})")


def landed(result):
    """The int subtracted from health: the blow, then the elemental wound, each rounded."""
    extra = getattr(result, "elemental_wound", 0.0) or 0.0
    return int(round(result.amount + result.bruise)) + int(round(extra))


def _cushion(layers):
    product = 1.0
    for layer in layers:
        product *= 1.0 - layer.absorb
    return product


def _bruise(force, layers):
    return force * _cushion(layers) * BRUISE_SCALE


def physical(delivery, damage, penetration, force, layers):
    """One blow against `layers` (outer first, the hide last).

    pierce: stop where penetration cannot beat stopping_power. crush and blast: no stop,
    the wound and the force are both cut by every layer's absorb.
    """
    if delivery == "pierce":
        pen = penetration
        met = []
        for layer in layers:
            met.append(layer)
            if pen - layer.stopping_power <= 0:
                return Physical(0.0, _bruise(force, met), False, layer)
            pen = pen - layer.stopping_power
        return Physical(float(damage), _bruise(force, met), True, None)
    if delivery in ("crush", "blast"):
        return Physical(float(damage) * _cushion(layers), _bruise(force, layers), False, None)
    raise ValueError(f"unknown delivery {delivery!r}")


# --- fire, cold, lightning (damage chunk 7) ------------------------------------------------------
# First numbers. A weakness is stored and clamped: chunk 9 drops the clamp.

CATCH = 0.5
COOK = 5.0
HEAT_K = 0.25
HEAT_SCALE = 0.25
BURN_MS = 6000

COLD_K = 0.02
BASE_CON = 10.0
SLOW_AT = 10.0
HURT_AT = 12.0
WET_COLD = 8.0
COLD_SPEED = {"mild": -1, "medium": -2, "severe": -3}
SIMPLE_COLD = {"mild": (2000, 0), "medium": (4000, 4), "severe": (6000, 8)}

WET_MULT = 1.5
WET_CARRY = 0.4


class Elemental:
    """wound: health, before rounding. starts: (name, strength or None, duration_ms).
    heat_shade / cold_shade: warm|hot|searing and mild|medium|severe, or None.
    passed_charge / passed_reach: set when the bolt may hop; the caller does the search."""

    __slots__ = ("wound", "starts", "heat_shade", "cold_shade", "passed_charge", "passed_reach")

    def __init__(self, wound, starts, heat_shade, cold_shade, passed_charge, passed_reach):
        self.wound = wound
        self.starts = starts
        self.heat_shade = heat_shade
        self.cold_shade = cold_shade
        self.passed_charge = passed_charge
        self.passed_reach = passed_reach

    def __repr__(self):
        return (f"Elemental(wound={self.wound:g}, starts={self.starts!r}, "
                f"heat={self.heat_shade!r}, cold={self.cold_shade!r})")


def resist_of(resist, name):
    """max(0, the category plus its parent). Negatives are stored and not used yet."""
    resist = resist or {}
    own = float(resist.get(name, 0) or 0)
    parent = CATEGORIES.parent.get(name)
    extra = float(resist.get(parent, 0) or 0) if parent else 0.0
    return max(0.0, own + extra)


def heat_shade(H):
    """Three reds. None at or below COOK."""
    if H > 18:
        return "searing"
    if H > 10:
        return "hot"
    if H > COOK:
        return "warm"
    return None


def heat_wound(H):
    """The cook, solved once. 0 at or below COOK."""
    if H <= COOK:
        return 0.0
    arc = H - COOK - COOK * math.log(H / COOK)
    return arc * (HEAT_SCALE / HEAT_K)


def heat_seconds(H):
    """Seconds a shell stays hot. 0 at or below COOK."""
    if H <= COOK:
        return 0.0
    return math.log(H / COOK) / HEAT_K


def cold_band(sticks):
    """Three blues. None below SLOW_AT."""
    if sticks >= 20:
        return "severe"
    if sticks >= 15:
        return "medium"
    if sticks >= SLOW_AT:
        return "mild"
    return None


def cold_wound(sticks, constitution):
    """Health from cold, the area under the curve until it warms past HURT_AT. Solved once."""
    if sticks <= HURT_AT:
        return 0.0
    rate = COLD_K * constitution
    return (sticks - HURT_AT - HURT_AT * math.log(sticks / HURT_AT)) / rate


def cold_seconds(sticks, constitution):
    """Seconds until cold falls under SLOW_AT. 0 when it never rose above that line."""
    if sticks <= SLOW_AT:
        return 0.0
    return math.log(sticks / SLOW_AT) / (COLD_K * constitution)


def bolt_body(charge, conductivity, wet, resist, origin_damage, reach):
    """One body a bolt has just hit. Returns (wound, passed charge, next reach px)."""
    charge = max(0.0, charge - max(0.0, resist))
    wound = charge * (1.0 + conductivity) * (WET_MULT if wet else 1.0)
    if conductivity > 0:
        passed = charge * conductivity
    elif wet:
        passed = charge * WET_CARRY
    else:
        passed = 0.0
    next_reach = reach * (passed / origin_damage) if origin_damage else 0.0
    return wound, passed, next_reach


def bolt_chain(damage, reach, arcs, spark, bodies, full):
    """Wounds along a bolt. `bodies` is (distance from the one just hit, conductivity, wet, resist),
    near to far; the first is the body the bolt already struck. Full may spend every arc. Simple
    jumps at most once. No world, no quadtree."""
    arcs_left = arcs if full else min(1, arcs)
    wounds = []
    charge = damage
    hop_reach = reach
    first = True
    for distance, conductivity, wet, resist in bodies:
        if first:
            wound, charge, hop_reach = bolt_body(charge, conductivity, wet, resist, damage, reach)
            wounds.append(wound)
            first = False
            continue
        if arcs_left <= 0 or charge < spark or hop_reach <= 0 or distance > hop_reach:
            break
        arcs_left -= 1
        wound, charge, hop_reach = bolt_body(charge, conductivity, wet, resist, damage, reach)
        wounds.append(wound)
    return wounds


def _sticks(cold, resist, constitution, wet):
    stuck = max(0.0, cold - resist_of(resist, "ice")) * BASE_CON / constitution
    if wet:
        stuck += WET_COLD
    return stuck


def elemental(fire=0, cold=0, bolt=None, layer=None, resist=None, constitution=BASE_CON,
              wet=False, full=True):
    """Fire, then cold, then the lightning on the body just hit. Pure: no search.

    `layer` is the one the hit met (flammability, insulation, conductivity). `resist` is the
    body's map (may be negative). `bolt` is a Lightning, or None. Missing constitution is 10.
    """
    resist = resist or {}
    constitution = constitution if constitution and constitution > 0 else BASE_CON
    flamm = 0.0 if layer is None else layer.flammability
    insulation = 0.0 if layer is None else layer.insulation
    conductivity = 0.0 if layer is None else layer.conductivity
    wound = 0.0
    starts = []
    heat = None

    power = max(0.0, fire - resist_of(resist, "fire"))
    if power > 0 and flamm >= CATCH:
        wound += power
        heat = "searing"
        starts.append(("burning", None, BURN_MS))
    elif power > 0:
        H = power * (1.0 - insulation)
        heat = heat_shade(H)
        if H > COOK:
            wound += heat_wound(H)
            starts.append(("hot_shell", None, int(round(heat_seconds(H) * 1000))))

    sticks = _sticks(cold, resist, constitution, wet) if cold else 0.0
    band = cold_band(sticks)
    cold_shade = None
    if band is not None:
        if full:
            seconds = cold_seconds(sticks, constitution)
            if seconds > 0:
                cold_shade = band
                wound += cold_wound(sticks, constitution)
                starts.append(("chilled", COLD_SPEED[band], int(round(seconds * 1000))))
        else:
            duration_ms, shade_wound = SIMPLE_COLD[band]
            duration_ms = int(round(duration_ms * BASE_CON / constitution))
            if duration_ms > 0:
                cold_shade = band
                wound += shade_wound
                starts.append(("chilled", COLD_SPEED[band], duration_ms))

    passed_charge = None
    passed_reach = None
    if bolt is not None and bolt.damage > 0:
        hit, passed, nxt = bolt_body(
            bolt.damage, conductivity, wet, resist_of(resist, "lightning"), bolt.damage, bolt.reach,
        )
        wound += hit
        arcs_left = bolt.arcs if full else min(1, bolt.arcs)
        if arcs_left > 0 and passed >= bolt.spark and nxt > 0:
            passed_charge = passed
            passed_reach = nxt

    return Elemental(wound, tuple(starts), heat, cold_shade, passed_charge, passed_reach)


def chest_layer(entity):
    """The outer layer on the chest, or the hide when nothing is worn. None when there is no card."""
    defence = getattr(entity, "defence", None)
    card = getattr(entity, "body_def", None)
    if card is None and defence is not None:
        card = defence.body
    if card is None:
        return None
    if defence is None or not defence.worn:
        return card.natural
    from defence_profile import region_slot
    layers = defence.layers_at(region_slot("chest"))
    return layers[0] if layers else card.natural


def patch_rate(entity, heat):
    """Health per second while standing in a heat patch. Does not read fire_resistance."""
    layer = chest_layer(entity)
    card = getattr(entity, "body_def", None)
    if card is None and getattr(entity, "defence", None) is not None:
        card = entity.defence.body
    resist = resist_of(card.resist, "fire") if card is not None else 0.0
    insulation = 0.0 if layer is None else layer.insulation
    return max(0.0, heat - resist) * (1.0 - insulation)


# --- one warmth (temperature plan) --------------------------------------------------------------
# The air, a blow, a hold and exertion write the same number. These functions do not see an entity.

AIR_K = 0.01
FAINT = 2.0
EXERT = 0.15
REF_VIT = 20.0
SAFE_LO = -HURT_AT
SAFE_HI = COOK


class Warmth:
    """One sample. `value` at `at_ms`, falling toward `target` with rate `k`. `quiet_ms` is the
    instant a prepaid spike has finished falling back inside the safe band; the integral skips
    that fall so the blow's cook is not paid twice."""

    __slots__ = ("value", "at_ms", "target", "k", "quiet_ms")

    def __init__(self, value=0.0, at_ms=0, target=0.0, k=AIR_K, quiet_ms=0):
        self.value = float(value)
        self.at_ms = int(at_ms)
        self.target = float(target)
        self.k = float(k)
        self.quiet_ms = int(quiet_ms)


def air_on_skin(air, resist, insulation, vitality):
    """The warmth the skin is pulled toward. Resist, then clothes, then vitality. Nowhere else."""
    air = float(air or 0.0)
    vitality = float(vitality) if isinstance(vitality, (int, float)) and not isinstance(vitality, bool) and vitality > 0 else REF_VIT
    cover = min(1.0, max(0.0, float(insulation or 0.0)))
    if air >= 0.0:
        power = max(0.0, air - resist_of(resist, "fire"))
    else:
        power = -max(0.0, -air - resist_of(resist, "ice"))
    return power * (1.0 - cover) * (REF_VIT / vitality)


def warmth_shade(value):
    """Faint red under COOK, the three reds above it, the three blues below -SLOW_AT."""
    value = float(value)
    if value > 0.0:
        if value > 18.0:
            return "searing"
        if value > 10.0:
            return "hot"
        if value > COOK:
            return "warm"
        if value > FAINT:
            return "faint"
        return None
    return cold_band(-value)


def shock_wound(before, after):
    """A jump that crosses 0 by at least HURT_AT. The cook curve of that distance.
    Landing on 0 counts. Starting at 0 does not: there was no other side to leave."""
    before = float(before)
    after = float(after)
    crossed = (before < 0.0 and after >= 0.0) or (after < 0.0 and before > 0.0)
    if not crossed:
        return 0.0
    distance = abs(after - before)
    if distance >= HURT_AT:
        return heat_wound(distance)
    return 0.0


def warmth_at(sample, now_ms):
    """The sample's value at `now_ms`. The exponential toward its target."""
    if sample is None:
        return 0.0
    elapsed = max(0.0, (int(now_ms) - int(sample.at_ms)) / 1000.0)
    if sample.k <= 0.0 or elapsed == 0.0:
        return sample.value
    return sample.target + (sample.value - sample.target) * math.exp(-sample.k * elapsed)


def _cross_s(value, target, k, line):
    """Seconds until the curve hits `line`, or None when it never does."""
    if k <= 0.0:
        return None
    gap = value - target
    if abs(gap) < 1e-12:
        return None
    ratio = (line - target) / gap
    if ratio <= 0.0 or ratio >= 1.0:
        return None
    return -math.log(ratio) / k


def _segment_heat(value, target, k, a, b):
    """HEAT_SCALE times the area of (warmth - COOK) on [a, b] seconds, where it is positive."""
    return _segment_over(value, target, k, a, b, COOK) * HEAT_SCALE


def _segment_cold(value, target, k, a, b):
    """Area of (-warmth - HURT_AT) on [a, b] seconds, where it is positive."""
    return _segment_over(-value, -target, k, a, b, HURT_AT)


def _segment_over(value, target, k, a, b, line):
    """Area of (curve - line) while the curve of `value` toward `target` stays above `line`."""
    if b <= a:
        return 0.0
    start = target + (value - target) * math.exp(-k * a)
    end = target + (value - target) * math.exp(-k * b)
    above = start > line or end > line
    if not above and not (start > line and end < line):
        if max(start, end) <= line:
            return 0.0
    cross = _cross_s(value, target, k, line)
    if cross is not None and a < cross < b:
        if start > line:
            return _area(value, target, k, a, cross, line)
        return _area(value, target, k, cross, b, line)
    if start <= line and end <= line:
        return 0.0
    return _area(value, target, k, a, b, line)


def _area(value, target, k, a, b, line):
    """Integral of (target + (value-target) e^{-kt} - line) from a to b. Caller clipped the span."""
    if k <= 0.0:
        return max(0.0, value - line) * (b - a)
    gap = value - target
    return (target - line) * (b - a) - (gap / k) * (math.exp(-k * b) - math.exp(-k * a))


def wound_between(sample, t0_ms, t1_ms):
    """Health from sitting past COOK or HURT_AT between two instants. Solved, not stepped.
    A prepaid spike's fall back into the safe band is skipped."""
    if sample is None or t1_ms <= t0_ms:
        return 0.0
    start = max(int(t0_ms), int(sample.quiet_ms))
    if t1_ms <= start:
        return 0.0
    origin = int(sample.at_ms)
    a = max(0.0, (start - origin) / 1000.0)
    b = max(a, (int(t1_ms) - origin) / 1000.0)
    return _segment_heat(sample.value, sample.target, sample.k, a, b) + _segment_cold(
        sample.value, sample.target, sample.k, a, b)


def spike_quiet_ms(value, target, k, now_ms):
    """When a spike that started at `value` falls back inside the safe band. 0 if it never does."""
    if SAFE_LO < target < SAFE_HI and (value >= SAFE_HI or value <= SAFE_LO):
        line = COOK if value > 0.0 else -HURT_AT
        seconds = _cross_s(value, target, k, line)
        if seconds is not None and seconds > 0.0:
            return int(now_ms) + int(round(seconds * 1000.0))
    return 0


# Lines the clock cares about. The one just inside the blue is how a hold at -SLOW_AT is seen to leave.
_WAKE_LINES = (FAINT, COOK, -SLOW_AT, -(SLOW_AT - 0.5), -HURT_AT)


def wake_ms(sample, now_ms, min_gap_ms=50, horizon_ms=120_000):
    """The next time this sample crosses a line or owes a point of health. None when it is quiet.
    `value` is the value at `now_ms` (the caller sampled first). Not a per-frame step."""
    if sample is None:
        return None
    now_ms = int(now_ms)
    best = None
    for line in _WAKE_LINES:
        seconds = _cross_s(sample.value, sample.target, sample.k, line)
        if seconds is None or seconds <= 0.0:
            continue
        at = now_ms + int(round(seconds * 1000.0))
        if best is None or at < best:
            best = at
    if sample.quiet_ms > now_ms and (best is None or sample.quiet_ms < best):
        best = int(sample.quiet_ms)
    owed = _wound_at(sample, now_ms, horizon_ms)
    if owed is not None and (best is None or owed < best):
        best = owed
    if best is None:
        return None
    return max(best, now_ms + int(min_gap_ms))


def _wound_at(sample, now_ms, horizon_ms):
    """When the solved integral from now first reaches 1 health. None inside the horizon if it never does."""
    end = int(now_ms) + int(horizon_ms)
    if wound_between(sample, now_ms, end) < 1.0:
        return None
    lo, hi = int(now_ms), end
    while hi - lo > 20:
        mid = (lo + hi) // 2
        if wound_between(sample, now_ms, mid) >= 1.0:
            hi = mid
        else:
            lo = mid
    return hi
