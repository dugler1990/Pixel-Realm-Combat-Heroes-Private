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

# Temperature on a full body (temperature.py, docs/damage/PLAN_temperature.md). First numbers,
# tuned from tools/temperature_table.py to the plan's feel targets (2026-11-21). Strengths are
# per second; capacity 1 is the skin's. A desert is air +10, sun 1; an ice field air -30.
AIR_K = 0.02          # the air on the outer layer
LAVA_K = 0.2          # a lava patch on the outer layer while you stand in it (its heat is the T)
WARM_K = 0.02         # the thermostat warming a cold skin, at vitality REF_VIT, armour or not
SWEAT_K = 0.02        # the thermostat cooling a warm skin, at REF_VIT, times the bare share
REST_HEAT = 0.02      # heat the body makes at rest, per second on the skin
SUN_K = 0.1           # heat per second on the outer layer per point of sun, times its sun_absorb
REF_VIT = 20.0
CONTACT_K = 0.08      # piece to skin, divided by the piece's insulation (insulation is resistance)
INSULATION_MIN = 0.01  # a piece with no insulation is all but bare skin
PIECE_CAP = 0.05      # a piece's capacity per weight (plate chest 12: 0.6)
PIECE_CAP_MIN = 0.1
FAINT = 2.0           # faint red from here to COOK
COLD_SCALE = 2.0      # health per second per point of skin below -HURT_AT
HOT_SCALE = 2.0       # health per second per point of skin above COOK (a blow's cook keeps HEAT_SCALE)
TICK_MS = 500         # while the skin is past a line, the wound arrives this often
HELD_MS = 86_400_000  # hot_shell / chilled while temperature holds them: until it clears them
HEAT_PER_STAMINA = 0.02  # warmth on the skin per point of stamina spent (a slide, 20: 0.4)

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


def shock_wound(before, after):
    """A jump that crosses 0 by at least HURT_AT: the cook of that distance. Landing on 0 counts;
    starting at 0 does not (there was no other side to leave)."""
    crossed = (before < 0.0 <= after) or (after < 0.0 < before)
    distance = abs(after - before)
    return heat_wound(distance) if crossed and distance >= HURT_AT else 0.0


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


def cold_sticks(cold, resist, constitution, wet):
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

    sticks = cold_sticks(cold, resist, constitution, wet) if cold else 0.0
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
