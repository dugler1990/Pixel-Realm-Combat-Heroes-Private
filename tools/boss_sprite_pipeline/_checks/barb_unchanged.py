"""What the barb's pipeline does, recorded without running anything: to diff a tree before and after a refactor.

    python tools/boss_sprite_pipeline/_checks/barb_unchanged.py <tree> <out.json>

<tree>: a checkout (main folder or a worktree); its tools/boss_sprite_pipeline code is imported. Needs
OUTFIT_DATA_ROOT (the Boss folder: run.json and data files). Writes nothing else: commands are recorded, not run.

Records, with the tree's path replaced by <TREE>:
- outfits     each barb outfit as the driver reads it (Ctx.o)
- commands    per outfit, per step: the commands and pod calls the step makes on today's run.json (a step that
              stops for a missing output records the stop)
- looks       the paint look each look file gives (repaint load_look); "bare": the look with no look file
              before, looks/barb_bare.json after
- export      the naked body export: the hero entry and the clips.json it writes
- retarget    the barb's retarget target row; clips: player_clips' clip choice for the barb
"""
from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

OUTFITS = ("naked", "fullplate", "loincloth")


def norm(obj, tree: str):
    s = json.dumps(obj, default=str)
    s = s.replace(json.dumps(sys.executable)[1:-1], "<PY>")
    for t in {tree, tree.replace("\\", "/"), tree.replace("\\", "\\\\")}:
        s = s.replace(t, "<TREE>")
    return json.loads(s)


def args():
    return SimpleNamespace(accept=None, retry=None, pick=None, redo=None, view=None, host="HOST", port="PORT",
                           models=None)


def commands(of, outfit: str) -> dict:
    out = {}
    for step in of.STEPS[of.Ctx("barb", outfit).o["kind"]]:
        rec = []
        of.call = lambda cmd, ok=None, cwd=None, show=True, rec=rec: rec.append([str(c) for c in cmd]) or "EXPORT_OK"
        of.pod = lambda ctx, s, a, token=False, extra=(), rec=rec: rec.append(["POD", s, token, *map(str, extra)]) or 0
        of.trellis_sheet = lambda ctx, models, rec=rec: rec.append(["SHEET", *models]) or Path("SHEET")
        of.shutil = SimpleNamespace(copy=lambda *a: None, rmtree=lambda *a, **k: None, move=lambda *a: None)
        of.Ctx.save = lambda self: None
        ctx = of.Ctx("barb", outfit)
        try:
            of.RUN[step](ctx, args())
        except of.Stop as stop:
            rec.append(["STOP", str(stop)])
        except SystemExit as exc:
            rec.append(["EXIT", str(exc)])
        except (OSError, KeyError, ValueError) as exc:     # a file the faked command would have made
            rec.append(["ERROR", type(exc).__name__, str(exc)])
        out[step] = rec
    return out


def looks(tree: Path) -> dict:
    rp = tree / "tools" / "boss_sprite_pipeline" / "repaint"
    src = (rp / "repaint.py").read_text(encoding="utf-8")
    if (rp / "look_file.py").is_file():                   # after: the look loader is its own module
        spec = importlib.util.spec_from_file_location("look_file", rp / "look_file.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        load, bare = mod.load_look, mod.load_look(rp / "looks" / "barb_bare.json")
    else:                                                 # before: DEFAULT_LOOK and load_look inside repaint.py
        ns: dict = {"json": json}
        tree_ = ast.parse(src)
        for node in tree_.body:
            if (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DEFAULT_LOOK" for t in node.targets)) \
                    or (isinstance(node, ast.FunctionDef) and node.name == "load_look"):
                exec(compile(ast.Module([node], []), "repaint", "exec"), ns)
        load, bare = ns["load_look"], ns["load_look"](None)
    res = {"bare": bare}
    for f in sorted((rp / "looks").glob("*.json")):
        if f.name != "barb_bare.json":
            res[f.name] = load(str(f))
    return {name: {k: v for k, v in look.items() if not k.startswith("_")} for name, look in res.items()}  # no notes


def export(of, tree: Path) -> dict:
    eo = importlib.import_module("tools.boss_sprite_pipeline.export_outfit")
    eo.run = lambda cmd, ok=None: ""
    eo.load_check = lambda p: None
    tmp = Path(tempfile.mkdtemp())
    real = eo.clips_json
    made = {}

    def clips(dst, *a, **k):
        real(tmp, *a, **k)
        made["clips"] = json.loads((tmp / "clips.json").read_text(encoding="utf-8"))
    eo.clips_json = clips
    ctx = of.Ctx("barb", "naked")
    ctx.painted = lambda: Path("PAINTED.glb")
    sys_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        res = eo.export_body(ctx.o, ctx)
    finally:
        sys.stdout.close()
        sys.stdout = sys_stdout
    return {"entry": res["selection_entry"], "clips_json": made.get("clips")}


def retarget(tree: Path) -> dict:
    tools = tree / "tools" / "boss_sprite_pipeline"
    if (tools / "characters.py").is_file():               # after: the barb's row from his character file
        sys.path.insert(0, str(tools))
        ch = importlib.import_module("characters")
        return {"retarget": ch.retarget_target("barb"), "clips": ch.clip_choice("barb")}
    src = (tools / "retarget_bvh.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "TARGETS" for t in n.targets))
    targets = eval(compile(ast.Expression(node.value), "TARGETS", "eval"), {"dict": dict})
    pc = (tools / "player_clips.py").read_text(encoding="utf-8")
    opt = dict(re.findall(r'opt\("--([a-z-]+)", "([^"]+)"\)', pc))
    clip = {"idle": opt["idle"], "move": opt["move"], "attack": opt["attack"],
            "attack_frames": [[int(v) for v in r.split("-")] for r in opt["attack-frames"].split(",")]}
    return {"retarget": targets["barb"], "clips": clip}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tree", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args()
    tree = a.tree.resolve()
    sys.path.insert(0, str(tree))
    of = importlib.import_module("tools.boss_sprite_pipeline.outfit")
    assert Path(of.__file__).resolve().is_relative_to(tree), of.__file__
    result = {"outfits": {o: of.Ctx("barb", o).o for o in OUTFITS},
              "looks": looks(tree), "export": export(of, tree), **retarget(tree)}
    result["commands"] = {o: commands(of, o) for o in OUTFITS}
    a.out.write_text(json.dumps(norm(result, str(tree)), indent=1, sort_keys=True), encoding="utf-8")
    print("BARB_RECORDED", a.out)


if __name__ == "__main__":
    main()
