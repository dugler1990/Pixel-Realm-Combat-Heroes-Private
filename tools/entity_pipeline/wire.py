"""Print a monster_data entry and add placed_entities objects."""
from __future__ import annotations

import ast
import copy
import json
import pprint
import re
from pathlib import Path

SETTINGS = Path("Code/Settings.py")

# Player start on the sunspine map, in Tiled pixels: world (15, 25) tiles * 150, then * 120/150.
# The warrior stands just south of that, on the same screen.
DEFAULT_X = 1800
DEFAULT_Y = 3400

# enemy_1 and enemy_3 are a hostile pair in Code/config/faction_policy.json.
# Two units on the plain "enemy" team will not attack each other.
HOSTILE_TEAMS = ("enemy_1", "enemy_3")
TEAM_SEPARATION = 440
ROW_STEP = 160
COPY_STEP = 90
# The benchmark wall ring leaves about 450px of open floor from the player to the
# nearest wall. A packed brawl stays inside that, with a gap the melee units can close.
BRAWL_HALF = 340
BRAWL_GAP = 110
BRAWL_STEP = 76
MELEE_RADIUS = 50          # tribey_spear's melee_attack_radius
MELEE_COOLDOWN = 1000      # tribey_spear's melee cooldown
RANGED_RADIUS = 200
RANGED_COOLDOWN = 4500     # three times the demon dog's 1500; the brawl was firing too often
PROJECTILE = "demon_dog_projectile"  # the spell, kept for casters
ARROW = "arrow"
STONE = "stone"


def template_entry(template: str) -> dict:
    """The template monster's monster_data entry. Settings.py is not imported.

    Only that one entry is evaluated. Other monsters call helpers, which the
    whole dict cannot be read as a literal.
    """
    tree = ast.parse(SETTINGS.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "monster_data"):
                continue
            if not isinstance(node.value, ast.Dict):
                raise SystemExit("monster_data is not a dict")
            for key, value in zip(node.value.keys, node.value.values):
                if key is None:
                    continue
                if ast.literal_eval(key) == template:
                    return ast.literal_eval(value)
            raise SystemExit(f"no monster_data entry named {template}")
    raise SystemExit("monster_data was not found in Code/Settings.py")


def format_entry(name: str, entry: dict) -> str:
    body = pprint.pformat(entry, width=88, sort_dicts=False)
    indented = "\n".join(("        " + line) if i else line for i, line in enumerate(body.splitlines()))
    return f'        "{name}": {indented},\n'


def _placed_group_close(text: str) -> int:
    match = re.search(r'<objectgroup\b[^>]*\bname="[^"]*placed_entities[^"]*"[^>]*>', text)
    if match is None:
        raise SystemExit("map has no placed_entities layer")
    pos = match.start()
    depth = 0
    while pos < len(text):
        nxt_open = text.find("<objectgroup", pos)
        nxt_close = text.find("</objectgroup>", pos)
        if nxt_close < 0:
            break
        if 0 <= nxt_open < nxt_close:
            depth += 1
            pos = nxt_open + len("<objectgroup")
            continue
        depth -= 1
        if depth == 0:
            return nxt_close
        pos = nxt_close + len("</objectgroup>")
    raise SystemExit("placed_entities layer is not closed")


def _monster_data_dict(tree: ast.AST) -> ast.Dict:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "monster_data":
                if not isinstance(node.value, ast.Dict):
                    raise SystemExit("monster_data is not a dict")
                return node.value
    raise SystemExit("monster_data was not found in Code/Settings.py")


def monster_names() -> set[str]:
    """Names already present in monster_data. Settings.py is not imported."""
    tree = ast.parse(SETTINGS.read_text(encoding="utf-8"))
    names = set()
    for key in _monster_data_dict(tree).keys:
        if key is None:
            continue
        try:
            names.add(ast.literal_eval(key))
        except (ValueError, SyntaxError):
            continue
    return names


def install_monster_entries(names: list[str], template: str) -> list[str]:
    """Copy the template entry under each missing name. Existing entries stay as they are."""
    entry = template_entry(template)
    present = monster_names()
    missing = [name for name in names if name not in present]
    if not missing:
        return []
    text = SETTINGS.read_text(encoding="utf-8")
    tree = ast.parse(text)
    close_at = _monster_data_dict(tree).end_lineno
    block = "".join(format_entry(name, entry) for name in missing)
    SETTINGS.write_text(_insert_before_line(text, close_at, block), encoding="utf-8")
    return missing


def _insert_before_line(text: str, lineno: int, block: str) -> str:
    """Insert `block` before the 1-based line, and give the previous item a trailing comma."""
    lines = text.splitlines(keepends=True)
    index = lineno - 1
    previous = index - 1
    while previous >= 0 and lines[previous].strip() == "":
        previous -= 1
    if previous >= 0 and not lines[previous].rstrip().endswith(","):
        body = lines[previous].rstrip("\r\n")
        newline = lines[previous][len(body):]
        lines[previous] = body + "," + (newline or "\n")
    if not block.endswith("\n"):
        block += "\n"
    lines.insert(index, block)
    return "".join(lines)


def _pack_grid(count: int, step: int, half: int, gap: int) -> tuple[int, int, int]:
    """Columns, rows, and step that keep one team inside the open floor."""
    if count <= 0:
        return 1, 0, step
    room_y = half * 2
    room_x = half - gap // 2
    step = max(step, 1)
    while True:
        cols = 1
        while cols < count:
            rows = (count + cols - 1) // cols
            if (rows - 1) * step <= room_y and (cols - 1) * step <= room_x:
                return cols, rows, step
            cols += 1
        if (count - 1) * step <= room_x:
            return count, 1, step
        if step == 1:
            return count, 1, 1
        step = max(1, step * 3 // 4)


# How many of one drawing. Foot outnumbers mounts, mounts outnumber casters,
# casters outnumber siege, and a melee version outnumbers the ranged one.
_LADDER = {
    "foot_melee": 3,
    "foot_ranged": 2,
    "mount_melee": 2,
    "mount_ranged": 1,
    "caster": 1,
    "siege": 1,
}
_COPY_CAP = 6


def _role(label: str, reach: str) -> str:
    """Foot, mount, caster, or siege, and whether this one fights in melee."""
    text = (label or "").lower()
    ranged = reach == "ranged"
    if any(word in text for word in ("machine", "cannon", "ballista", "trebuchet", "siege")) or (
        "catapult" in text and "crew" not in text
    ):
        return "siege"
    if any(word in text for word in ("priest", "magic", "wizard", "mage", "sorcer", "shaman")):
        return "caster"
    mounted = any(word in text for word in ("mounted", "cavalry", "camel", "horse", "knight", "rider"))
    beast = any(word in text for word in ("beast", "creature", "monster"))
    if mounted or beast:
        return "mount_ranged" if ranged else "mount_melee"
    return "foot_ranged" if ranged else "foot_melee"


def copies_for(label: str, reach: str = "melee") -> int:
    """Copies of one drawing before the roster is balanced. No model call."""
    return _LADDER[_role(label, reach)]


def roster_counts(scores: dict[str, dict]) -> dict[str, int]:
    """Copies for a whole sheet.

    Starts from the ladder, then adds to the side that should be larger until
    the army has more foot than mounts, more mounts than casters, more casters
    than siege, and more melee than ranged. A sheet that already has that shape
    is left on the ladder.
    """
    roles = {}
    counts = {}
    for name, score in scores.items():
        role = _role(score.get("label", ""), score.get("reach", "melee"))
        roles[name] = role
        counts[name] = _LADDER[role]

    def members(*kinds: str) -> list[str]:
        return [name for name, role in roles.items() if role in kinds]

    def total(names: list[str]) -> int:
        return sum(counts[name] for name in names)

    def add(names: list[str]) -> bool:
        room = [name for name in names if counts[name] < _COPY_CAP]
        if not room:
            return False
        room.sort(key=lambda name: (counts[name], name))
        counts[room[0]] += 1
        return True

    foot = members("foot_melee", "foot_ranged")
    mounts = members("mount_melee", "mount_ranged")
    casters = members("caster")
    siege = members("siege")
    melee = members("foot_melee", "mount_melee")
    ranged = members("foot_ranged", "mount_ranged", "caster", "siege")
    for _ in range(len(scores) * _COPY_CAP + 1):
        if foot and mounts and total(foot) <= total(mounts):
            if not add(members("foot_melee") or foot):
                break
            continue
        if mounts and casters and total(mounts) <= total(casters):
            if not add(members("mount_melee") or mounts):
                break
            continue
        if casters and siege and total(casters) <= total(siege):
            if not add(casters):
                break
            continue
        if melee and ranged and total(melee) <= total(ranged):
            if not add(members("foot_melee") or melee):
                break
            continue
        break
    return counts


def _how_many(name: str, each: int, counts: dict[str, int] | None) -> int:
    """`counts` is the label count. `each` multiplies it. Missing names stay at `each`."""
    if counts is not None and name in counts:
        return max(1, counts[name] * each)
    return each


def fight_placements(
    names: list[str],
    each: int,
    x: float = DEFAULT_X,
    y: float = DEFAULT_Y,
    packed: bool = False,
    counts: dict[str, int] | None = None,
) -> list[dict]:
    """Copies of every warrior, split onto the two hostile teams.

    `each` is the copy count. `counts` replaces it per name, and `each` then
    multiplies those. Copies of one warrior stay together. A sheet with a
    single warrior splits its copies across the two teams, so they still have
    someone to fight. `packed` folds each team into a block around (x, y) so a
    brawl fits in the wall ring. The map fight leaves it off and uses the wide line.
    """
    if each < 1:
        raise ValueError("each must be at least 1")
    names = list(names)
    sides: dict[str, list[tuple[str, int]]] = {team: [] for team in HOSTILE_TEAMS}
    if len(names) == 1 and _how_many(names[0], each, counts) > 1:
        name = names[0]
        total = _how_many(name, each, counts)
        left = total // 2
        for copy in range(left):
            sides[HOSTILE_TEAMS[0]].append((name, copy))
        for copy in range(left, total):
            sides[HOSTILE_TEAMS[1]].append((name, copy))
    else:
        for index, name in enumerate(names):
            team = HOSTILE_TEAMS[index % 2]
            for copy in range(_how_many(name, each, counts)):
                sides[team].append((name, copy))
    placements = []
    for team_index, team in enumerate(HOSTILE_TEAMS):
        members = sides[team]
        if packed:
            cols, _rows, step = _pack_grid(len(members), BRAWL_STEP, BRAWL_HALF, BRAWL_GAP)
            rows = (len(members) + cols - 1) // cols if members else 0
            block_w = (cols - 1) * step
            block_h = (max(rows, 1) - 1) * step
            center_x = x - (BRAWL_GAP / 2 + block_w / 2) if team_index == 0 else x + (BRAWL_GAP / 2 + block_w / 2)
            for index, (name, copy) in enumerate(members):
                col = index % cols
                row = index // cols
                placements.append({
                    "name": name if _how_many(name, each, counts) == 1 else f"{name}_{copy + 1}",
                    "entity_type": name,
                    "team_id": team,
                    "x": center_x + col * step - block_w / 2,
                    "y": y + row * step - block_h / 2,
                })
            continue
        x0 = x - TEAM_SEPARATION / 2 if team_index == 0 else x + TEAM_SEPARATION / 2
        row_of: dict[str, int] = {}
        for name, copy in members:
            row = row_of.setdefault(name, len(row_of))
            placements.append({
                "name": name if _how_many(name, each, counts) == 1 else f"{name}_{copy + 1}",
                "entity_type": name,
                "team_id": team,
                "x": x0 + copy * COPY_STEP,
                "y": y + row * ROW_STEP,
            })
    return placements


def add_placed_entity(
    map_path: Path,
    name: str,
    *,
    x: float = DEFAULT_X,
    y: float = DEFAULT_Y,
    entity_type: str | None = None,
    team_id: str | None = None,
) -> int:
    """Add one enemy object. Returns its id. Refuses when the layer is missing."""
    path = Path(map_path)
    text = path.read_text(encoding="utf-8")
    if re.search(rf'<object\b[^>]*\bname="{re.escape(name)}"', text):
        raise SystemExit(f"{path} already has an object named {name}")
    id_match = re.search(r'nextobjectid="(\d+)"', text)
    if id_match is None:
        raise SystemExit(f"{path} has no nextobjectid")
    object_id = int(id_match.group(1))
    text = text.replace(f'nextobjectid="{object_id}"', f'nextobjectid="{object_id + 1}"', 1)
    payload = {"kind": "enemy", "type": entity_type or name}
    if team_id:
        payload["spawn_team_id"] = team_id
    config = json.dumps(payload, separators=(",", ":"))
    config_xml = config.replace('"', "&quot;")
    # x/y may be whole numbers; write them the way the other objects on this layer are written.
    x_text = str(int(x)) if float(x).is_integer() else str(x)
    y_text = str(int(y)) if float(y).is_integer() else str(y)
    block = (
        f'  <object id="{object_id}" name="{name}" x="{x_text}" y="{y_text}">\n'
        f"   <properties>\n"
        f'    <property name="entity_spawn_config" value="{config_xml}"/>\n'
        f"   </properties>\n"
        f"  </object>\n"
    )
    close_at = _placed_group_close(text)
    text = text[:close_at] + block + text[close_at:]
    path.write_text(text, encoding="utf-8")
    return object_id


def projectile_for(label: str) -> str:
    """Casters keep the spell. A catapult throws a stone. Other ranged units shoot an arrow."""
    text = (label or "").lower()
    if any(word in text for word in ("magic", "priest", "wizard", "mage")):
        return PROJECTILE
    if "catapult" in text:
        return STONE
    return ARROW


def _band(score: int, lo: int, hi: int) -> int:
    """1 -> lo, 10 -> hi, straight line between, rounded."""
    return round(lo + (score - 1) * (hi - lo) / 9)


def adjust_entry(entry: dict, score: dict) -> dict:
    out = copy.deepcopy(entry)
    config = out.setdefault("combat_config", {})
    context = config.setdefault("combat_context", {})
    out["speed"] = _band(score["speed"], 2, 6)
    out["health"] = _band(score["bulk"], 40, 140)
    damage = _band(score["damage"], 3, 12)
    if score["reach"] == "ranged":
        out["attack_type"] = "ranged"
        config["melee_attacks"] = []
        config["ranged_attacks"] = [{"type": projectile_for(score.get("label", "")), "damage": damage, "cooldown": RANGED_COOLDOWN}]
        config["melee_attack_radius"] = 0
        config["ranged_attack_radius"] = RANGED_RADIUS
        context["fire_projectile"] = True
    else:
        out["attack_type"] = "melee"
        config["melee_attacks"] = [{"damage": damage, "cooldown": MELEE_COOLDOWN}]
        config["ranged_attacks"] = []
        config["melee_attack_radius"] = MELEE_RADIUS
        config.pop("ranged_attack_radius", None)
        context.pop("fire_projectile", None)
    return out


def _entry_span(text: str, name: str):
    tree = ast.parse(text)
    data = _monster_data_dict(tree)
    for key, value in zip(data.keys, data.values):
        if key is None:
            continue
        try:
            key_name = ast.literal_eval(key)
        except (ValueError, SyntaxError):
            continue
        if key_name != name:
            continue
        try:
            entry = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            raise SystemExit(f"monster_data[{name!r}] is not a plain dict; edit it by hand")
        lines = text.splitlines(keepends=True)
        # ast column offsets count UTF-8 bytes, so compare on bytes.
        before = lines[key.lineno - 1].encode("utf-8")[:key.col_offset]
        after = lines[value.end_lineno - 1].encode("utf-8")[value.end_col_offset:]
        if before.strip() or after.strip() not in (b"", b","):
            raise SystemExit(f"monster_data[{name!r}] shares a line with other code; edit it by hand")
        return entry, key.lineno, value.end_lineno
    return None


def rescore_monster_entries(scores: dict[str, dict], template: str) -> list[str]:
    changed = []
    for name, score in scores.items():
        if name == template:              # never rewrite tribey_spear itself
            continue
        text = SETTINGS.read_text(encoding="utf-8")
        found = _entry_span(text, name)
        if found is None:
            continue
        entry, first, last = found
        new = adjust_entry(entry, score)
        if new == entry:
            continue
        lines = text.splitlines(keepends=True)
        lines[first - 1:last] = [format_entry(name, new)]   # format_entry ends with ",\n"
        SETTINGS.write_text("".join(lines), encoding="utf-8")
        changed.append(name)
    return changed
