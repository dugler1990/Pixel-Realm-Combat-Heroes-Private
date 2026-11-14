"""What the item card says, as text rows: no pygame. inventory_view.py draws them.

Everything comes from the item's base (item_properties.base_of) and the property rows (item_properties.PROPERTIES):
no stat text is written by hand. An item with no base (the old items) shows its name and description only.

Card, top to bottom: name; type line (slot · weight class · set); verdicts (empty for now: they will come from
the shared rule function, item_card.plan.md chunk 2); the property lines in row order (covers, cost, ...,
durability); flavour. The detail view: every property as a raw number.
"""
from __future__ import annotations

from dataclasses import dataclass

import equipment
import item_properties as P

KIND_LABEL = {"helmet": "Helmet", "armor": "Chest", "shoulder": "Shoulder", "arm": "Arm", "legs": "Leg",
              "boots": "Boot", "waist": "Waist"}
SIDE_LABEL = {"l": "left", "r": "right"}


@dataclass(frozen=True)
class Card:
    name: str
    type_line: str = ""
    verdicts: tuple = ()      # "Stops darts, arrows" ... from the rule function (next chunk); nothing typed
    lines: tuple = ()
    flavour: str = ""
    detail: tuple = ()        # (label, value as text) for every property of the base


def item_name(item):
    name = getattr(item, "name", None)
    if name:
        return name
    return str(getattr(item, "item_id", "?")).replace("_", " ").capitalize()


def slot_label(item):
    worn = equipment.wearable(item)
    if worn is None:
        return ""
    kind, side = worn
    label = KIND_LABEL.get(kind, kind.capitalize())
    return f"{label} ({SIDE_LABEL[side]})" if side in SIDE_LABEL else label


def type_line(item, base):
    parts = [slot_label(item)]
    worn = equipment.wearable(item)
    if worn is not None and base.get("weight") is not None:
        parts.append(P.weight_class(worn[0], base["weight"]).capitalize())
    if base.get("set"):
        parts.append(f"{base['set'].capitalize()} set")
    return " · ".join(p for p in parts if p)


def property_lines(item, base):
    rows = []
    for prop in P.PROPERTIES:
        if prop.card != "line" or prop.id not in base or not P.shown(prop, base[prop.id]):
            continue
        v = base[prop.id]
        fields = {"v": P.format_value(prop, v)}
        if "{now}" in prop.template:                  # the item's own value (item.durability); None: as new
            now = getattr(item, prop.id, None)
            fields["now"] = P.format_value(prop, v if now is None else now)
        rows.append(prop.template.format(**fields))
    return tuple(rows)


def state(item):
    """The item's own values the card shows (durability now): the card is remade when they change."""
    return tuple(getattr(item, p.id, None) for p in P.PROPERTIES if "{now}" in p.template)


def detail_lines(base):
    return tuple((p.label, P.format_value(p, base[p.id])) for p in P.PROPERTIES if p.id in base)


def build(item):
    """The card for one item."""
    base = P.base_of(item)
    if base is None:
        return Card(item_name(item), flavour=getattr(item, "description", "") or "")
    return Card(name=base.get("name") or item_name(item), type_line=type_line(item, base),
                lines=property_lines(item, base), flavour=base.get("flavour", "") or "",
                detail=detail_lines(base))
