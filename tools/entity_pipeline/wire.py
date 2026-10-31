"""Print a monster_data entry and add one placed_entities object."""
from __future__ import annotations

import ast
import json
import pprint
import re
from pathlib import Path

SETTINGS = Path("Code/Settings.py")

# Player start on the sunspine map, in Tiled pixels: world (15, 25) tiles * 150, then * 120/150.
# The warrior stands just south of that, on the same screen.
DEFAULT_X = 1800
DEFAULT_Y = 3400


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


def add_placed_entity(
    map_path: Path,
    name: str,
    *,
    x: float = DEFAULT_X,
    y: float = DEFAULT_Y,
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
    config = json.dumps({"kind": "enemy", "type": name}, separators=(",", ":"))
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
