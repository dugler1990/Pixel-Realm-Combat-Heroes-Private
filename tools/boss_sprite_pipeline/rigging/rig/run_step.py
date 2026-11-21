"""Run one rig step: input version + settings -> a new, not yet accepted, version with its checks.

Reserves v<N> first (rig/version.py), runs the step, evaluates each check's rules, writes the record.
A failed step removes its folder, so a half-made version never shows. Blender work is always a fresh
subprocess of the Boss .venv-bpy python.
"""
from __future__ import annotations

import json
import operator
import shutil
import subprocess
from pathlib import Path

from .. import paths
from ..settings import resolve
from . import glb as G
from . import steps as S
from . import version as V

OPS = {"==": operator.eq, "<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt}


class Ctx:
    def __init__(self, cid, n, folder, input_rec, settings, lines):
        self.cid, self.n, self.dir = cid, n, Path(folder)
        self.input = input_rec
        self.input_glb = input_rec["glb_path"]
        self.input_roles = dict(input_rec["roles"])
        self.settings = settings
        self.lines = lines
        self.pipe = paths.PIPE
        self.measured = {}

    def log(self, text):
        for line in str(text).splitlines():
            self.lines.append(line)
        del self.lines[:-400]

    def blender(self, args, expect=None):
        cmd = [str(paths.bpy_python())] + [str(a) for a in args]
        self.log("$ " + " ".join(cmd))
        proc = subprocess.run(cmd, cwd=str(self.pipe), capture_output=True, text=True,
                              env={**__import__("os").environ, "ANIM_DATA_ROOT": str(paths.data_root())})
        self.log(proc.stdout[-6000:])
        if proc.stderr:
            self.log(proc.stderr[-3000:])
        if proc.returncode != 0 or (expect and expect not in proc.stdout):
            raise RuntimeError(f"{Path(args[0]).name} failed (exit {proc.returncode})")
        return proc.stdout

    def measure(self, check, glb):
        out = self.dir / f"check_{check}.json"
        self.blender([str(self.pipe / "rigging" / "blender" / "runner.py"), "check", check, str(glb), str(out)],
                     expect="RUNNER_OK")
        return json.loads(out.read_text(encoding="utf-8"))

    def check(self, name, numbers):
        self.measured[name] = numbers

    def op(self, name, params, glb=None):
        """A Blender edit from rigging/blender/ops.py on the input (or `glb`), into this version's rig.glb."""
        p = self.dir / f"op_{name}.json"
        p.write_text(json.dumps(params), encoding="utf-8")
        out = self.dir / "rig.glb"
        self.blender([str(self.pipe / "rigging" / "blender" / "runner.py"), "op", name, str(glb or self.input_glb),
                      str(p), str(out)], expect="RUNNER_OK")
        return out, json.loads(Path(str(out) + ".json").read_text(encoding="utf-8"))


def evaluate(step, measured: dict) -> dict:
    out = {}
    for name, rules in step.CHECKS.items():
        nums = measured.get(name)
        if nums is None:
            out[name] = {"pass": False, "gate": any(r[3] for r in rules), "error": "not measured"}
            continue
        results = []
        for metric, op, value, gate in rules:
            got = nums.get(metric)
            ok = got is not None and OPS[op](got, value)
            results.append({"metric": metric, "got": got, "rule": f"{op} {value}", "pass": ok, "gate": gate})
        gate_rules = [r for r in results if r["gate"]]
        out[name] = {"pass": all(r["pass"] for r in gate_rules) if gate_rules else True,
                     "gate": bool(gate_rules), "rules": results, "numbers": nums}
    return out


def run_step(cid: str, step_name: str, settings: dict, input_n: int, lines: list) -> dict:
    step = S.get(step_name)
    resolved = resolve(step.SETTINGS, [("step", settings or {})])
    vals = {k: v["value"] for k, v in resolved.items()}
    inp = V.load(cid, input_n)
    n, folder = V.begin(cid)
    ctx = Ctx(cid, n, folder, inp, vals, lines)
    ctx.log(f"{step_name}: v{input_n} -> v{n}")
    try:
        result = step.run(ctx)
        checks = evaluate(step, ctx.measured)
        glb = result["glb"]
        kind = step.KIND
        if kind == "auto":
            new_hash = G.bone_hash(G.skeleton(glb if glb else inp["glb_path"]))
            kind = "weights" if new_hash == inp["bone_hash"] else "bone_set"
        rec = V.finish(cid, n, step=step_name, kind=kind, settings=resolved, input_n=input_n,
                       roles=result["roles"], glb=glb, glb_ref=None if glb else inp["glb"], checks=checks,
                       note=vals.get("reason", ""))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    ok, bad = V.gates_pass(rec)
    ctx.log(f"RIG_STEP_DONE v{n} {step_name} {kind} gates {'pass' if ok else 'FAIL ' + ', '.join(bad)}")
    return rec
