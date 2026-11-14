"""Item properties: one row each, and the base stats that use them (Graphics/Standard_Items/item_bases.json).

The item card (item_card.py) draws only from these rows; combat will read the same numbers. A new property is a
new row here and a field in the bases, with no new card code. No rule reads a name: plate is a set of numbers.

Row fields:
    group     physical / element / cost / state
    format    int / number / percent (0..1 shown as %) / yes-no / list (body regions)
    better    higher / lower (for compare, later)
    card      line: a line on the card (in this order) / detail: only in the detail view
    template  the card line; {v} the value as formatted. yes-no: shown when true. With `at`: shown when the
              value is at least `at` (a threshold: "Conducts lightning"). {now}: the item's own value
              (the item attribute named as the row, e.g. item.durability; None: the base's).
A line whose value is 0, empty or false is left off the card (the detail view shows every value).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Property:
    id: str
    label: str
    group: str
    format: str
    better: str
    card: str
    template: str
    at: float | None = None


PROPERTIES = (
    Property("coverage", "Covers", "physical", "list", "higher", "line", "Covers: {v}"),
    Property("weight", "Weight", "cost", "number", "lower", "line", "Weight {v}"),
    Property("stopping_power", "Stopping power", "physical", "int", "higher", "line", "Stopping power {v}"),
    Property("absorb", "Absorb", "physical", "percent", "higher", "line", "Cushions {v} of force"),
    Property("conductivity", "Conductivity", "element", "percent", "lower", "line", "Conducts lightning", at=0.5),
    Property("flammability", "Flammability", "element", "percent", "lower", "line", "Catches fire", at=0.5),
    Property("insulation", "Insulation", "element", "percent", "higher", "detail", "Insulation {v}"),
    Property("sealed", "Sealed", "physical", "yes-no", "higher", "line", "Sealed: stops gas"),
    Property("durability", "Durability", "state", "int", "higher", "line", "Durability {now} / {v}"),
)
BY_ID = {p.id: p for p in PROPERTIES}

IDENTITY = ("name", "set", "flavour")   # base fields that are not properties: the card's name, set, free text

REGIONS = ("head", "neck", "chest", "back", "upper_arm", "forearm", "hand", "waist", "thigh", "shin", "foot")

# Weight class by body slot kind (equipment.BODY kinds): light up to the first number, medium up to the second,
# heavy above. Per kind, as a 3 kg helmet is heavy and a 3 kg chest is light. First numbers, to be tuned.
WEIGHT_CLASSES = {
    "helmet": (1, 2), "armor": (4, 8), "shoulder": (0.7, 1.5), "arm": (0.5, 1), "legs": (1, 2),
    "boots": (0.8, 1.6), "waist": (0.4, 0.8),
}

BASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Graphics", "Standard_Items",
                          "item_bases.json")


def load_bases(path=BASES_PATH):
    """{base id: {field: value}} from item_bases.json (keys starting with _ are notes)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


_bases = None


def base_of(item):
    """The base stats of an item (its `base` field), else None. The bases file is read once."""
    global _bases
    base_id = getattr(item, "base", None) if item is not None else None
    if not base_id:
        return None
    if _bases is None:
        _bases = load_bases()
    return _bases.get(base_id)


def unknown_fields(base):
    """Fields of a base that are neither a property nor an identity field."""
    return sorted(k for k in base if k not in BY_ID and k not in IDENTITY)


def format_value(prop, v):
    if prop.format == "yes-no":
        return "yes" if v else "no"
    if prop.format == "percent":
        return f"{round(v * 100)}%"
    if prop.format == "list":
        return ", ".join(r.replace("_", " ") for r in v)
    if prop.format == "int":
        return str(int(v))
    return f"{v:g}"


def shown(prop, v):
    """Does this property give a card line at this value?"""
    if prop.at is not None:
        return v is not None and v >= prop.at
    return bool(v)


def weight_class(kind, weight):
    light, medium = WEIGHT_CLASSES.get(kind, (1, 3))
    return "light" if weight <= light else "medium" if weight <= medium else "heavy"
