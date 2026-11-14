"""What view_gate would send for the barb's drawn views, recorded with --dry-run (no call): to diff a tree before and
after moving its prompts and check values into files.

    python tools/boss_sprite_pipeline/_checks/view_prompts_unchanged.py <tree> <out.json>

<tree>: a checkout (main folder or a worktree); its view_gate and outfit files are used, run with its
Code/sprite_venv python. Needs OUTFIT_DATA_ROOT (the Boss folder: the concepts). Writes only into a temp folder.
Records, per barb outfit with drawn views and per case (front, front rb, back, sides, 3/4s): the prompt printed
and the images it would send, with the tree and temp paths replaced.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

OUTFITS = ("fullplate", "naked")


def cases(concept: Path) -> list[tuple[str, list[str]]]:
    c = str(concept)
    return [("front", ["front", "--input", c]),
            ("front rb", ["front", "--input", c, "--retry", "rb"]),
            ("front r why", ["front", "--input", c, "--retry", "r the arms are too thin"]),
            ("back", ["back", "--front", c]),
            ("side left", ["side", "--front", c, "--back", c, "--side", "left"]),
            ("side right", ["side", "--front", c, "--back", c, "--side", "right"]),
            ("side front_left", ["side", "--front", c, "--back", c, "--side", "front_left"]),
            ("side back_right", ["side", "--front", c, "--back", c, "--side", "back_right"])]


def main() -> None:
    tree, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    root = Path(os.environ["OUTFIT_DATA_ROOT"])
    py = tree / "Code" / "sprite_venv" / "Scripts" / "python.exe"
    res = {}
    for outfit in OUTFITS:
        ofile = tree / "tools" / "boss_sprite_pipeline" / "outfits" / "barb" / f"{outfit}.json"
        concept = root / json.loads(ofile.read_text(encoding="utf-8"))["concept"]
        for name, args in cases(concept):
            tmp = tempfile.mkdtemp()
            r = subprocess.run([str(py), "-m", "tools.boss_sprite_pipeline.view_gate", *args, "--out", tmp,
                                "--outfit", str(ofile), "--dry-run"], cwd=tree, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            text = (r.stdout + "\n--- stderr\n" + "\n".join(l for l in r.stderr.splitlines() if "joints on" in l
                                                             or "--- images" in l or "error" in l.lower()))
            for t in (str(tree), str(tree).replace("\\", "/"), tmp, tmp.replace("\\", "/")):
                text = text.replace(t, "<T>")
            res[f"{outfit}: {name}"] = {"exit": r.returncode, "text": text}
            print(f"  {outfit}: {name}  exit {r.returncode}", flush=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print("VIEW_PROMPTS_RECORDED", out)


if __name__ == "__main__":
    main()
