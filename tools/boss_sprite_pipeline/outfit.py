"""The outfit pipeline's driver: one command per character + outfit (PROCESS_outfit.md).

    python -m tools.boss_sprite_pipeline.outfit <character> <outfit> [--status] [--backfill]
        [--from STEP] [--only STEP] [--host IP --port PORT] [--retry R | --accept N | --pick M | --redo VIEW...]

Runs the outfit's steps in order from the first one not done, recording each in
<data>/generated/bosses/<character>/outfits/<outfit>/run.json, and stops:
- at a gate: front / back (view_gate draws; --accept N or --retry r|r1|rb|"r <why> @img"), trellis (both models
  made; --pick front_only|front_back, by eye for now), paint (look at the check image; --accept, or --redo views)
- before a pod step without --host / --port (or POD_HOST / POD_PORT); you start and stop the pod
- at the first step that fails.
Steps by the outfit's kind:
    body    front back trellis skeleton paint export
    armour  front back trellis skeleton paint views sam3 cut holopart merge worn slots sheet export
    cut     views sam3 cut holopart merge worn slots sheet export
--status   what is done, with outputs. --backfill: run.json from the outfit's "existing" outputs (made before the
           driver: v9). --only STEP: that step alone (rerun). --from STEP: from there on, rerunning what is done.
Data root: OUTFIT_DATA_ROOT (where generated/ is: the Boss folder), else this repo. Blender: OUTFIT_BPY, else
tools/boss_sprite_pipeline/.venv-bpy. Image keys and HF_TOKEN from the environment, never typed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[1]
STEPS = {
    "body": ["front", "back", "trellis", "skeleton", "paint", "export"],
    "armour": ["front", "back", "trellis", "skeleton", "paint", "views", "sam3", "cut", "holopart", "merge", "worn",
               "slots", "sheet", "export"],
    "cut": ["views", "sam3", "cut", "holopart", "merge", "worn", "slots", "sheet", "export"],
}
POD_STEPS = {"trellis", "sam3", "holopart"}


class Stop(Exception):
    """A gate or a missing input: the run stops here, with what to do next."""


class Ctx:
    def __init__(self, character: str, outfit: str):
        self.character, self.outfit = character, outfit
        self.file = TOOLS / "outfits" / character / f"{outfit}.json"
        if not self.file.is_file():
            sys.exit(f"no outfit file {self.file}")
        self.o = json.loads(self.file.read_text(encoding="utf-8"))
        self.root = Path(os.environ.get("OUTFIT_DATA_ROOT") or REPO)
        self.bpy = Path(os.environ.get("OUTFIT_BPY") or TOOLS / ".venv-bpy" / "Scripts" / "python.exe")
        self.work = self.root / "generated" / "bosses" / character / "outfits" / outfit
        self.run_json = self.work / "run.json"
        self.run = json.loads(self.run_json.read_text(encoding="utf-8")) if self.run_json.is_file() else {
            "character": character, "outfit": outfit, "steps": {}}

    def data(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    def tool(self, rel: str) -> Path:
        """A repo file named in an outfit file (prompts, looks): this repo first, else the data root."""
        p = REPO / rel
        return p if p.exists() else self.data(rel)

    def save(self) -> None:
        self.work.mkdir(parents=True, exist_ok=True)
        self.run_json.write_text(json.dumps(self.run, indent=1), encoding="utf-8")

    def step(self, name: str) -> dict:
        return self.run["steps"].get(name, {})

    def record(self, name: str, **fields) -> None:
        s = self.run["steps"].setdefault(name, {})
        s.update(fields)
        s["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save()

    def done(self, name: str) -> bool:
        return self.step(name).get("status") in ("done", "skipped")

    def out(self, step: str, key: str) -> Path:
        v = self.step(step).get("outputs", {}).get(key)
        if not v:
            raise Stop(f"step {step} has no output {key!r} yet (run it first)")
        return self.data(v)

    def painted(self) -> Path:
        if self.o["kind"] == "cut":
            return self.data(self.o["source_mesh"])
        return self.out("paint", "painted")


def call(cmd: list, ok: str | None = None, cwd: Path = REPO, show: bool = True) -> str:
    """Run a step's command; stream its output; fail unless it exits 0 (and prints `ok`, if given)."""
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in p.stdout:
        lines.append(line)
        if show:
            print("  | " + line.rstrip(), flush=True)
    p.wait()
    out = "".join(lines)
    if p.returncode or (ok and ok not in out):
        raise Stop(f"{Path(str(cmd[3] if str(cmd[1]) == '-m' else cmd[1])).name} failed (exit {p.returncode}{'' if not ok or ok in out else ', no ' + ok})")
    return out


def view_gate(ctx: Ctx, view: str, a) -> None:
    o, gate_dir = ctx.o, ctx.work / "gate"
    gate_json = gate_dir / f"gate_{view}.json"
    base = [sys.executable, "-m", "tools.boss_sprite_pipeline.view_gate", view, "--out", gate_dir,
            "--outfit", ctx.file]
    if view == "front":
        base += ["--input", ctx.data(o["concept"])]
    else:
        base += ["--front", ctx.out("front", "draw")]
    gate = json.loads(gate_json.read_text(encoding="utf-8")) if gate_json.is_file() else {}
    if a.accept is not None:
        call(base + ["--accept", a.accept], ok="accepted attempt")
    elif gate.get("status") != "accepted":
        call(base + ["--no-ask"] + (["--retry", a.retry] if a.retry else []), ok="PENDING")
    gate = json.loads(gate_json.read_text(encoding="utf-8"))
    if gate.get("status") != "accepted":
        last = gate["attempts"][-1]
        ctx.record(view, status="gate", attempts=len(gate["attempts"]), sheet=gate.get("sheet"))
        raise Stop(f"{view} attempt {last['attempt']} drawn: look at {gate.get('sheet')}\n"
                   f"  accept:  outfit.py {ctx.character} {ctx.outfit} --only {view} --accept {last['attempt']}\n"
                   f"  redraw:  outfit.py {ctx.character} {ctx.outfit} --only {view} --retry r|r1|rb|\"r <why> @img\"")
    n = gate["accepted"]
    draw = next(t["draw"] for t in gate["attempts"] if t["attempt"] == n)
    ctx.record(view, status="done", accepted=n, outputs={"draw": draw, "cutout": str(gate_dir / f"{view}.png"),
                                                         "gate": str(gate_json)})


def pod_args(ctx: Ctx, a) -> list:
    host, port = a.host or os.environ.get("POD_HOST"), a.port or os.environ.get("POD_PORT")
    if not host or not port:
        raise Stop("a pod step: start a pod, then rerun with --host <ip> --port <port> (or set POD_HOST / POD_PORT)")
    return ["--host", host, "--port", port, "--work", ctx.work]


def pod(ctx: Ctx, step: str, a, token: bool = False, extra: list = ()) -> float:
    t0 = time.time()
    base = [sys.executable, TOOLS / "gpu_box" / "pod.py", step]
    args = pod_args(ctx, a) + list(extra)
    if token:
        call(base + ["token"] + args, ok="token written")
    for action in ("push", "run", "pull"):
        call(base + [action] + args, ok="PULL_OK" if action == "pull" else None)
    return round((time.time() - t0) / 60, 1)


def s_trellis(ctx: Ctx, a) -> None:
    out = ctx.work / "trellis"
    have = {m: out / f"{m}_from_front.glb" for m in ("front_only", "front_back")}
    if not any(p.is_file() for p in have.values()):
        if not (ctx.work / "gate" / "front.png").is_file():
            shutil.copy(ctx.out("front", "cutout"), ctx.work / "gate" / "front.png")
        minutes = pod(ctx, "trellis", a, token=True)
        ctx.record("trellis", pod_minutes=minutes)
    models = {m: str(p) for m, p in have.items() if p.is_file()}
    if a.pick:
        if a.pick not in models:
            raise Stop(f"no {a.pick} model; have {sorted(models)}")
        ctx.record("trellis", status="done", picked=a.pick, outputs={**models, "picked": models[a.pick]})
        return
    ctx.record("trellis", status="gate", outputs=models)
    raise Stop("TRELLIS made " + ", ".join(models) + ": open both, pick by eye:\n"
               f"  outfit.py {ctx.character} {ctx.outfit} --only trellis --pick front_only|front_back")


def s_skeleton(ctx: Ctx, a) -> None:
    rigged = ctx.work / "rigged.glb"
    call([ctx.bpy, TOOLS / "explode2" / "outfit_skeleton.py", ctx.data(ctx.o["rig_fit"]),
          ctx.out("trellis", "picked"), rigged], ok="SKELETON_OK")
    ctx.record("skeleton", status="done", outputs={"rigged": str(rigged)})


def s_paint(ctx: Ctx, a) -> None:
    o, paint = ctx.o, ctx.work / "paint"
    if a.accept is not None and (paint / "result").is_dir():
        painted = next(iter(glob.glob(str(paint / "result" / "*_painted.glb"))), None)
        ctx.record("paint", status="done", outputs={"painted": painted,
                                                    "check": str(paint / "result" / "after_0_body_0.png")})
        return
    cmd = [ctx.bpy, TOOLS / "repaint" / "paint_outfit.py", ctx.out("skeleton", "rigged"), paint,
           ctx.out("front", "draw"), ctx.data(o["roles"]), ctx.tool(o["paint_look"])]
    call(cmd + (["--redo"] + a.redo if a.redo else []), ok="PAINT_OUTFIT_DONE")
    check = paint / "result" / "after_0_body_0.png"
    ctx.record("paint", status="gate", outputs={"check": str(check)})
    raise Stop(f"painted: look at {check} (and the other after_*.png beside it)\n"
               f"  continue: outfit.py {ctx.character} {ctx.outfit} --only paint --accept 1\n"
               f"  repaint views: outfit.py {ctx.character} {ctx.outfit} --only paint --redo <view> ...")


def s_views(ctx: Ctx, a) -> None:
    o, views = ctx.o, ctx.work / "views"
    call([ctx.bpy, TOOLS / "explode" / "explode_render.py", ctx.painted(), views,
          f"greedy:{ctx.data(o['greedy_dirs'])}:{o.get('views', 32)}", "--diag", ctx.work / "diag_step3_render.json"])
    ctx.record("views", status="done", outputs={"views": str(views)})


def sam_prompts(ctx: Ctx) -> Path:
    p = ctx.o["sam"]["prompts"]
    if isinstance(p, str):
        return ctx.tool(p)
    path = ctx.work / "sam_prompts.json"
    path.write_text(json.dumps(p, indent=1), encoding="utf-8")
    return path


def s_sam3(ctx: Ctx, a) -> None:
    minutes = pod(ctx, "sam3", a, token=False, extra=["--prompts", sam_prompts(ctx)])
    n = len(glob.glob(str(ctx.work / "views" / "masks" / "*__*.png")))
    ctx.record("sam3", status="done", pod_minutes=minutes, masks=n, outputs={"masks": str(ctx.work / "views" / "masks")})


def s_cut(ctx: Ctx, a) -> None:
    o = ctx.o
    cmd = [ctx.bpy, TOOLS / "explode" / "explode_label.py", ctx.out("views", "views"), "--facing-power", 8,
           "--belt-gate", "--crease-snap", "--dirs", o.get("views", 32), "--out", ctx.work / "cut",
           "--diag", ctx.work / "diag_step5_label.json"]
    if "prompt_to_part" in o.get("sam", {}):
        cmd += ["--prompt-map", ctx.file]
    call(cmd, ok="LABEL_OK")
    ctx.record("cut", status="done", outputs={"cut": str(ctx.work / "cut"),
                                              "sheet": str(ctx.work / "cut" / "PARTS_SHEET.png")})


def s_holopart(ctx: Ctx, a) -> None:
    if not ctx.o.get("holopart", True):
        ctx.record("holopart", status="skipped", note="outfit: holopart false")
        return
    minutes = pod(ctx, "holopart", a)
    ctx.record("holopart", status="done", pod_minutes=minutes,
               outputs={"output": str(ctx.work / "holopart" / "output.glb")})


def s_merge(ctx: Ctx, a) -> None:
    cut = ctx.work / "cut"
    shutil.copy(ctx.out("views", "views") / "cams.json", cut / "cams.json")
    hp = ctx.work / "holopart" / "output.glb"
    has_hp = ctx.step("holopart").get("status") == "done" and hp.is_file()
    call([ctx.bpy, TOOLS / "explode" / "explode_merge.py", cut] + ([hp] if has_hp else []), ok="MERGE_OK")
    if has_hp:
        call([ctx.bpy, TOOLS / "explode" / "explode_show.py", cut, hp])
    ctx.record("merge", status="done", outputs={"shells": str(cut / "shells_parts.glb")})


def s_worn(ctx: Ctx, a) -> None:
    o = ctx.o
    body = ctx.data(o["rig_fit"])
    if o.get("worn_on"):
        other = Ctx(ctx.character, o["worn_on"])
        if other.step("paint").get("status") != "done":
            ctx.record("worn", status="skipped", note=f"{o['worn_on']} not painted yet: worn on {o['rig_fit']}")
        else:
            body = other.painted()
    worn = ctx.work / "worn"
    call([ctx.bpy, TOOLS / "explode" / "explode_pose.py", "--texture", "--aligned", "--rigid", "--hide-under", body,
          ctx.data(o["roles"]), worn, f"outfit={ctx.out('merge', 'shells')}"])
    sheet = next(iter(glob.glob(str(worn / "POSE_COMPARE*.png"))), None)
    ctx.record("worn", status="done", body=str(body), outputs={"sheet": sheet})


def s_slots(ctx: Ctx, a) -> None:
    o, slots = ctx.o, ctx.work / "slots"
    call([ctx.bpy, TOOLS / "explode2" / "armour_slots.py", ctx.data(o["rig_game"]), ctx.data(o["roles"]),
          ctx.out("merge", "shells"), slots], ok="SLOTS_OK")
    ctx.record("slots", status="done", outputs={"slots": str(slots / "slots_parts.glb")})


def s_sheet(ctx: Ctx, a) -> None:
    sheet = ctx.work / "slots" / "SLOTS_SHEET.png"
    call([ctx.bpy, TOOLS / "explode2" / "pieces_sheet.py", ctx.out("slots", "slots"), sheet, "--slots"],
         ok="PIECES_OK")
    ctx.record("sheet", status="done", outputs={"sheet": str(sheet)})


def s_export(ctx: Ctx, a) -> None:
    out = call([sys.executable, "-m", "tools.boss_sprite_pipeline.export_outfit", ctx.character, ctx.outfit],
               ok="EXPORT_OK")
    ctx.record("export", status="done", result=out.split("EXPORT_OK", 1)[1].strip()[:400])


RUN = {"front": lambda c, a: view_gate(c, "front", a), "back": lambda c, a: view_gate(c, "back", a),
       "trellis": s_trellis, "skeleton": s_skeleton, "paint": s_paint, "views": s_views, "sam3": s_sam3,
       "cut": s_cut, "holopart": s_holopart, "merge": s_merge, "worn": s_worn, "slots": s_slots, "sheet": s_sheet,
       "export": s_export}


def backfill(ctx: Ctx) -> None:
    existing = ctx.o.get("existing")
    if not existing:
        sys.exit("this outfit has no 'existing' outputs to backfill")
    for step, outs in existing.items():
        files = {k: v for k, v in outs.items() if isinstance(v, str) and k != "picked"}
        missing = [v for v in files.values() if not ctx.data(v).exists()]
        extra = {k: v for k, v in outs.items() if not isinstance(v, str) and k != "picked"}
        ctx.record(step, status="done" if not missing else "missing", backfilled=True,
                   outputs={k: str(ctx.data(v)) for k, v in files.items()}, missing=missing,
                   **({"picked": outs["picked"]} if "picked" in outs else {}), **extra)
    for step in ("front", "back"):
        s = ctx.step(step)
        if "draw" not in s.get("outputs", {}) and "gate" in s.get("outputs", {}):
            g = json.loads(Path(s["outputs"]["gate"]).read_text(encoding="utf-8"))
            s["outputs"]["draw"] = next(t["draw"] for t in g["attempts"] if t["attempt"] == g["accepted"])
    if "trellis" in existing:
        t = ctx.step("trellis")
        t["outputs"]["picked"] = t["outputs"][existing["trellis"]["picked"]]
    ctx.save()
    print(f"backfilled {ctx.run_json}")


def status(ctx: Ctx) -> None:
    print(f"{ctx.character}/{ctx.outfit} ({ctx.o['kind']}), run: {ctx.run_json}")
    for name in STEPS[ctx.o["kind"]]:
        s = ctx.step(name)
        st = s.get("status", "-")
        extra = "  ".join(f"{k}={Path(v).name if isinstance(v, str) else v}" for k, v in s.get("outputs", {}).items())
        print(f"  {name:9s} {st:8s} {extra}")
        for m in s.get("missing", []):
            print(f"            missing: {m}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("character")
    ap.add_argument("outfit")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--only")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--retry")
    ap.add_argument("--accept", type=int)
    ap.add_argument("--pick", choices=("front_only", "front_back"))
    ap.add_argument("--redo", nargs="+")
    a = ap.parse_args(argv)
    ctx = Ctx(a.character, a.outfit)
    if a.backfill:
        backfill(ctx)
    if a.status or a.backfill:
        status(ctx)
        return
    steps = STEPS[ctx.o["kind"]]
    for s in (a.only, a.start):
        if s and s not in steps:
            sys.exit(f"{s} is not a step of a {ctx.o['kind']} outfit: {steps}")
    todo = [a.only] if a.only else steps[steps.index(a.start):] if a.start else [s for s in steps if not ctx.done(s)]
    for name in todo:
        print(f"=== {name}", flush=True)
        try:
            RUN[name](ctx, a)
        except Stop as stop:
            print(f"\nSTOPPED at {name}: {stop}")
            sys.exit(2)
        if a.only:
            break
        a.accept = a.retry = a.pick = a.redo = None        # those answered the first step only
    print("\nOUTFIT_DONE" if not a.only else f"\nSTEP_DONE {a.only}")


if __name__ == "__main__":
    main()
