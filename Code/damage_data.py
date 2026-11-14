"""Attack defs: what kind of blow each attack is (damage chunk 2, docs/damage/NOTES_damage_and_armour.md).

Read once at import from config/damage/categories.json and config/damage/attacks.json. Every attack in
Settings.py names its def with an "attack" key; attack(name) returns the one shared AttackDef, so a
sprite or a strike carries a reference, never a copy. Nothing reads the defs for damage yet: chunk 5
does. No pygame here.
"""
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "damage")
CATEGORIES_PATH = os.path.join(CONFIG_DIR, "categories.json")
ATTACKS_PATH = os.path.join(CONFIG_DIR, "attacks.json")
SCHEMA_VERSION = 1

_ROW_FIELDS = frozenset(
    ("delivery", "damage", "penetration", "force", "magic", "venom", "stops", "scales_with")
)
_NUMBER_FIELDS = ("damage", "penetration", "force")
_SCALES_WITH = frozenset(("attack", "magic"))


class DamageDataError(ValueError):
    """A damage config file is wrong; the message names the file and the row."""


class AttackDef:
    """One attack def. Shared: never change one after load.

    magic is ((category_id, power), ...). magic_mask has a bit for each of those categories and
    for every parent above them (fire also sets elemental), so a resistance to a whole family is
    one AND.
    """

    __slots__ = (
        "id", "name", "delivery", "damage", "penetration", "force",
        "magic", "magic_mask", "venom", "stops", "scales_with",
    )

    def __init__(self, id, name, delivery, damage, penetration, force,
                 magic, magic_mask, venom, stops, scales_with):
        self.id = id
        self.name = name
        self.delivery = delivery
        self.damage = damage
        self.penetration = penetration
        self.force = force
        self.magic = magic
        self.magic_mask = magic_mask
        self.venom = venom
        self.stops = stops
        self.scales_with = scales_with

    def __repr__(self):
        return f"AttackDef({self.name!r})"


class Categories:
    """Magic categories: name -> id, and each one's parent (None at the top)."""

    def __init__(self, deliveries, parents):
        self.deliveries = tuple(deliveries)
        self.names = tuple(parents)
        self.ids = {name: i for i, name in enumerate(self.names)}
        self.parent = {name: parents[name] for name in self.names}

    def mask(self, name):
        """The bit of `name` and of every parent above it."""
        bits = 0
        while name is not None:
            bits |= 1 << self.ids[name]
            name = self.parent[name]
        return bits


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DamageDataError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise DamageDataError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    return data


def load_categories(path=CATEGORIES_PATH):
    data = _read(path)
    deliveries = data.get("deliveries")
    parents = data.get("categories")
    if not isinstance(deliveries, list) or not all(isinstance(d, str) for d in deliveries):
        raise DamageDataError(f"{path}: deliveries must be a list of names")
    if not isinstance(parents, dict):
        raise DamageDataError(f"{path}: categories must be a name -> parent map")
    for name, parent in parents.items():
        if parent is not None and parent not in parents:
            raise DamageDataError(f"{path}: category {name!r}: unknown parent {parent!r}")
    for name in parents:
        seen = set()
        walk = name
        while walk is not None:
            if walk in seen:
                raise DamageDataError(f"{path}: category {name!r}: its parents loop")
            seen.add(walk)
            walk = parents[walk]
    return Categories(deliveries, parents)


def _number(path, name, field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise DamageDataError(f"{path}: attack {name!r}: {field} must be a number >= 0, got {value!r}")
    return value


def _attack_def(path, attack_id, name, row, categories):
    where = f"{path}: attack {name!r}"
    if not isinstance(row, dict):
        raise DamageDataError(f"{where}: must be an object")
    unknown = set(row) - _ROW_FIELDS
    if unknown:
        raise DamageDataError(f"{where}: unknown field(s) {sorted(unknown)}")
    if not ({"delivery", "magic", "venom"} & set(row)):
        raise DamageDataError(f"{where}: needs a delivery, magic or venom")
    delivery = row.get("delivery")
    if delivery is not None and delivery not in categories.deliveries:
        raise DamageDataError(f"{where}: unknown delivery {delivery!r}")
    numbers = {field: _number(path, name, field, row.get(field, 0)) for field in _NUMBER_FIELDS}
    magic_row = row.get("magic", {})
    if not isinstance(magic_row, dict):
        raise DamageDataError(f"{where}: magic must be a category -> power map")
    magic = []
    mask = 0
    for category, power in magic_row.items():
        if category not in categories.ids:
            raise DamageDataError(f"{where}: unknown magic category {category!r}")
        magic.append((categories.ids[category], _number(path, name, f"magic {category}", power)))
        mask |= categories.mask(category)
    venom = row.get("venom")
    if venom is not None:
        if (not isinstance(venom, dict) or set(venom) != {"id", "dose"}
                or not isinstance(venom["id"], str)):
            raise DamageDataError(f"{where}: venom must be {{\"id\": name, \"dose\": n}}")
        venom = (venom["id"], _number(path, name, "venom dose", venom["dose"]))
    stops = row.get("stops", False)
    if not isinstance(stops, bool):
        raise DamageDataError(f"{where}: stops must be true or false")
    scales_with = row.get("scales_with")
    if scales_with is not None and scales_with not in _SCALES_WITH:
        raise DamageDataError(f"{where}: scales_with must be one of {sorted(_SCALES_WITH)}")
    return AttackDef(
        attack_id, name, delivery, numbers["damage"], numbers["penetration"], numbers["force"],
        tuple(magic), mask, venom, stops, scales_with,
    )


def load_attacks(path=ATTACKS_PATH, categories=None):
    """The attack defs in file order; ids are 0..n-1."""
    categories = categories if categories is not None else load_categories()
    data = _read(path)
    rows = data.get("attacks")
    if not isinstance(rows, dict):
        raise DamageDataError(f"{path}: attacks must be a name -> row map")
    return [
        _attack_def(path, attack_id, name, row, categories)
        for attack_id, (name, row) in enumerate(rows.items())
    ]


CATEGORIES = load_categories()
ATTACKS = load_attacks(categories=CATEGORIES)
_BY_NAME = {d.name: d for d in ATTACKS}


def attack(name):
    """The shared AttackDef called `name`. KeyError naming it when there is none."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"no attack def {name!r} in {ATTACKS_PATH}") from None


def attack_of(entry, key="attack"):
    """The def an attack entry from Settings names under `key`; None when it names none."""
    name = entry.get(key) if isinstance(entry, dict) else None
    return None if name is None else attack(name)
