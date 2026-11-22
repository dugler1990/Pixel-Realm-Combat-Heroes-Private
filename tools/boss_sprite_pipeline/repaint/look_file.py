"""Paint looks: what the paint prompts say about a character and its outfit (repaint/looks/*.json).

There is no default look: every run names one (`views --look`, remembered in cams.json). A look may say
"extends": "<other look>.json" (same folder): it starts from that one and overrides its keys. The barb's outfit
looks extend barb_bare.json (the bare barb, pass 1/2 wording). Stdlib only (Blender's python imports it).

Keys: the REQUIRED wording below; optional: "views" (names) limits the views, "shots" ({name: {"shows", "paint"}})
re-words close-ups, "part_res" close-up size in px, "quality" gpt-image-2 quality (high), "provider" "openai"
(gpt-image-2) or "leonardo" with "model" (e.g. "nano-banana-2"), "regions" ({"arm": {"scale", "shift_up"}}) widens
or raises a close-up frame (shift in heights). Keys starting with "_" are notes.
"""
from __future__ import annotations

import json
import os

REQUIRED = ("subject", "design", "match_part", "match_body", "body_paint", "part_variation", "safety", "finish_part",
            "finish_body")


def load_look(path) -> dict:
    if not path:
        raise SystemExit("no look file: pass views --look <repaint/looks/*.json> (a cams.json made before looks were "
                         "required has \"look\": null: set it to the look file that run used)")
    path = str(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    base = {}
    if "extends" in data:
        parent = load_look(os.path.join(os.path.dirname(path), data.pop("extends")))
        base = {k: v for k, v in parent.items() if not k.startswith("_")}
    look = {**base, **data}
    missing = [k for k in REQUIRED if k not in look]
    if missing:
        raise SystemExit(f"look {path} has no {', '.join(missing)}")
    return look
