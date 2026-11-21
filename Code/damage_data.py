"""Attack defs: what kind of blow each attack is (damage chunk 2, docs/damage/NOTES_damage_and_armour.md).

Read once at import from config/damage/categories.json and config/damage/attacks.json. Every attack in
Settings.py names its def with an "attack" key; attack(name) returns the one shared AttackDef, so a
sprite or a strike carries a reference, never a copy. Nothing reads the defs for damage yet: chunk 5
does. No pygame here.

Body defs (chunk 4): config/damage/kinds.json and bodies.json. Every monster_data entry names its
body with a "body" key; body(name) returns the shared BodyDef (kind + natural LayerDef). Worn pieces
become LayerDefs from their item base (defence_profile.py).
"""
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "damage")
CATEGORIES_PATH = os.path.join(CONFIG_DIR, "categories.json")
ATTACKS_PATH = os.path.join(CONFIG_DIR, "attacks.json")
SCHEMA_VERSION = 1

_ROW_FIELDS = frozenset(
    ("delivery", "damage", "penetration", "force", "magic", "venom", "stops", "scales_with", "cold",
     "hold")
)
_BOLT_FIELDS = frozenset(("damage", "reach", "arcs", "spark"))
_NUMBER_FIELDS = ("damage", "penetration", "force")
_SCALES_WITH = frozenset(("attack", "magic"))


class DamageDataError(ValueError):
    """A damage config file is wrong; the message names the file and the row."""


class Lightning:
    """A bolt's four knobs. A bare number in the file is damage only: it hits and does not jump."""

    __slots__ = ("damage", "reach", "arcs", "spark")

    def __init__(self, damage, reach, arcs, spark):
        self.damage = damage
        self.reach = reach
        self.arcs = arcs
        self.spark = spark

    def __repr__(self):
        return (f"Lightning(damage={self.damage:g}, reach={self.reach:g}, "
                f"arcs={self.arcs}, spark={self.spark:g})")


class AttackDef:
    """One attack def. Shared: never change one after load.

    magic is ((category_id, power), ...) for what is still a flat category (fire, holy, unholy).
    Ice is `cold` (a temperature). Lightning is a Lightning. magic_mask still has a bit for ice
    and lightning and for every parent (fire also sets elemental).
    """

    __slots__ = (
        "id", "name", "delivery", "damage", "penetration", "force",
        "magic", "magic_mask", "venom", "stops", "scales_with", "cold", "lightning", "hold",
    )

    def __init__(self, id, name, delivery, damage, penetration, force,
                 magic, magic_mask, venom, stops, scales_with, cold=0, lightning=None, hold=None):
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
        self.cold = cold
        self.lightning = lightning
        # (T, k): while in reach of a body with a temperature, this attack holds it (a source on
        # its outer layer, temperature.py) instead of striking. None: it strikes.
        self.hold = hold

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


def _lightning(path, name, value):
    """A bare number, or {damage, reach, arcs, spark}. Missing reach, arcs and spark are 0."""
    where = f"{path}: attack {name!r}: lightning"
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return Lightning(_number(path, name, "lightning", value), 0.0, 0, 0.0)
    if not isinstance(value, dict):
        raise DamageDataError(f"{where} must be a number or an object")
    unknown = set(value) - _BOLT_FIELDS
    if unknown:
        raise DamageDataError(f"{where}: unknown field(s) {sorted(unknown)}")
    if "damage" not in value:
        raise DamageDataError(f"{where}: needs damage")
    arcs = value.get("arcs", 0)
    if isinstance(arcs, bool) or not isinstance(arcs, int) or arcs < 0:
        raise DamageDataError(f"{where}: arcs must be a whole number >= 0, got {arcs!r}")
    return Lightning(
        _number(path, name, "lightning damage", value["damage"]),
        _number(path, name, "lightning reach", value.get("reach", 0)),
        arcs,
        _number(path, name, "lightning spark", value.get("spark", 0)),
    )


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
    ice_power = None
    lightning = None
    for category, power in magic_row.items():
        if category not in categories.ids:
            raise DamageDataError(f"{where}: unknown magic category {category!r}")
        mask |= categories.mask(category)
        if category == "ice":
            ice_power = _number(path, name, "magic ice", power)
            continue
        if category == "lightning":
            lightning = _lightning(path, name, power)
            continue
        magic.append((categories.ids[category], _number(path, name, f"magic {category}", power)))
    if "cold" in row:
        cold = _number(path, name, "cold", row["cold"])
    else:
        cold = 0 if ice_power is None else ice_power
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
    hold = row.get("hold")
    if hold is not None:
        if not isinstance(hold, dict) or set(hold) != {"T", "k"}:
            raise DamageDataError(f"{where}: hold must be {{\"T\": warmth, \"k\": strength}}")
        k = hold["k"]
        if isinstance(k, bool) or not isinstance(k, (int, float)) or k <= 0:
            raise DamageDataError(f"{where}: hold k must be > 0, got {k!r}")
        T = hold["T"]
        if isinstance(T, bool) or not isinstance(T, (int, float)):
            raise DamageDataError(f"{where}: hold T must be a number, got {T!r}")
        hold = (float(T), float(k))
    return AttackDef(
        attack_id, name, delivery, numbers["damage"], numbers["penetration"], numbers["force"],
        tuple(magic), mask, venom, stops, scales_with, cold, lightning, hold,
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


# --- bodies and layers (damage chunk 4) ------------------------------------------------------

KINDS_PATH = os.path.join(CONFIG_DIR, "kinds.json")
BODIES_PATH = os.path.join(CONFIG_DIR, "bodies.json")

# The item property ids (item_properties.PROPERTIES) a layer has; coverage is where, not what.
LAYER_NUMBERS = ("stopping_power", "absorb", "flammability", "conductivity", "insulation",
                 "sun_absorb", "weight", "durability")
LAYER_SHARES = ("absorb", "flammability", "conductivity", "insulation", "sun_absorb")   # 0..1
# A missing number is 0, except these: skin and hides soak up half the sun.
LAYER_DEFAULTS = {"sun_absorb": 0.5}
_LAYER_FIELDS = frozenset(LAYER_NUMBERS + ("sealed",))
_BODY_FIELDS = frozenset(("kind", "natural", "resist", "starts"))


class LayerDef:
    """One layer between a hit and the flesh: a worn piece's base or a body's natural hide.
    Shared: never change one after load (wear, chunk 10, keeps its own state)."""

    __slots__ = LAYER_NUMBERS + ("sealed", "name")

    def __init__(self, name, **fields):
        self.name = name
        for field in LAYER_NUMBERS:
            setattr(self, field, fields.get(field, LAYER_DEFAULTS.get(field, 0)))
        self.sealed = fields.get("sealed", False)

    def __repr__(self):
        return f"LayerDef({self.name!r})"


class BodyDef:
    """A creature's constants: its kind, its natural layer, its resists, what it starts as.
    Mass is in monster_data. A resist may be negative; the rule clamps it until chunk 9."""

    __slots__ = ("id", "name", "kind", "natural", "resist", "starts")

    def __init__(self, id, name, kind, natural, resist, starts):
        self.id = id
        self.name = name
        self.kind = kind
        self.natural = natural
        self.resist = resist
        self.starts = starts

    def __repr__(self):
        return f"BodyDef({self.name!r})"


def layer_def(name, fields, where, extra=()):
    """A LayerDef from property fields (a natural layer or an item base). Fields in `extra` are
    allowed and skipped (an item base's name, set, coverage); any other unknown field fails."""
    unknown = set(fields) - _LAYER_FIELDS - set(extra)
    if unknown:
        raise DamageDataError(f"{where}: unknown layer field(s) {sorted(unknown)}")
    clean = {}
    for field in LAYER_NUMBERS:
        if field in fields:
            value = fields[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise DamageDataError(f"{where}: {field} must be a number >= 0, got {value!r}")
            if field in LAYER_SHARES and value > 1:
                raise DamageDataError(f"{where}: {field} must be 0..1, got {value!r}")
            clean[field] = value
    sealed = fields.get("sealed", False)
    if not isinstance(sealed, bool):
        raise DamageDataError(f"{where}: sealed must be true or false")
    return LayerDef(name, sealed=sealed, **clean)


def load_kinds(path=KINDS_PATH):
    kinds = _read(path).get("kinds")
    if not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) for k in kinds):
        raise DamageDataError(f"{path}: kinds must be a list of names")
    return tuple(kinds)


def load_bodies(path=BODIES_PATH, kinds=None):
    """The body defs in file order; ids are 0..n-1."""
    kinds = kinds if kinds is not None else load_kinds()
    rows = _read(path).get("bodies")
    if not isinstance(rows, dict):
        raise DamageDataError(f"{path}: bodies must be a name -> row map")
    bodies = []
    for body_id, (name, row) in enumerate(rows.items()):
        where = f"{path}: body {name!r}"
        if not isinstance(row, dict):
            raise DamageDataError(f"{where}: must be an object")
        unknown = set(row) - _BODY_FIELDS
        if unknown:
            raise DamageDataError(f"{where}: unknown field(s) {sorted(unknown)}")
        if row.get("kind") not in kinds:
            raise DamageDataError(f"{where}: unknown kind {row.get('kind')!r}")
        natural = row.get("natural", {})
        if not isinstance(natural, dict):
            raise DamageDataError(f"{where}: natural must be a property -> value map")
        resist = row.get("resist", {})
        if not isinstance(resist, dict):
            raise DamageDataError(f"{where}: resist must be a category -> number map")
        clean_resist = {}
        for category, value in resist.items():
            if category not in CATEGORIES.ids:
                raise DamageDataError(f"{where}: unknown resist {category!r}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DamageDataError(f"{where}: resist {category} must be a number, got {value!r}")
            clean_resist[category] = value
        starts = row.get("starts", [])
        if not isinstance(starts, list) or not all(isinstance(name, str) and name for name in starts):
            raise DamageDataError(f"{where}: starts must be a list of condition names")
        bodies.append(BodyDef(
            body_id, name, row["kind"], layer_def(name, natural, where),
            clean_resist, tuple(starts),
        ))
    return bodies


KINDS = load_kinds()
BODIES = load_bodies(kinds=KINDS)
_BODY_BY_NAME = {b.name: b for b in BODIES}


def body(name):
    """The shared BodyDef called `name`. KeyError naming it when there is none."""
    try:
        return _BODY_BY_NAME[name]
    except KeyError:
        raise KeyError(f"no body def {name!r} in {BODIES_PATH}") from None


def body_of(entry, key="body"):
    """The body def a monster_data entry names under `key`; None when it names none."""
    name = entry.get(key) if isinstance(entry, dict) else None
    return None if name is None else body(name)
