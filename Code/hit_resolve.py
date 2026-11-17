"""Turn a damage context into the int the receiver subtracts (damage chunk 5). No pygame.

Reads the attack def and the target's defence profile. A body that wears nothing stays on its
hide and never looks up a region. Magic-only blows (no delivery) are left alone for chunk 7.
"""
from __future__ import annotations

import defence_profile
from damage_rules import physical


def resolve(ctx):
    """A Physical result, or None when this hit keeps the amount it arrived with."""
    attack = getattr(ctx, "attack_def", None)
    if getattr(ctx, "kind", None) != "damage" or attack is None or not attack.delivery:
        return None
    target = ctx.target
    body = getattr(target, "body_def", None)
    defence = getattr(target, "defence", None)
    if body is None or defence is None:
        return None
    return physical(attack.delivery, _damage(ctx, attack), attack.penetration, attack.force,
                    _layers(target, defence, ctx))


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


def _layers(target, defence, ctx):
    """Outer first, the hide last. Unarmoured: the hide, no lookup. No pixel (a blast): the
    chest stack. A points hit: the piece drawn at the pixel, then the other pieces on that
    region; a skin pixel is the hide only. Capsules and a sprite hero: the region's stack."""
    natural = target.body_def.natural
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
