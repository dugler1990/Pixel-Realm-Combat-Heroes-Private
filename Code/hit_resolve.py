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


def skin_tint(entity):
    """Blue on the skin while chilled. Red on the skin only when the hide itself is hot."""
    if entity is None:
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
    """Red on the piece that heated. Everything else stays white, including skin under a plate."""
    if entity is None or getattr(entity, "heat_piece", None) != name:
        return WHITE
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
