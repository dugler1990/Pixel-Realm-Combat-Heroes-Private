"""Turn a damage context into the int the receiver subtracts (damage chunks 5 and 7).

Reads the attack def and the target's body card. No card: the hit keeps the amount it arrived
with. A card: the blow, then fire, cold and lightning. Holy and unholy add nothing. A body that
wears nothing stays on its hide and never looks up a region. Lightning hops only after a hit,
and only as many times as the bolt's arcs allow.
"""
from __future__ import annotations

import defence_profile
from damage_data import CATEGORIES, Lightning
from damage_rules import elemental, physical


class _Priced:
    """A blow plus the elemental wound. `landed` rounds each and adds them."""

    __slots__ = ("amount", "bruise", "reached_flesh", "stopped_at", "elemental", "elemental_wound")

    def __init__(self, amount, bruise, elemental, reached_flesh=False, stopped_at=None):
        self.amount = amount
        self.bruise = bruise
        self.reached_flesh = reached_flesh
        self.stopped_at = stopped_at
        self.elemental = elemental
        self.elemental_wound = 0.0 if elemental is None else elemental.wound


def resolve(ctx):
    """A priced hit, or None when this hit keeps the amount it arrived with.

    No body card: None. Holy or unholy alone: None, so today's amount stays. Fire, cold or
    lightning: a result, even when the resist brings the wound to 0.
    """
    attack = getattr(ctx, "attack_def", None)
    if getattr(ctx, "kind", None) != "damage" or attack is None:
        return None
    if not attack.delivery and not _has_element(attack):
        return None
    target = ctx.target
    defence = getattr(target, "defence", None)
    card = _card(target, defence)
    if card is None or defence is None:
        return None
    layers = _layers(target, defence, ctx, card)
    phys = None
    if attack.delivery:
        phys = physical(attack.delivery, _damage(ctx, attack), attack.penetration, attack.force, layers)
    element = _element_for(ctx, attack, card, layers[0]) if _has_element(attack) else None
    if element is None:
        return phys
    if phys is None:
        return _Priced(0.0, 0.0, element)
    return _Priced(phys.amount, phys.bruise, element, phys.reached_flesh, phys.stopped_at)


def _damage(ctx, attack):
    """The hookup's amount when it set one (a monster's own damage, a blast's falloff);
    otherwise the def's damage plus the attacker's stat. The stat never raises penetration."""
    if ctx.amount is not None:
        return float(ctx.amount)
    damage = float(attack.damage)
    stat = attack.scales_with
    stats = getattr(ctx.source, "stats", None) if ctx.source is not None else None
    if stat and isinstance(stats, dict) and stat in stats:
        damage += float(stats[stat])
    return damage


def _center(body):
    if body is None:
        return None
    box = getattr(body, "hitbox", None)
    if box is None:
        box = getattr(body, "rect", None)
    if box is None:
        return None
    return box.center


def _toward(ctx):
    """The attack's travel on the ground: the shot's movement, else source to target.
    None: the torso counts as chest."""
    toward = getattr(ctx, "toward", None)
    if toward is not None:
        return toward
    origin, dest = _center(ctx.source), _center(ctx.target)
    if origin is None or dest is None:
        return None
    return (dest[0] - origin[0], dest[1] - origin[1])


def _layers(target, defence, ctx, card):
    """Outer first, the hide last. Unarmoured: the hide, no lookup. No pixel (a blast): the
    chest stack. A points hit: the piece drawn at the pixel, then the other pieces on that
    region; a skin pixel is the hide only. Capsules and a sprite hero: the region's stack."""
    natural = card.natural
    if not defence.worn:
        return (natural,)
    if ctx.contact is None:
        return defence.layers_at(defence_profile.region_slot("chest"))
    import body_regions

    spot = body_regions.hit_layers(target, ctx.contact, _toward(ctx))
    if spot.point is None:
        return spot.layers
    if spot.piece is None or len(spot.layers) < 2:
        return (natural,)
    front = spot.layers[0]
    rest = tuple(layer for layer in defence.layers_at(spot.slot) if layer is not front)
    return (front,) + rest


# --- fire, cold, lightning on the hit -----------------------------------------------------------

WHITE = (1.0, 1.0, 1.0, 1.0)
HEAT_TINT = {
    "faint": (1.0, 0.86, 0.80, 1.0),
    "warm": (1.0, 0.72, 0.62, 1.0),
    "hot": (1.0, 0.32, 0.22, 1.0),
    "searing": (1.0, 0.08, 0.04, 1.0),
}
COLD_TINT = {
    "mild": (0.78, 0.86, 1.0, 1.0),
    "medium": (0.55, 0.70, 1.0, 1.0),
    "severe": (0.32, 0.48, 1.0, 1.0),
}


def _card(target, defence):
    card = getattr(target, "body_def", None)
    if card is None and defence is not None:
        card = defence.body
    return card


def _has_element(attack):
    if attack.cold or attack.lightning is not None:
        return True
    fire = CATEGORIES.ids["fire"]
    return any(cat == fire for cat, _power in attack.magic)


def _stat(attack, source):
    stat = attack.scales_with
    stats = getattr(source, "stats", None) if source is not None else None
    if stat and isinstance(stats, dict) and stat in stats:
        return float(stats[stat])
    return 0.0


def _wet(target, card):
    if card is not None and "wet" in card.starts:
        return True
    conds = getattr(target, "conditions", None)
    if not conds:
        return False
    from conditions import condition
    return condition("wet").id in conds


def _constitution(target):
    stats = getattr(target, "stats", None)
    if isinstance(stats, dict):
        value = stats.get("constitution")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    from damage_rules import BASE_CON
    return BASE_CON


def _element_for(ctx, attack, card, layer):
    extra = _stat(attack, ctx.source)
    fire = 0.0
    fire_id = CATEGORIES.ids["fire"]
    for cat, power in attack.magic:
        if cat == fire_id:
            fire = power + extra
    cold = (attack.cold + extra) if attack.cold else 0.0
    bolt = attack.lightning
    if bolt is not None:
        bolt = Lightning(bolt.damage + extra, bolt.reach, bolt.arcs, bolt.spark)
    return elemental(
        fire=fire, cold=cold, bolt=bolt, layer=layer, resist=card.resist,
        constitution=_constitution(ctx.target), wet=_wet(ctx.target, card),
        full=getattr(ctx.target, "detail", "simple") == "full",
    )


def _level_of(entity):
    level = getattr(entity, "level", None)
    if level is None:
        combat = getattr(entity, "combat_context", None)
        if isinstance(combat, dict):
            level = combat.get("level")
    return level


def _clock(entity):
    level = _level_of(entity)
    return getattr(level, "condition_clock", None) if level is not None else None


def remember_heat(entity, layer, shade):
    """Store which draw goes red. The skin draw, only when the hide itself heated."""
    entity.heat_shade = shade
    natural = getattr(getattr(entity, "body_def", None), "natural", None)
    entity.heat_on_skin = layer is not None and layer is natural
    entity.heat_piece = None
    if entity.heat_on_skin or layer is None:
        return
    for name, piece_layer in (getattr(entity, "piece_layers", None) or {}).items():
        if piece_layer is layer:
            entity.heat_piece = name
            return


def _has_condition(entity, name):
    conds = getattr(entity, "conditions", None)
    if not conds:
        return False
    from conditions import condition
    return condition(name).id in conds


def _ticks():
    try:
        import pygame
        return int(pygame.time.get_ticks())
    except Exception:
        return 0


def _sample_shade(sample, now=None):
    """(shade, True) when this body keeps a sample. (None, False) when it does not."""
    if sample is None:
        return None, False
    from damage_rules import warmth_at, warmth_shade
    return warmth_shade(warmth_at(sample, _ticks() if now is None else now)), True


def skin_tint(entity):
    """Blue from the skin's warmth. Red on the skin only when the hide itself is hot.
    A stored warmth wins over the condition, so a faint red and a fading blue can share a body."""
    if entity is None:
        return WHITE
    shade, stored = _sample_shade(getattr(entity, "_skin", None))
    if stored:
        if shade in COLD_TINT:
            return COLD_TINT[shade]
        if shade in HEAT_TINT and getattr(entity, "heat_on_skin", False):
            return HEAT_TINT[shade]
        return WHITE
    if _has_condition(entity, "chilled"):
        shade = getattr(entity, "cold_shade", None)
        if shade in COLD_TINT:
            return COLD_TINT[shade]
    if getattr(entity, "heat_on_skin", False) and (
            _has_condition(entity, "hot_shell") or _has_condition(entity, "burning")):
        return HEAT_TINT.get(getattr(entity, "heat_shade", None), WHITE)
    return WHITE


def piece_tint(entity, name):
    """Red on the piece that heated, including the faint red under COOK. Skin under a plate stays
    on `skin_tint`."""
    if entity is None or getattr(entity, "heat_piece", None) != name:
        return WHITE
    shade, stored = _sample_shade(getattr(entity, "_piece", None))
    if stored:
        return HEAT_TINT.get(shade, WHITE)
    if not (_has_condition(entity, "hot_shell") or _has_condition(entity, "burning")):
        return WHITE
    return HEAT_TINT.get(getattr(entity, "heat_shade", None), WHITE)


def _grant(entity, name, now, strength, duration_ms):
    clock = _clock(entity)
    if clock is None:
        return
    clock.start(entity, name, now, strength=strength, duration_ms=duration_ms)


def apply_element(ctx, priced, now):
    """Start what the rule returned, tint the layer, and spend lightning hops. No clock: the
    wound still lands (the caller set the amount) and the condition does not."""
    element = getattr(priced, "elemental", None)
    if element is None:
        return
    target = ctx.target
    attack = ctx.attack_def
    if element.cold_shade:
        target.cold_shade = element.cold_shade
    elif attack is not None and attack.cold and _clock(target) is not None:
        _clock(target).cure(target, "chilled")
        target.cold_shade = None
    defence = getattr(target, "defence", None)
    card = _card(target, defence)
    if element.heat_shade and defence is not None and card is not None:
        remember_heat(target, _layers(target, defence, ctx, card)[0], element.heat_shade)
    for name, strength, duration_ms in element.starts:
        _grant(target, name, now, strength, duration_ms)
    _store_temperature(ctx, now)
    _hop(ctx, element)


def _hop(ctx, element):
    """One query per hop, the nearest body not already in this bolt. Full spends every arc.
    Simple was already capped to one hop by the rule."""
    if element.passed_charge is None:
        return
    attack = ctx.attack_def
    bolt = None if attack is None else attack.lightning
    if bolt is None:
        return
    level = _level_of(ctx.target)
    tree = getattr(getattr(level, "layout_manager", None), "entity_quad_tree", None)
    sprites = getattr(getattr(level, "layout_manager", None), "visible_sprites", None)
    resolver = getattr(level, "interaction_resolver", None)
    if tree is None or sprites is None or resolver is None:
        return
    from Interaction import InteractionContext
    from damage_rules import bolt_body, chest_layer, resist_of

    already = {id(ctx.target)}
    charge = element.passed_charge
    reach = element.passed_reach
    origin = bolt.damage + _stat(attack, ctx.source)
    arcs_left = bolt.arcs if getattr(ctx.target, "detail", "simple") == "full" else min(1, bolt.arcs)
    while arcs_left > 0 and charge >= bolt.spark and reach > 0:
        nxt = _nearest(tree, sprites, ctx.target, reach, already)
        if nxt is None:
            return
        already.add(id(nxt))
        arcs_left -= 1
        card = _card(nxt, getattr(nxt, "defence", None))
        layer = chest_layer(nxt)
        conductivity = 0.0 if layer is None else layer.conductivity
        resist = resist_of(card.resist, "lightning") if card is not None else 0.0
        wound, charge, reach = bolt_body(
            charge, conductivity, _wet(nxt, card), resist, origin, bolt.reach,
        )
        resolver.apply(InteractionContext(
            kind="damage", source=ctx.source, source_kind=ctx.source_kind,
            source_team=ctx.source_team, target=nxt, amount=int(round(wound)),
            attack_type=ctx.attack_type,
        ))


def _nearest(tree, sprites, origin, reach, already):
    box = getattr(origin, "hitbox", None) or getattr(origin, "rect", None)
    if box is None:
        return None
    import pygame
    query = pygame.Rect(box.centerx - reach, box.centery - reach, reach * 2, reach * 2)
    by_id = {s.id: s for s in sprites.sprites() if hasattr(s, "id")}
    from hashRect import HashableRect
    best = None
    best_d = None
    ox, oy = box.center
    for hit in tree.hit(HashableRect(query, -1)):
        ent = by_id.get(hit._id)
        if ent is None or id(ent) in already:
            continue
        if _card(ent, getattr(ent, "defence", None)) is None:
            continue
        other = getattr(ent, "hitbox", None) or getattr(ent, "rect", None)
        if other is None:
            continue
        dx = other.centerx - ox
        dy = other.centery - oy
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= reach and (best_d is None or dist < best_d):
            best, best_d = ent, dist
    return best


# --- one warmth on a full body ------------------------------------------------------------------
# Simple bodies do not come here. They keep `apply_element` and `elemental`.

_HOLD_REFRESH_MS = 5000
_CHILL_MS = 6000


def _full(entity):
    return getattr(entity, "detail", "simple") == "full"


def _vitality(entity):
    stats = getattr(entity, "stats", None)
    if isinstance(stats, dict):
        value = stats.get("vitality", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    from damage_rules import REF_VIT
    return REF_VIT


def _air(entity):
    level = _level_of(entity)
    if level is None:
        return 0.0
    air = getattr(level, "air", 0.0)
    return 0.0 if air is None else float(air)


def _insulation(entity):
    from damage_rules import chest_layer
    layer = chest_layer(entity)
    if layer is None:
        return 0.0
    return min(1.0, max(0.0, float(layer.insulation or 0.0)))


def _resist(entity):
    card = _card(entity, getattr(entity, "defence", None))
    return {} if card is None else card.resist


def _piece_k(insulation):
    """Stored heat leaves more slowly under the chest's outer layer. Naked is HEAT_K."""
    from damage_rules import AIR_K, HEAT_K
    return max(AIR_K, HEAT_K * (1.0 - insulation))


def _blank(now, target, k):
    from damage_rules import Warmth
    return Warmth(0.0, now, target, k, 0)


def _aim(sample, value, target, k, now):
    """Write the sampled value and, when the pull changes, drop a quiet window that no longer fits."""
    changed = abs(sample.target - target) > 1e-9 or abs(sample.k - k) > 1e-12
    sample.value = float(value)
    sample.at_ms = int(now)
    sample.target = float(target)
    sample.k = float(k)
    if changed:
        sample.quiet_ms = 0
    return sample


def temper(entity, now_ms=None, blow_heat=0.0, on_skin=False, exert_add=0.0, pay_cook=True,
           heated_layer=None):
    """Advance one full body's warmth to now. A blow pays its own cook, plus a shock when the
    jump crosses 0. The air, a hold and lava are the sample's target. Returns the wound and
    subtracts it. A simple body is left untouched."""
    if not _full(entity):
        return 0.0
    from damage_rules import (
        AIR_K, COOK, COLD_SPEED, HEAT_K, HURT_AT, SLOW_AT, air_on_skin, cold_wound, heat_wound,
        shock_wound, spike_quiet_ms, warmth_at, warmth_shade, wound_between, wake_ms,
    )

    now = _ticks() if now_ms is None else int(now_ms)
    insulation = _insulation(entity)
    # The air the body actually reaches. The piece does not keep a second copy of it.
    reached = air_on_skin(_air(entity), _resist(entity), insulation, _vitality(entity))
    skin_pull = -SLOW_AT if getattr(entity, "_ghost_hold", False) else reached
    lava = getattr(entity, "_lava_heat", None)
    # Lava uses the blow's rate so standing in it heats. Clothes only slow heat that is already stored.
    piece_k = HEAT_K if lava is not None else _piece_k(insulation)
    piece_pull = float(lava) if lava is not None else reached

    skin = getattr(entity, "_skin", None)
    piece = getattr(entity, "_piece", None)
    if skin is None or piece is None:
        skin = _blank(now, skin_pull, AIR_K)
        piece = _blank(now, piece_pull, piece_k)
        entity._skin = skin
        entity._piece = piece

    wound = 0.0
    if now > skin.at_ms:
        wound += wound_between(skin, skin.at_ms, now)
        wound += wound_between(piece, piece.at_ms, now)
    live_skin = warmth_at(skin, now)
    live_piece = warmth_at(piece, now)

    blow_heat = float(blow_heat or 0.0)
    exert_add = float(exert_add or 0.0)
    if on_skin and blow_heat:
        before, live_skin = live_skin, live_skin + blow_heat
        wound += _blow_cost(blow_heat, before, live_skin, pay_cook, entity, heat_wound, cold_wound, shock_wound, COOK, HURT_AT)
        shocked = (before, live_skin, True)
    elif blow_heat:
        before, live_piece = live_piece, live_piece + blow_heat
        wound += _blow_cost(blow_heat, before, live_piece, pay_cook, entity, heat_wound, cold_wound, shock_wound, COOK, HURT_AT)
        shocked = (before, live_piece, False)
    else:
        shocked = None
    if exert_add:
        live_skin += exert_add

    from damage_rules import FAINT
    # Nothing stored: the piece stays put. A hot piece fades toward the air it reached, not a second bill.
    if lava is None and live_piece <= FAINT and not (blow_heat > FAINT and not on_skin):
        piece_pull = 0.0
    # A warmer piece delays the skin: the skin chases the plate while the plate is spent.
    buffering = live_piece > live_skin and live_piece > skin_pull
    if buffering:
        skin_target, skin_k = live_piece, AIR_K
        if getattr(entity, "_ghost_hold", False) and lava is None:
            piece_pull = skin_pull
            piece_k = _piece_k(insulation)
    else:
        skin_target, skin_k = skin_pull, AIR_K

    _aim(skin, live_skin, skin_target, skin_k, now)
    _aim(piece, live_piece, piece_pull, piece_k, now)

    # The ghost is a constant mild cold while he is on you, unless the plate is still warmer.
    if (getattr(entity, "_ghost_hold", False) and not buffering and lava is None
            and blow_heat == 0.0 and exert_add == 0.0):
        skin.value = float(skin_pull)
        skin.target = float(skin_pull)

    if shocked is not None:
        sample = skin if shocked[2] else piece
        sample.quiet_ms = spike_quiet_ms(sample.value, sample.target, sample.k, now)

    if wound and getattr(entity, "health", None) is not None:
        entity.health -= wound
    _paint(entity, now, heated_layer, warmth_shade, COLD_SPEED)
    _schedule(entity, now, wake_ms)
    return wound


def _blow_cost(blow_heat, before, after, pay_cook, entity, heat_wound, cold_wound, shock_wound, COOK, HURT_AT):
    """The blow's own cook, not shrunk by what was already stored, plus the shock of the jump."""
    cost = shock_wound(before, after)
    if not pay_cook:
        return cost
    if blow_heat > COOK:
        cost += heat_wound(blow_heat)
    elif blow_heat < -HURT_AT:
        cost += cold_wound(-blow_heat, _constitution(entity))
    return cost


def _paint(entity, now, heated_layer, warmth_shade, cold_speed):
    """Colour and the small slow follow the live number. Burning cloth is left alone."""
    piece_shade = warmth_shade(entity._piece.value)
    skin_shade = warmth_shade(entity._skin.value)
    heat_names = ("faint", "warm", "hot", "searing")
    if piece_shade in heat_names:
        entity.heat_shade = piece_shade
        if heated_layer is not None:
            remember_heat(entity, heated_layer, piece_shade)
        elif not getattr(entity, "heat_piece", None) and not getattr(entity, "heat_on_skin", False):
            from damage_rules import chest_layer
            remember_heat(entity, chest_layer(entity), piece_shade)
    elif skin_shade in heat_names:
        entity.heat_shade = skin_shade
        entity.heat_on_skin = True
        entity.heat_piece = None
    elif not (_has_condition(entity, "burning") or _has_condition(entity, "hot_shell")):
        entity.heat_shade = None
        entity.heat_piece = None
        entity.heat_on_skin = False

    if skin_shade in cold_speed:
        entity.cold_shade = skin_shade
        _grant(entity, "chilled", now, cold_speed[skin_shade], _CHILL_MS)
    elif getattr(entity, "cold_shade", None) is not None or _has_condition(entity, "chilled"):
        entity.cold_shade = None
        clock = _clock(entity)
        if clock is not None:
            clock.cure(entity, "chilled")


def _schedule(entity, now, wake_ms):
    clock = _clock(entity)
    if clock is None or not hasattr(entity, "id"):
        return
    due = []
    for sample in (entity._skin, entity._piece):
        at = wake_ms(sample, now)
        if at is not None:
            due.append(at)
    if getattr(entity, "_ghost_hold", False):
        due.append(now + _HOLD_REFRESH_MS)
    if not due:
        return
    clock.schedule_warmth(entity, min(due))


def exert(entity, paid, now_ms=None):
    """Stamina spent, as heat on the skin. `paid` is what `pay` will hand over when the branches meet.
    This branch does not call `pay`."""
    if not _full(entity):
        return 0.0
    from damage_rules import EXERT
    return temper(entity, now_ms, exert_add=float(paid) * EXERT)


def set_ghost_hold(entity, holding, now_ms=None):
    """While a cold melee body is inside his own reach. Leaving clears it. One call per change."""
    if not _full(entity):
        return 0.0
    holding = bool(holding)
    if getattr(entity, "_ghost_hold", False) == holding and getattr(entity, "_skin", None) is not None:
        return 0.0
    entity._ghost_hold = holding
    return temper(entity, now_ms)


def set_lava(entity, heat, now_ms=None):
    """The patch's heat becomes the piece's target. None stops the feed. A simple body never arrives."""
    if not _full(entity):
        return 0.0
    if heat is not None:
        heat = float(heat)
    prev = getattr(entity, "_lava_heat", None)
    if prev == heat and getattr(entity, "_skin", None) is not None:
        return 0.0
    entity._lava_heat = heat
    return temper(entity, now_ms)


def _store_temperature(ctx, now):
    """A fire or ice blow on a full body. The cook is already on the hit; this adds the shock
    and the store. Caught cloth burns and does not become stored heat."""
    target = ctx.target
    if not _full(target):
        return
    attack = ctx.attack_def
    defence = getattr(target, "defence", None)
    card = _card(target, defence)
    if attack is None or card is None or defence is None:
        return
    layer = _layers(target, defence, ctx, card)[0]
    extra = _stat(attack, ctx.source)
    fire = 0.0
    fire_id = CATEGORIES.ids["fire"]
    for cat, power in attack.magic:
        if cat == fire_id:
            fire = power + extra
    from damage_rules import CATCH, _sticks, resist_of
    power = max(0.0, fire - resist_of(card.resist, "fire"))
    if power > 0.0 and (layer.flammability or 0.0) < CATCH:
        heat = power * (1.0 - (layer.insulation or 0.0))
        if heat > 0.0:
            temper(target, now, blow_heat=heat, on_skin=layer is card.natural, pay_cook=False,
                    heated_layer=layer)
    cold = (attack.cold + extra) if attack.cold else 0.0
    if cold:
        sticks = _sticks(cold, card.resist, _constitution(target), _wet(target, card))
        if sticks > 0.0:
            temper(target, now, blow_heat=-sticks, on_skin=True, pay_cook=False)
