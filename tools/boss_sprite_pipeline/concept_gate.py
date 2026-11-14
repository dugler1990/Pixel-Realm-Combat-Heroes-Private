"""A new character's concept: its description as a prompt with context images → candidates, each checked; you pick one.

    python -m tools.boss_sprite_pipeline.concept_gate --out <dir> --outfit <outfit.json>
        [--count N] [--retry "r <why>"] [--accept N] [--dry-run]

From the outfit file (outfit_fields.py):
  concept_prompt   the description ("a hooded ice wizard with a staff ...")
  concept_config   the image model's config (an image_client config: OpenAI gpt-image, Leonardo ...)
  concept_refs     images of how it should look (optional; paths relative to the data root)
  concept_count    candidates per call (else --count)
  view_prompts     its "concept" block: the prompt around the description, the pose image (the A-pose stick figure),
                   the lines naming the look images and the retry line
  view_checks      its "concept" block: arm angle range, frame margin, background (default.json when not set)
Context goes in the way each model takes it (image_client): the images in the request, named "Image 1..." in the
prompt; Leonardo gets a strength per image (the pose HIGH, the look images MID).

Each candidate: pose_heights.py --arms on it: one person, arms within the range from straight down, the figure
clear of the edges, a white background. <out>/gate_concept.json records the attempts (pending until accepted),
<out>/CONCEPT_SHEET.png shows the latest candidates with PASS / FAIL. --accept N copies attempt N to
<out>/concept.png. Prints PENDING / accepted attempt N, and the cost the client prints.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[1]
POSE_PYTHON = TOOLS / ".venv-pose" / "Scripts" / "python.exe"
CHECKS = TOOLS / "view_checks" / "default.json"


def repo_file(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else REPO / p


def data_file(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else Path(os.environ.get("OUTFIT_DATA_ROOT") or REPO) / p


def build_prompt(block: dict, description: str, n_refs: int, why: str | None) -> str:
    prompt = block["prompt"].format(description=description.strip())
    if n_refs == 1:
        prompt += block["refs_one"].format(first=2)
    elif n_refs > 1:
        prompt += block["refs"].format(first=2, last=1 + n_refs)
    if why:
        prompt += block["retry"].format(why=why)
    return prompt


def poses(images: list[Path]) -> dict:
    """pose_heights.py --arms on the images: {path: {joints..., "_arms", "_people"} or None}."""
    if not POSE_PYTHON.exists():
        sys.exit(f"the concept check needs the pose venv: {POSE_PYTHON} (see pose_heights.py)")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "poses.json"
        subprocess.run([str(POSE_PYTHON), str(TOOLS / "pose_heights.py"), *map(str, images), "--arms", "--json",
                        str(out)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return json.loads(out.read_text(encoding="utf-8"))


def check(path: Path, pose: dict | None, limits: dict) -> dict:
    """PASS / FAIL of one candidate, with what failed."""
    im = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    h, w = im.shape[:2]
    figure = (im < 240).any(axis=2)
    ys, xs = np.nonzero(figure)
    m = limits["frame_margin"]
    border = np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]])
    s = {"people": (pose or {}).get("_people", 0), "arms": (pose or {}).get("_arms"),
         "background": round(float(border.mean()), 1),
         "clear_of_edges": bool(len(ys)) and ys.min() > m * h and ys.max() < (1 - m) * h
         and xs.min() > m * w and xs.max() < (1 - m) * w}
    fail = []
    if not pose:
        fail.append("no person found")
    elif s["people"] != 1:
        fail.append(f"{s['people']} people")
    if s["arms"]:
        lo, hi = limits["arm_deg"]
        fail += [f"{side} arm {v:.0f} deg (A-pose: {lo:.0f}-{hi:.0f})" for side, v in s["arms"].items()
                 if not lo <= v <= hi]
    if not s["clear_of_edges"]:
        fail.append("figure touches the edge (cut off)")
    if s["background"] < limits["background_min"]:
        fail.append(f"background not white ({s['background']:.0f})")
    s["passed"], s["failing"] = not fail, fail
    return s


def concept_sheet(attempts: list[dict], path: Path) -> Path:
    tile, head = 384, 64
    out = Image.new("RGB", (tile * len(attempts), tile * 3 // 2 + head), (25, 25, 28))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for i, t in enumerate(attempts):
        im = Image.open(t["draw"]).convert("RGB")
        im.thumbnail((tile, tile * 3 // 2))
        out.paste(im, (i * tile + (tile - im.width) // 2, head))
        sc = t["scores"]
        draw.text((i * tile + 6, 4), f"{t['attempt']}: {'PASS' if sc['passed'] else 'FAIL'}",
                  fill=(90, 200, 120) if sc["passed"] else (230, 90, 90), font=font)
        draw.text((i * tile + 6, 24), "; ".join(sc["failing"])[:60], fill=(220, 220, 220), font=font)
        if sc.get("arms"):
            draw.text((i * tile + 6, 44), f"arms {sc['arms']['left']:.0f} / {sc['arms']['right']:.0f} deg",
                      fill=(160, 160, 170), font=font)
    out.save(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--outfit", required=True, type=Path)
    ap.add_argument("--count", type=int)
    ap.add_argument("--retry", help="r <why>: generate again, saying what was wrong")
    ap.add_argument("--accept", type=int)
    ap.add_argument("--dry-run", action="store_true", help="print the prompt and the images; no call")
    a = ap.parse_args()
    o = json.loads(a.outfit.read_text(encoding="utf-8"))
    missing = [k for k in ("concept_prompt", "concept_config", "view_prompts") if not o.get(k)]
    if missing:
        sys.exit("the concept needs " + ", ".join(missing) + " in the outfit file")
    vp = json.loads(repo_file(o["view_prompts"]).read_text(encoding="utf-8"))
    if "concept" not in vp:
        sys.exit(f"{o['view_prompts']} has no concept block")
    block = vp["concept"]
    limits = json.loads(repo_file(o.get("view_checks") or CHECKS).read_text(encoding="utf-8"))["concept"]
    a.out.mkdir(parents=True, exist_ok=True)
    gate_json = a.out / "gate_concept.json"
    gate = json.loads(gate_json.read_text(encoding="utf-8")) if gate_json.is_file() else {"attempts": []}

    if a.accept is not None:
        hit = [t for t in gate["attempts"] if t["attempt"] == a.accept]
        if not hit:
            sys.exit(f"no attempt {a.accept} in {gate_json}")
        shutil.copy(hit[0]["draw"], a.out / "concept.png")
        gate.update(status="accepted", accepted=a.accept, concept=str(a.out / "concept.png"))
        gate_json.write_text(json.dumps(gate, indent=1), encoding="utf-8")
        print(f"accepted attempt {a.accept} -> {a.out / 'concept.png'}")
        return

    why = None
    if a.retry:
        r = a.retry.strip()
        if not (r == "r" or r.startswith("r ")):
            sys.exit("--retry: r, or r <why>")
        why = r[1:].strip() or None
    refs = [data_file(p) for p in o.get("concept_refs") or []]
    images = [repo_file(block["pose_ref"]), *refs]
    for p in images:
        if not p.is_file():
            sys.exit(f"no image {p}")
    prompt = build_prompt(block, o["concept_prompt"], len(refs), why)
    count = a.count or int(o.get("concept_count") or 4)
    if a.dry_run:
        print(prompt)
        print("--- images: " + ", ".join(str(p) for p in images), file=sys.stderr)
        print(f"--- {count} candidates, config {o['concept_config']}", file=sys.stderr)
        return

    sys.path.insert(0, str(REPO))
    from tools.painted_map_pipeline.image_client import make_image_client
    config = json.loads(repo_file(o["concept_config"]).read_text(encoding="utf-8"))
    client = make_image_client(config)
    strengths = (["HIGH"] + ["MID"] * len(refs)) if config.get("provider") == "leonardo" else None
    n = max((t["attempt"] for t in gate["attempts"]), default=0)
    new = []
    for _ in range(count):
        n += 1
        draw = a.out / f"concept_attempt_{n:02d}.png"
        (a.out / f"concept_attempt_{n:02d}_prompt.txt").write_text(prompt, encoding="utf-8")
        result = client.generate(prompt, [str(p) for p in images], str(draw), strengths=strengths)
        (a.out / f"concept_attempt_{n:02d}_request.json").write_text(json.dumps(
            {"images": [str(p) for p in images], "strengths": strengths, "result": result}, indent=1, default=str),
            encoding="utf-8")
        new.append({"attempt": n, "draw": str(draw), "prompt": prompt, "why": why})
    found = poses([Path(t["draw"]) for t in new])
    for t in new:
        t["scores"] = check(Path(t["draw"]), found.get(t["draw"]), limits)
        print(f"  attempt {t['attempt']}: {'PASS' if t['scores']['passed'] else 'FAIL ' + '; '.join(t['scores']['failing'])}")
    gate["attempts"] += new
    sheet = concept_sheet(new, a.out / "CONCEPT_SHEET.png")
    for t in new:
        t["sheet"] = str(sheet)
    gate.update(status="pending", sheet=str(sheet), config=o["concept_config"])
    gate_json.write_text(json.dumps(gate, indent=1), encoding="utf-8")
    print(f"  {sheet}")
    print(f"  PENDING attempts {new[0]['attempt']}-{new[-1]['attempt']}: --accept N, or --retry \"r <why>\"")


if __name__ == "__main__":
    main()
