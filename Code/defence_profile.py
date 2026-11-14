"""What is between a hit and the flesh, per body region (damage chunk 4).

A DefenceProfile holds, for each region slot (head, chest, `upper_arm l`, ...), the layers a hit
there meets, outer first, the body's natural layer last; and the weight of what is worn. A body
that wears nothing shares one profile per body def (natural_profile). The hero's is rebuilt on
every equip (Player.refresh_equipment), never per frame. Nothing reads it for damage yet: chunk 5.

Regions are item_properties.REGIONS. Arms and legs come in a left and a right slot ("l" is the
wearer's own left); a worn piece covers its own side, a piece with no side covers both. Where two
pieces cover one region, the harder one (higher stopping_power) is outside. No pygame here.
"""
from __future__ import annotations

import equipment
import item_properties
from damage_data import DamageDataError, layer_def

SIDED = frozenset(("upper_arm", "forearm", "hand", "thigh", "shin", "foot"))
SIDES = ("l", "r")

SLOTS = tuple(
    (region, side)
    for region in item_properties.REGIONS
    for side in (SIDES if region in SIDED else (None,))
)
SLOT = {key: i for i, key in enumerate(SLOTS)}

_BASE_FIELDS = item_properties.IDENTITY + ("coverage",)


def region_slot(region, side=None):
    """The int slot of a region; arms and legs need their side ("l" / "r")."""
    try:
        return SLOT[(region, side if region in SIDED else None)]
    except KeyError:
        raise KeyError(f"no region slot {region!r} side {side!r}") from None


class DefenceProfile:
    """layers[slot]: tuple of LayerDefs, outer first, the natural one last. Shared: never change one;
    build a new one (wear, chunk 10, will copy on write)."""

    __slots__ = ("body", "layers", "weight", "worn")

    def __init__(self, body, layers, weight, worn):
        self.body = body
        self.layers = layers
        self.weight = weight
        self.worn = worn          # False: natural layer only everywhere (the fast path)

    def layers_at(self, slot):
        return self.layers[slot]

    def __repr__(self):
        return f"DefenceProfile({self.body.name!r}, worn={self.worn}, weight={self.weight:g})"


_NATURAL = {}
_BASE_LAYERS = {}


def natural_profile(body_def):
    """The one shared profile of a body that wears nothing; None for no body def."""
    if body_def is None:
        return None
    profile = _NATURAL.get(body_def.id)
    if profile is None:
        only = (body_def.natural,)
        profile = DefenceProfile(body_def, (only,) * len(SLOTS), 0.0, False)
        _NATURAL[body_def.id] = profile
    return profile


def base_layer(base_id, base):
    """The LayerDef of an item base (item_bases.json), made once per base id."""
    layer = _BASE_LAYERS.get(base_id)
    if layer is None:
        layer = layer_def(base_id, base, f"{item_properties.BASES_PATH}: base {base_id!r}",
                          extra=_BASE_FIELDS)
        _BASE_LAYERS[base_id] = layer
    return layer


def _covered_slots(base_id, base, side):
    coverage = base.get("coverage") or ()
    slots = []
    for region in coverage:
        if region not in item_properties.REGIONS:
            raise DamageDataError(f"{item_properties.BASES_PATH}: base {base_id!r}: unknown region {region!r}")
        for s in ((side,) if side else SIDES) if region in SIDED else (None,):
            slots.append(SLOT[(region, s)])
    return slots


def build_profile(body_def, worn):
    """The profile of `body_def` wearing `worn`: (base id, base dict, side or None) per piece."""
    pieces = list(worn)
    if not pieces:
        return natural_profile(body_def)
    per_slot = [[] for _ in SLOTS]
    weight = 0.0
    for base_id, base, side in pieces:
        layer = base_layer(base_id, base)
        weight += layer.weight
        for slot in _covered_slots(base_id, base, side):
            per_slot[slot].append(layer)
    natural = body_def.natural
    layers = tuple(
        tuple(sorted(found, key=lambda l: -l.stopping_power)) + (natural,)
        for found in per_slot
    )
    return DefenceProfile(body_def, layers, weight, True)


def worn_from_items(items):
    """(base id, base, side) for each worn item with a base; weapons, belts without a base and
    empty slots add nothing."""
    worn = []
    for item in items:
        slot = equipment.wearable(item)
        if slot is None:
            continue
        base = item_properties.base_of(item)
        if base is None:
            continue
        worn.append((item.base, base, slot[1]))
    return worn
