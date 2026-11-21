"""Temperature on a full body: layers that hold warmth, sources that pull them, one settle
(docs/damage/PLAN_temperature.md).

A body that `join`s keeps its skin and, when it wears a chest piece, that piece. The body's own
heat is a source on the skin; the air, lava and a hold are sources on the outer layer. Between two
events the layers follow the exact curve of `heat_network`. Every change settles first: the wound
since the last settle goes through the level's resolver, then the curve is solved again from the
values at that instant. Only the skin wounds. The level's wake queue (`tick`) brings a body back at
its next line crossing, or every `TICK_MS` while its skin is past a line; a body at rest has none.
"""
import heapq
import itertools

from damage_rules import (
    AIR_K, BODY_K, COLD_SCALE, COLD_SPEED, CONTACT_K, COOK, FAINT, HEAT_SCALE, HELD_MS, HURT_AT,
    INSULATION_MIN,
    PIECE_CAP, PIECE_CAP_MIN, REF_VIT, SLOW_AT, TICK_MS, chest_layer, cold_band, heat_shade,
    resist_of, shock_wound,
)
from heat_network import solve

SKIN, OUTER = "skin", "outer"
HORIZON_S = 120.0   # look this far ahead for the next crossing; past it, look again then
REST = 0.05         # a layer this close to its steady state is at rest: no wake
_HEAT_LINES = (FAINT, COOK, 10.0, 18.0)       # the faint red, then heat_shade's three reds
_COLD_LINES = (-SLOW_AT, -15.0, -20.0)        # cold_band's three blues
_WOUND_LINES = (COOK, -HURT_AT)
_seq = itertools.count()


class Warmth:
    """One full body's store. `values` were the layers' warmth at `since_ms`; `curve` carries them
    on. `paid_ms`: wounds are paid up to here; `owed`: the fraction of a point not yet sent."""

    __slots__ = ("level", "piece", "sources", "curve", "since_ms", "paid_ms", "owed", "gen")

    def __init__(self, level, now):
        self.level = level
        self.piece = None      # the worn chest LayerDef, None when naked
        self.sources = {}      # key -> (SKIN or OUTER, T, k, outside)
        self.curve = None
        self.since_ms = now
        self.paid_ms = now
        self.owed = 0.0
        self.gen = 0


# --- the public calls -------------------------------------------------------------------------

def join(body, level, now):
    """Give `body` a temperature: its own heat on the skin, the level's air on its outer layer."""
    state = Warmth(level, now)
    body.warmth = state
    state.piece = _worn_piece(body)
    state.sources["body"] = (SKIN, 0.0, 0.0, False)   # strength read live from vitality
    state.sources["air"] = (OUTER, float(getattr(level, "air", 0.0) or 0.0), AIR_K, True)
    _solve_from(body, state, [0.0] * _layers(state), now)
    _schedule(body, state, now)


def forget(body, now):
    """A dead body: its store goes, and every source it placed on others is taken off."""
    state = getattr(body, "warmth", None)
    if state is not None:
        state.gen += 1
        body.warmth = None
    placed = getattr(body, "warming", None)
    if placed:
        body.warming = {}
        for other, key in placed.values():
            remove_source(other, key, now)


def add_source(body, key, T, k, now, placed_by=None, layer=OUTER):
    """A source on `body` until removed. Outside sources are cut by the body's fire or ice resist.
    `placed_by` remembers it, so its death takes it off (`forget`)."""
    state = _state(body)
    if state is None:
        return

    def put():
        state.sources[key] = (layer, float(T), float(k), True)

    _change(body, state, now, put)
    if placed_by is not None:
        if getattr(placed_by, "warming", None) is None:
            placed_by.warming = {}
        placed_by.warming[(id(body), key)] = (body, key)


def remove_source(body, key, now, placed_by=None):
    state = _state(body)
    if placed_by is not None and getattr(placed_by, "warming", None):
        placed_by.warming.pop((id(body), key), None)
    if state is None or key not in state.sources:
        return
    def take():
        state.sources.pop(key, None)

    _change(body, state, now, take)


def bump(body, layer, amount, now):
    """A jump of `amount` on SKIN or OUTER (a blow, exertion). Returns the shock wound for the
    caller's price (the jump crossing 0 by at least HURT_AT); the heat itself wounds over time."""
    state = _state(body)
    if state is None or not amount:
        return 0.0
    shock = [0.0]

    def jump():
        values = _values(state, now)
        i = 0 if layer == SKIN else len(values) - 1
        before = values[i]
        values[i] = before + amount
        shock[0] = shock_wound(before, values[i])
        return values

    _change(body, state, now, None, new_values=jump)
    return shock[0]


def settle(body, now):
    """Bring the body to now: pay, paint, schedule. The wake queue calls it."""
    state = _state(body)
    if state is not None:
        _change(body, state, now, None)


def set_air(level, air, now, bodies):
    """The level's air, on each of `bodies` (the full bodies it holds)."""
    level.air = float(air)
    for body in bodies:
        add_source(body, "air", level.air, AIR_K, now)


def refresh(body, now):
    """What it wears changed: the outer layer, its capacity and its link follow. The skin keeps
    its warmth; a new piece starts at the skin's."""
    state = _state(body)
    if state is None:
        return

    def rewear():
        values = _values(state, now)
        state.piece = _worn_piece(body)
        return values[:1] + ([values[-1] if len(values) > 1 else values[0]] if state.piece else [])

    _change(body, state, now, None, new_values=rewear)


def skin(body, now):
    """The skin's warmth now (0 for a body without a store)."""
    state = _state(body)
    return 0.0 if state is None else _values(state, now)[0]


def outer(body, now):
    state = _state(body)
    return 0.0 if state is None else _values(state, now)[-1]


def tick(level, now):
    """Wake every body that is due. Stale entries (re-scheduled, dead) are skipped."""
    heap = getattr(level, "warmth_wakes", None)
    while heap and heap[0][0] <= now:
        _due, _seq, gen, body = heapq.heappop(heap)
        state = getattr(body, "warmth", None)
        if state is not None and state.gen == gen:
            settle(body, now)


# --- inside -----------------------------------------------------------------------------------

def _state(body):
    return getattr(body, "warmth", None)


def _worn_piece(body):
    layer = chest_layer(body)
    card = getattr(body, "body_def", None)
    natural = getattr(card, "natural", None)
    return None if layer is None or layer is natural else layer


def _layers(state):
    return 2 if state.piece is not None else 1


def _values(state, now):
    return state.curve.at((now - state.since_ms) / 1000.0)


def _resist(body):
    card = getattr(body, "body_def", None)
    return getattr(card, "resist", None) if card is not None else None


def _vitality(body):
    stats = getattr(body, "stats", None)
    value = stats.get("vitality") if isinstance(stats, dict) else None
    return float(value) if isinstance(value, (int, float)) and value > 0 else REF_VIT


def _solve_from(body, state, values, now):
    """The curve from `values` at `now`, with the sources as they are."""
    n = _layers(state)
    pull = [[0.0, 0.0] for _ in range(n)]
    resist = _resist(body)
    for where, T, k, outside in state.sources.values():
        if where == SKIN and not outside:
            k = BODY_K * _vitality(body) / REF_VIT   # the body's own heat, stronger with vitality
        if outside:
            if T > 0.0:
                T = max(0.0, T - resist_of(resist, "fire"))
            elif T < 0.0:
                T = min(0.0, T + resist_of(resist, "ice"))
        i = 0 if where == SKIN else n - 1
        pull[i][0] += k
        pull[i][1] += k * T
    capacity = [1.0]
    links = ()
    if n == 2:
        piece = state.piece
        capacity.append(max(PIECE_CAP_MIN, PIECE_CAP * float(piece.weight)))
        links = ((0, 1, CONTACT_K / max(INSULATION_MIN, float(piece.insulation))),)
    state.curve = solve(values, capacity, [tuple(p) for p in pull], links)
    state.since_ms = now


def _change(body, state, now, edit, new_values=None):
    """Pay to now, apply `edit` (sources) or `new_values` (a jump, a re-wear), solve, paint,
    schedule. A wound that kills ends it there."""
    _pay(body, state, now)
    if getattr(body, "warmth", None) is not state:
        return   # died of it
    if edit is not None:
        edit()
    values = new_values() if new_values is not None else _values(state, now)
    _solve_from(body, state, values, now)
    _paint(body, state, now)
    _schedule(body, state, now)


def _pay(body, state, now):
    """The skin's time past COOK or -HURT_AT since `paid_ms`, through the resolver in whole points."""
    if now <= state.paid_ms:
        return
    t0 = (state.paid_ms - state.since_ms) / 1000.0
    t1 = (now - state.since_ms) / 1000.0
    curve = state.curve
    heat = HEAT_SCALE * curve.area_past(0, COOK, t0, t1)
    cold = COLD_SCALE * curve.area_past(0, -HURT_AT, t0, t1, above=False)
    state.paid_ms = now
    state.owed += heat + cold
    whole = int(state.owed)
    if whole <= 0:
        return
    state.owed -= whole
    resolver = getattr(state.level, "interaction_resolver", None)
    if resolver is None:
        return
    from Interaction import InteractionContext
    resolver.apply(InteractionContext(
        kind="damage", source_kind="temperature", source_team="environment", target=body,
        amount=whole, attack_type="heat" if heat >= cold else "cold", tags={"temperature"},
    ))


def _paint(body, state, now):
    """Red on the outer layer from FAINT, blue and the slow on the skin from -SLOW_AT."""
    from hit_resolve import _clock, remember_heat
    values = _values(state, now)
    outer_value, skin_value = values[-1], values[0]
    clock = _clock(body)
    shade = heat_shade(outer_value) or ("faint" if outer_value > FAINT else None)
    layer = state.piece if state.piece is not None else getattr(getattr(body, "body_def", None), "natural", None)
    # A condition starts only when the shade changes: a settle is not a new entry on the clock.
    if shade is not None:
        if shade != getattr(body, "heat_shade", None) and clock is not None:
            clock.start(body, "hot_shell", now, duration_ms=HELD_MS)
        body.heat_shade = shade
        remember_heat(body, layer, shade)
    elif getattr(body, "heat_shade", None) is not None:
        body.heat_shade = None
        body.heat_piece = None
        body.heat_on_skin = False
        if clock is not None:
            clock.cure(body, "hot_shell")
    band = cold_band(-skin_value)
    if band is not None:
        if band != getattr(body, "cold_shade", None) and clock is not None:
            clock.start(body, "chilled", now, strength=COLD_SPEED[band], duration_ms=HELD_MS)
        body.cold_shade = band
    elif getattr(body, "cold_shade", None) is not None:
        body.cold_shade = None
        if clock is not None:
            clock.cure(body, "chilled")


def _schedule(body, state, now):
    """The next instant this body needs looking at: a line crossing, the next wound tick, or the
    horizon while it is still moving. At rest and safe: nothing."""
    curve = state.curve
    t0 = (now - state.since_ms) / 1000.0
    skin_value = curve.layer_at(0, t0)
    when = None
    if skin_value > COOK or skin_value < -HURT_AT:
        when = now + TICK_MS
    last = len(curve.steady) - 1
    lines_by_layer = {0: _COLD_LINES + _WOUND_LINES}
    lines_by_layer[last] = lines_by_layer.get(last, ()) + _HEAT_LINES
    moving = False
    for i, lines in lines_by_layer.items():
        if curve.reach(i, t0) <= REST:
            continue
        moving = True
        found = curve.first_crossing(i, lines, t0, t0 + HORIZON_S)
        if found is not None:
            at = state.since_ms + int(found * 1000.0) + 1
            when = at if when is None else min(when, at)
    if when is None and moving:
        when = now + int(HORIZON_S * 1000)
    if when is None:
        return
    heap = getattr(state.level, "warmth_wakes", None)
    if heap is None:
        heap = state.level.warmth_wakes = []
    state.gen += 1
    heapq.heappush(heap, (int(when), next(_seq), state.gen, body))
