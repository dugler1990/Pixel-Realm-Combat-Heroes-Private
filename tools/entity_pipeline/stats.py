"""Score a cut sprite sheet. One vision call, separate from Leonardo."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tools.painted_map_pipeline.api_common import api_key
from tools.sprite_assets.cut_sheet import cells_from_grid

DEFAULT_STATS_CONFIG = Path("tools/entity_pipeline/stats.openai.json")
DEFAULT_URL = "https://api.openai.com/v1/chat/completions"


class StatsClientError(RuntimeError):
    pass


def sheet_cells(work):
    path = work / "layout.json"
    if not path.exists():
        raise SystemExit(f"no {path}; run cut first")
    layout = json.loads(path.read_text(encoding="utf-8"))
    if "named_boxes" in layout:          # light (parchment) sheet
        return [(name, tuple(box)) for name, box in layout["named_boxes"]]
    cells = cells_from_grid(layout["row_spans"], layout["col_spans"])   # black-gap sheet
    names = layout.get("names")
    if isinstance(names, list) and len(names) == len(cells):
        return [(str(names[i]), cell.box) for i, cell in enumerate(cells)]
    return [(f"warrior_{i:02d}", cell.box) for i, cell in enumerate(cells)]


def numbered_sheet(sheet, cells, dest):
    with Image.open(sheet) as source:
        image = source.convert("RGB")
    for name, box in cells:
        if box[2] > image.width or box[3] > image.height:
            raise SystemExit(f"layout.json does not fit {sheet}; pass the sheet you cut with --sheet")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)      # Pillow >= 11 is pinned, so size= works
    for index, (name, box) in enumerate(cells):
        draw.rectangle(box, outline=(255, 0, 0), width=3)
        label = str(index)
        spot = (box[0] + 6, box[1] + 4)
        draw.rectangle(draw.textbbox(spot, label, font=font), fill=(255, 255, 255))
        draw.text(spot, label, fill=(255, 0, 0), font=font)
    image.save(dest)
    return dest


STATS_PROMPT = (
    "This sprite sheet shows <COUNT> game warriors. Each one has a red box with a number from 0 to <LAST>. "
    "Score every numbered warrior from how it looks. "
    "speed: 1 is slow and heavy (a siege machine, heavy armour), 10 is very fast (a light runner, a beast, a rider). "
    "damage: 1 is weak (unarmed, a tool), 10 hits very hard (a big weapon, a large monster). "
    "bulk: 1 is frail (thin, no armour), 10 is very tough (heavy armour, a big shield, a large creature or machine). "
    "reach: \"ranged\" if it carries a bow, sling, throwing weapon or catapult, or casts magic with a staff; otherwise \"melee\". "
    "size: how big the whole figure should be next to a normal man of this same style on foot, height and width together. "
    "A man on foot is 1. A rider is more than 1, because the animal is under him and the figure is wider. "
    "Do not copy the drawn size: the sheet draws every cell at a similar scale. "
    "One decimal from 0.5 to 2.5. "
    "label: a short name for what you see. "
    "name: the folder name for this warrior. Lowercase words separated by underscores, no spaces. "
    "A spearman is \"spearman\". A camel archer is \"camel_archer\". Unique on this sheet. "
    "Reply with JSON only, in this shape: "
    "{\"warriors\": [{\"cell\": 0, \"label\": \"archer\", \"name\": \"archer\", \"speed\": 5, \"damage\": 5, \"bulk\": 5, \"reach\": \"melee\", \"size\": 1}]} "
    "The list has exactly <COUNT> objects, one per number, cell 0 to <LAST>. "
    "speed, damage and bulk are whole numbers from 1 to 10."
)


def build_prompt(count):
    return STATS_PROMPT.replace("<COUNT>", str(count)).replace("<LAST>", str(count - 1))


def ask_scores(image, prompt, config, model):
    key = api_key(config, default_env="OPENAI_API_KEY", error_cls=StatsClientError)
    url = config.get("url") or DEFAULT_URL
    encoded = base64.b64encode(Path(image).read_bytes()).decode("ascii")
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config.get("timeout_seconds", 120))) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise StatsClientError(f"HTTP {exc.code} from {url}: {detail}") from None
    except urllib.error.URLError as exc:
        raise StatsClientError(f"could not reach {url}: {exc.reason}") from None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise StatsClientError(f"unexpected reply: {json.dumps(data)[:2000]}") from None
    if not isinstance(content, str):
        raise StatsClientError(f"reply has no text: {json.dumps(data)[:2000]}")
    return content


def parse_scores(text, names):
    body = text.strip()
    if body.startswith("```"):                     # some endpoints wrap JSON in a fence
        body = body.split("\n", 1)[1] if "\n" in body else ""
        body = body.rsplit("```", 1)[0]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise StatsClientError(f"reply is not JSON: {exc}") from None
    rows = data.get("warriors") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise StatsClientError('reply has no "warriors" list')
    if len(rows) != len(names):
        raise StatsClientError(f"reply scored {len(rows)} warriors, the sheet has {len(names)}")
    scores = {}
    for row in rows:
        if not isinstance(row, dict):
            raise StatsClientError(f"not an object: {row!r}")
        cell = row.get("cell")
        if type(cell) is not int or not 0 <= cell < len(names):
            raise StatsClientError(f"bad cell number: {row!r}")
        name = names[cell]
        if name in scores:
            raise StatsClientError(f"cell {cell} was scored twice")
        for field in ("speed", "damage", "bulk"):
            value = row.get(field)
            if type(value) is not int or not 1 <= value <= 10:   # rejects True, 7.5, "7"
                raise StatsClientError(f"cell {cell}: {field} must be a whole number 1-10, got {value!r}")
        if row.get("reach") not in ("melee", "ranged"):
            raise StatsClientError(f'cell {cell}: reach must be "melee" or "ranged", got {row.get("reach")!r}')
        size = row.get("size")
        if isinstance(size, bool) or not isinstance(size, (int, float)):
            raise StatsClientError(f"cell {cell}: size must be a number from 0.5 to 2.5, got {size!r}")
        size = float(size)
        if not 0.5 <= size <= 2.5:
            raise StatsClientError(f"cell {cell}: size must be from 0.5 to 2.5, got {size!r}")
        folder = _unique_folder(row.get("name") or row.get("label"), cell, scores)
        scores[name] = {
            "label": str(row.get("label") or ""),
            "name": folder,
            "speed": row["speed"],
            "damage": row["damage"],
            "bulk": row["bulk"],
            "reach": row["reach"],
            "size": size,
        }
    return scores


def _folder_token(raw):
    text = re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")
    return text[:48].strip("_")


def _unique_folder(raw, cell, scores):
    token = _folder_token(raw)
    if not token:
        raise StatsClientError(f"cell {cell}: name must be a short folder name, got {raw!r}")
    used = {row.get("name") for row in scores.values()}
    folder = token
    n = 2
    while folder in used:
        folder = f"{token}_{n}"
        n += 1
    return folder


def adopt_names(work, cells, scores, monsters=None):
    """Point the cell, clip, and monster folders at the folder name in each score.

    Scores come back keyed by the cut name (warrior_00). This returns them keyed
    by the folder name, after the files have moved.
    """
    monsters = Path(monsters) if monsters is not None else Path("Graphics/Monsters")
    work = Path(work)
    new_cells = []
    new_scores = {}
    renamed = []
    moves = []
    for old, box in cells:
        folder = scores[old]["name"]
        new_scores[folder] = scores[old]
        new_cells.append((folder, box))
        if folder == old:
            continue
        renamed.append((old, folder))
        for src, dest in (
            (work / "cells" / f"{old}.png", work / "cells" / f"{folder}.png"),
            (work / "anim" / old, work / "anim" / folder),
            (monsters / old, monsters / folder),
        ):
            if src.exists():
                moves.append((src, dest))
    sources = {src.resolve() for src, _dest in moves}
    for _src, dest in moves:
        if dest.exists() and dest.resolve() not in sources:
            raise StatsClientError(f"{dest} already exists, not renaming over it")
    parked = []
    for src, dest in moves:
        tmp = src.with_name(src.name + ".renaming")
        src.rename(tmp)
        parked.append((tmp, dest))
    for tmp, dest in parked:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp.rename(dest)
    _write_layout_names(work, [name for name, _box in new_cells])
    return new_cells, new_scores, renamed


def _write_layout_names(work, names):
    path = Path(work) / "layout.json"
    if not path.exists():
        return
    layout = json.loads(path.read_text(encoding="utf-8"))
    if "named_boxes" in layout:
        boxes = layout["named_boxes"]
        if len(boxes) != len(names):
            raise StatsClientError("layout.json cell count does not match the scores")
        layout["named_boxes"] = [[names[i], boxes[i][1]] for i in range(len(names))]
    else:
        layout["names"] = list(names)
    path.write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _cell_list(cells):
    return [[name, list(box)] for name, box in cells]


def save_scores(work, model, sheet, cells, scores):
    record = {
        "model": model,
        "sheet": str(sheet),
        "sheet_sha256": _sha256(sheet),
        "cells": _cell_list(cells),
        "scores": scores,
    }
    path = work / "stats.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def load_scores(work):
    path = work / "stats.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    sheet = Path(data.get("sheet", ""))
    same_sheet = sheet.is_file() and _sha256(sheet) == data.get("sheet_sha256")
    same_cells = data.get("cells") == _cell_list(sheet_cells(work))
    if not (same_sheet and same_cells):
        print(f"stats: {path} is for a different sheet or cut; run stats --force")
        return {}
    return data["scores"]


def print_scores(scores):
    for name, s in scores.items():
        print(f"  {name}  {s['label'][:28]:<28}  speed {s['speed']:>2}  damage {s['damage']:>2}  "
              f"bulk {s['bulk']:>2}  size {s.get('size', 0):.1f}  {s['reach']}")
