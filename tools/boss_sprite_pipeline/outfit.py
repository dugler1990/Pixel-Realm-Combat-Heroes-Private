"""The outfit pipeline's driver: one command per character + outfit (PROCESS_outfit.md).

    python -m tools.boss_sprite_pipeline.outfit <character> <outfit> [--status] [--backfill]
        [--from STEP] [--only STEP] [--host IP --port PORT] [--models a,b] [--view V]
        [--retry R | --accept N | --pick M | --redo VIEW...]

Runs the outfit's steps in order from the first one not done, recording each in
<data>/generated/bosses/<character>/outfits/<outfit>/run.json (log per step: <run>/logs/<step>.log), and stops:
- at a gate: front / back / sides (view_gate draws; --accept N or --retry r|r1|rb|"r <why> @img"; sides: --view
  left|front_left|back_left), trellis (several models: --pick one, by eye), paint (look at the check image;
  --accept, or --redo views)
--models: which TRELLIS models to build (front_only, front_back, front_back_sides, eight_views; default
  DEFAULT_MODELS, or the outfit's "trellis_models"); they decide which drawings are asked for.
- before a pod step without --host / --port (or POD_HOST / POD_PORT); you start and stop the pod
- at the first step that fails.
Steps by the outfit's kind:
    body    front back sides trellis skeleton paint export
    armour  front back sides trellis skeleton paint views sam3 cut holopart merge worn slots sheet export
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
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[1]
STEPS = {
    "body": ["front", "back", "sides", "trellis", "skeleton", "paint", "export"],
    "armour": ["front", "back", "sides", "trellis", "skeleton", "paint", "views", "sam3", "cut", "holopart", "merge",
               "worn", "slots", "sheet", "export"],
    "cut": ["views", "sam3", "cut", "holopart", "merge", "worn", "slots", "sheet", "export"],
}
POD_STEPS = {"trellis", "sam3", "holopart"}
# TRELLIS models and the drawings each needs. The default is a setting: an outfit's "trellis_models" or --models
# overrides it (2026-11-13, naked barb: front + back + sides and 8 views both better than front + back by eye).
MODEL_VIEWS = {
    "front_only": ["front"],
    "front_back": ["front", "back"],
    "front_back_sides": ["front", "back", "left", "right"],
    "eight_views": ["front", "back", "left", "right", "front_left", "front_right", "back_left", "back_right"],
}
DEFAULT_MODELS = ["eight_views"]
# Side views in drawing order: the left side first (the 3/4 views are sent it); the right-hand views are the
# left-hand ones mirrored unless the outfit says "mirror_right": false (drawn alone they came out short, as four
# small figures, or from the front: 2026-11-13).
SIDE_ORDER = ["left", "front_left", "back_left", "right", "front_right", "back_right"]
MIRROR_OF = {"right": "left", "front_right": "front_left", "back_right": "back_left"}
LOG = None                       # the running step's log file (<run>/logs/<step>.log)
COST = [0.0]                     # $ printed by the running step's commands (paint prints one per view)


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

    def models(self) -> list[str]:
        """The TRELLIS models this run builds: --models (kept in run.json), else the outfit's, else the default."""
        return list(self.run.get("models") or self.o.get("trellis_models") or DEFAULT_MODELS)

    def views(self) -> list[str]:
        """The drawings the chosen models need."""
        need = {v for m in self.models() for v in MODEL_VIEWS[m]}
        return [v for v in ["front", "back"] + SIDE_ORDER if v in need]


def call(cmd: list, ok: str | None = None, cwd: Path = REPO, show: bool = True) -> str:
    """Run a step's command; stream its output; fail unless it exits 0 (and prints `ok`, if given)."""
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    lines = []
    if LOG:
        LOG.write("$ " + " ".join(str(c) for c in cmd) + "\n")
    for line in p.stdout:
        lines.append(line)
        if show:
            print("  | " + line.rstrip(), flush=True)
        if LOG:
            LOG.write(line)
            LOG.flush()
    p.wait()
    out = "".join(lines)
    COST[0] += sum(float(x) for x in re.findall(r"\$(\d+\.\d+)", out))
    if p.returncode or (ok and ok not in out):
        raise Stop(f"{Path(str(cmd[3] if str(cmd[1]) == '-m' else cmd[1])).name} failed (exit {p.returncode}{'' if not ok or ok in out else ', no ' + ok})")
    return out


def view_gate(ctx: Ctx, view: str, a) -> None:
    if view not in ctx.views():
        ctx.record(view, status="skipped", note=f"not needed by {ctx.models()}")
        return
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


def s_sides(ctx: Ctx, a) -> None:
    """The side and 3/4 views the chosen models need, one gate each (gate_side_<view>.json). A view is done once
    its cut-out gate/side_<view>.png exists (view_gate's accept writes it; a mirrored one is written here)."""
    o, gate_dir = ctx.o, ctx.work / "gate"
    need = [v for v in SIDE_ORDER if v in ctx.views()]
    if not need:
        ctx.record("sides", status="skipped", note=f"not needed by {ctx.models()}")
        return
    mirror = o.get("mirror_right", True)
    if a.view and a.view not in need:
        raise Stop(f"--view {a.view} is not needed by {ctx.models()}: {need}")
    base = [sys.executable, "-m", "tools.boss_sprite_pipeline.view_gate", "side", "--out", gate_dir, "--outfit",
            ctx.file, "--front", ctx.out("front", "draw"), "--back", ctx.out("back", "draw")]
    if o.get("side_config"):
        base += ["--config", ctx.tool(o["side_config"])]
    for v in need:
        cutout = gate_dir / f"side_{v}.png"
        if cutout.is_file():
            continue
        if v in MIRROR_OF and mirror:
            src = gate_dir / f"side_{MIRROR_OF[v]}.png"
            from PIL import Image, ImageOps
            ImageOps.mirror(Image.open(src)).save(cutout)
            print(f"  {v}: {MIRROR_OF[v]} mirrored -> {cutout}", flush=True)
            continue
        cmd = base + ["--side", v]
        if v != "left" and (gate_dir / "side_left.png").is_file():
            cmd += ["--side-ref", gate_dir / "side_left.png"]
        if v in MIRROR_OF:
            cmd += ["--other-side", gate_dir / f"side_{MIRROR_OF[v]}.png"]
        gate_json = gate_dir / f"gate_side_{v}.json"
        gate = json.loads(gate_json.read_text(encoding="utf-8")) if gate_json.is_file() else {}
        mine = a.view == v or (a.view is None and v == next(x for x in need if not (gate_dir / f"side_{x}.png").is_file()))
        if mine and a.accept is not None:
            call(cmd + ["--accept", a.accept], ok="accepted attempt")
            continue
        if not gate.get("attempts") or (mine and a.retry):
            call(cmd + ["--no-ask"] + (["--retry", a.retry] if mine and a.retry else []), ok="PENDING")
            gate = json.loads(gate_json.read_text(encoding="utf-8"))
        last = gate["attempts"][-1]
        ctx.record("sides", status="gate", view=v, attempts=len(gate["attempts"]), sheet=gate.get("sheet"))
        raise Stop(f"{v} attempt {last['attempt']} drawn: look at {gate.get('sheet')}\n"
                   f"  accept:  outfit.py {ctx.character} {ctx.outfit} --only sides --view {v} --accept {last['attempt']}\n"
                   f"  redraw:  outfit.py {ctx.character} {ctx.outfit} --only sides --view {v} --retry r|\"r <why> @img\"")
    ctx.record("sides", status="done", view=None, outputs={v: str(gate_dir / f"side_{v}.png") for v in need})


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
        call(base + ["token"] + args, ok="TOKEN_OK")
    for action in ("push", "run", "pull"):
        call(base + [action] + args, ok="PULL_OK" if action == "pull" else None)
    return round((time.time() - t0) / 60, 1)


def trellis_sheet(ctx: Ctx, models: list[str]) -> Path:
    """Each model from the front, his left side and behind, one row per model: TRELLIS_SHEET.png."""
    from PIL import Image, ImageDraw
    out, tiles = ctx.work / "trellis", ctx.work / "trellis" / "sheet_tiles"
    call([ctx.bpy, TOOLS / "gpu_box" / "trellis_sheet.py", out, tiles, *models], ok="TILES_OK", show=False)
    w, h, top = 512, 768, 30
    sheet = Image.new("RGB", (w * 3, (h + top) * len(models)), "white")
    d = ImageDraw.Draw(sheet)
    for r, m in enumerate(models):
        d.text((8, r * (h + top) + 8), f"{m}   (front, his left side, back)", fill="black")
        for c, yaw in enumerate((0, 90, 180)):
            sheet.paste(Image.open(tiles / f"{m}_{yaw}.png").convert("RGB"), (c * w, r * (h + top) + top))
    path = out / "TRELLIS_SHEET.png"
    sheet.save(path)
    return path


def s_trellis(ctx: Ctx, a) -> None:
    out, models = ctx.work / "trellis", ctx.models()
    have = {m: out / f"{m}_from_front.glb" for m in MODEL_VIEWS}
    missing = [m for m in models if not have[m].is_file()]
    if missing:
        gate = ctx.work / "gate"
        if not (gate / "front.png").is_file():
            shutil.copy(ctx.out("front", "cutout"), gate / "front.png")
        minutes = pod(ctx, "trellis", a, token=True, extra=["--models", ",".join(missing)])
        ctx.record("trellis", pod_minutes=round(ctx.step("trellis").get("pod_minutes", 0) + minutes, 1))
        lost = [m for m in missing if not have[m].is_file()]
        if lost:
            raise Stop(f"TRELLIS gave no {lost}")
    made = {m: str(have[m]) for m in models}
    sheet = trellis_sheet(ctx, models)
    pick = a.pick or (models[0] if len(models) == 1 else None)
    if pick:
        if pick not in made:
            raise Stop(f"{pick} is not one of this run's models {models}")
        if ctx.step("trellis").get("last_picked") not in (None, pick):
            steps = STEPS[ctx.o["kind"]]
            for later in steps[steps.index("trellis") + 1:]:          # built on the other model: build again
                if ctx.step(later).get("status") in ("done", "gate"):
                    ctx.record(later, status="redo", note=f"TRELLIS pick changed to {pick}")
        ctx.record("trellis", status="done", picked=pick, last_picked=pick,
                   outputs={**made, "picked": made[pick], "sheet": str(sheet)})
        return
    ctx.record("trellis", status="gate", picked=None, outputs={**made, "sheet": str(sheet)})
    raise Stop(f"TRELLIS made {', '.join(models)}: look at {sheet}, pick one:\n"
               f"  outfit.py {ctx.character} {ctx.outfit} --only trellis --pick {'|'.join(models)}")


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
    body, note = ctx.data(o["rig_fit"]), None
    if o.get("worn_on"):
        other = Ctx(ctx.character, o["worn_on"])
        if other.step("paint").get("status") != "done":
            note = f"{o['worn_on']} not painted yet: worn on {o['rig_fit']}"   # recorded only once the test ran
        else:
            body = other.painted()
    worn = ctx.work / "worn"
    # A cut keeps the rest of the mesh as "body": only the pieces are worn (piece_weights has no rule for it).
    pieces = sorted(set(o.get("sam", {}).get("prompt_to_part", {}).values()) - {"body"})
    only = ["--only", ",".join(pieces)] if pieces else []
    call([ctx.bpy, TOOLS / "explode" / "explode_pose.py", "--texture", "--aligned", "--rigid", "--hide-under", *only,
          body, ctx.data(o["roles"]), worn, f"outfit={ctx.out('merge', 'shells')}"])
    sheet = next(iter(glob.glob(str(worn / "POSE_COMPARE*.png"))), None)
    ctx.record("worn", status="done", body=str(body), note=note, outputs={"sheet": sheet})


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
       "sides": s_sides, "trellis": s_trellis, "skeleton": s_skeleton, "paint": s_paint, "views": s_views, "sam3": s_sam3,
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
    ap.add_argument("--pick", choices=tuple(MODEL_VIEWS))
    ap.add_argument("--models", help=f"TRELLIS models, comma-separated, kept in run.json: {', '.join(MODEL_VIEWS)} "
                                     f"(default: the outfit's trellis_models, else {DEFAULT_MODELS})")
    ap.add_argument("--view", choices=SIDE_ORDER, help="sides: the view --accept / --retry answers")
    ap.add_argument("--redo", nargs="+")
    a = ap.parse_args(argv)
    ctx = Ctx(a.character, a.outfit)
    if a.models:
        models = [m for m in a.models.split(",") if m]
        bad = sorted(set(models) - set(MODEL_VIEWS))
        if bad or not models:
            sys.exit(f"unknown models {bad}; choose from {list(MODEL_VIEWS)}")
        ctx.run["models"] = models
        ctx.save()
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
    global LOG
    for name in todo:
        print(f"=== {name}", flush=True)
        (ctx.work / "logs").mkdir(parents=True, exist_ok=True)
        LOG = open(ctx.work / "logs" / f"{name}.log", "a", encoding="utf-8")
        LOG.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {name} {' '.join(sys.argv[1:])}\n")
        COST[0] = 0.0
        try:
            RUN[name](ctx, a)
        except Stop as stop:
            LOG.write(f"STOPPED: {stop}\n")
            LOG.close()
            note_cost(ctx, name)
            print(f"\nSTOPPED at {name}: {stop}")
            sys.exit(2)
        LOG.close()
        note_cost(ctx, name)
        if name in POD_STEPS and not any(s in POD_STEPS and not ctx.done(s) for s in steps[steps.index(name) + 1:]):
            print("\nstop the pod  (no pod step left for this outfit)", flush=True)
        if a.only:
            break
        a.accept = a.retry = a.pick = a.redo = a.view = None   # those answered the first step only
    print("\nOUTFIT_DONE" if not a.only else f"\nSTEP_DONE {a.only}")


def note_cost(ctx: Ctx, name: str) -> None:
    """Add the $ the step's commands printed (paint: one line per view) to its cost in run.json."""
    if COST[0]:
        ctx.record(name, cost_usd=round(ctx.step(name).get("cost_usd", 0) + COST[0], 3))


if __name__ == "__main__":
    main()
