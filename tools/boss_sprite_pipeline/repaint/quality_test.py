"""Same close-up through other models / qualities / sizes: is the cheaper painting as good on the model?

    .venv-bpy/Scripts/python.exe quality_test.py <work_dir> <view> <combo> [...]

combo = provider:model:quality:size, or quality:size for OpenAI gpt-image-2. Examples:
    openai:gpt-image-2:medium:1024   openai:gpt-image-2:low:816 (smallest: 655,360 px minimum)
    openai:gpt-image-1-mini:low:1024 (mini: 1024 only)   leonardo:nano-banana-2:-:1024

Re-sends the accepted painting's exact inputs (prompt, flat render, clay render, reference, colour
anchor) with only the model / quality / size changed. Writes <work>/quality_test/<view>/<label>/
(output.png, check.json with usage and cost) and two sheets in <work>/quality_test/:
  QUALITY_<view>.png  the 3D render that went in, then every version big, with cost and silhouette match
  ALIGN_<view>.png    the model's outline and skin edge drawn over each version, and a close-up shrunk to
                      what the texture keeps (TEXTURE_PX: the 4096 atlas gives the barb's face ~263 texels)
A combo that fails is logged and skipped. The sheets include every earlier finished run of the view, so
one combo can be added later on its own; with no combos the sheets are just rebuilt (no API calls).
Keys from the environment: OPENAI_API_KEY, LEONARDO_API_KEY.
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BOSS = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
sys.path.insert(0, BOSS)
from tools.painted_map_pipeline.openai_api import edit_image  # noqa: E402

# USD per 1M tokens, OpenAI Standard (developers.openai.com/api/docs/pricing, read 2026-11-02)
PRICES = {"gpt-image-2": {"text_in": 5.0, "image_in": 8.0, "image_out": 30.0},
          "gpt-image-1.5": {"text_in": 5.0, "image_in": 8.0, "image_out": 32.0},
          "gpt-image-1-mini": {"text_in": 2.0, "image_in": 2.5, "image_out": 8.0}}
TEXTURE_PX = {"face_front": 263, "head_back": 379, "hand_l_out": 392, "hand_r_out": 377, "chest_front": 650,
              "leg_l_front": 923, "legs_back": 1056, "pelvis_front": 592}   # barb, 1 px per texel (PROCESS_repaint.md)

WORK, VIEW = os.path.abspath(sys.argv[1]), sys.argv[2]


def parse(c):
    p = c.split(":")
    return ("openai", "gpt-image-2", p[0], int(p[1])) if len(p) == 2 else (p[0], p[1], p[2], int(p[3]))


def usd(model, u):
    pr = PRICES.get(model)
    if not pr or not u:
        return None
    i, o = u.get("input_tokens_details", {}), u.get("output_tokens_details", {})
    return (i.get("text_tokens", 0) * pr["text_in"] + i.get("image_tokens", 0) * pr["image_in"]
            + o.get("image_tokens", 0) * pr["image_out"]) / 1e6


att = open(os.path.join(WORK, "gen", VIEW, "ACCEPTED.txt")).read().strip()
views = json.load(open(os.path.join(WORK, "cams.json")))["views"]
v = next(x for x in views if x["name"] == VIEW)
bodies = [b for b in views if b["kind"] == "body"]
near = min(bodies, key=lambda b: min(abs(b["yaw"] - v["yaw"]) % 360, 360 - abs(b["yaw"] - v["yaw"]) % 360))
anchor = os.path.join(open(os.path.join(WORK, "gen", near["name"], "ACCEPTED.txt")).read().strip(), "output.png")
imgs = [Path(att, x) for x in ("input.png", "clay.png", "ref.png")] + [Path(anchor)]
prompt = open(os.path.join(att, "prompt.txt")).read().strip()
base = json.load(open(os.path.join(att, "check.json")))
size0 = Image.open(os.path.join(att, "output.png")).size[0]
results = [(f"gpt-image-2 high {size0} (the one used)", os.path.join(att, "output.png"), usd("gpt-image-2", base.get("usage")))]

for combo in sys.argv[3:]:
    provider, model, q, size = parse(combo)
    label = f"{model} {q} {size}" if q != "-" else f"{model} {size}"
    out = os.path.join(WORK, "quality_test", VIEW, label.replace(" ", "_"))
    os.makedirs(out, exist_ok=True)
    t = time.time()
    try:
        if provider == "openai":
            info = edit_image(prompt=prompt, input_images=imgs, mask=None, output_path=Path(out, "output.png"),
                              width=size, height=size,
                              config={"model": model, "quality": q, "config_source": "quality_test"})
            cost = usd(model, info.get("usage"))
            rec = {"usage": info.get("usage")}
        else:
            from tools.painted_map_pipeline.leonardo_api import generate_with_image_reference
            cfg = {"model": model}
            if q != "-":
                cfg["quality"] = q
            info = generate_with_image_reference(prompt=prompt, input_images=imgs, output_path=Path(out, "output.png"),
                                                 width=size, height=size, config=cfg)
            cost = info.get("cost_usd")
            rec = {"generation_id": info.get("generation_id")}
    except Exception as e:                         # one failed combo must not lose the others
        print(f"FAIL {label}: {str(e)[:300]}", flush=True)
        continue
    rec.update({"provider": provider, "model": model, "quality": q, "size": size, "usd": cost,
                "seconds": round(time.time() - t)})
    json.dump(rec, open(os.path.join(out, "check.json"), "w"), indent=1)
    print(f"{label}: ${cost if cost is not None else float('nan'):.3f}, {time.time() - t:.0f} s", flush=True)

# the sheet shows every finished run of this view, so a combo can be run (or re-run) on its own later
for chk in sorted(Path(WORK, "quality_test", VIEW).glob("*/check.json")):
    r = json.load(open(chk))
    label = f"{r['model']} {r['quality']} {r['size']}" if r["quality"] != "-" else f"{r['model']} {r['size']}"
    results.append((label, str(chk.parent / "output.png"), r.get("usd")))

# Two sheets. QUALITY_<view>.png: the 3D render that went in, then every painting big, with cost and
# silhouette match (the IoU repaint.py's gen records: painted pixels vs the render's alpha, 1.0 = same
# outline). ALIGN_<view>.png: each painting with the model's outline (cyan) and its skin edge (yellow:
# hairline, brows, beard; skin = R-G > 18 in the flat render) drawn on top, so drift is visible; under
# it a close-up (CROP) at the size the texture keeps (TEXTURE_PX).
CROP = {"face_front": (0.25, 0.42, 0.75, 0.92)}   # brows, eyes, nose, moustache
flat = Image.open(os.path.join(WORK, VIEW + "_flat.png")).convert("RGBA")
try:
    font = ImageFont.truetype("arial.ttf", 22)
except OSError:
    font = ImageFont.load_default()


def match(path):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    a = np.asarray(flat.resize(rgb.shape[1::-1], Image.NEAREST))[..., 3] > 8
    ng = np.abs(rgb - 128).max(2) > 18
    return float((ng & a).sum() / max((ng | a).sum(), 1))


def edge(m):
    im = Image.fromarray(m.astype(np.uint8) * 255)
    return np.asarray(im.filter(ImageFilter.MaxFilter(5))) != np.asarray(im.filter(ImageFilter.MinFilter(3)))


def caption(d, x, y, lines):
    for k, s in enumerate(lines):
        d.text((x + 8, y + 6 + 26 * k), s, fill=(235, 235, 235), font=font)


T, LAB = 640, 62
cells = [("3D render that went in", "flat colours of the model", os.path.join(att, "input.png"))]
cells += [(label, (f"${cost:.3f}" if cost is not None else "cost n/a") + f"   silhouette match {match(p):.2f}", p)
          for label, p, cost in results]
cols = 3
sheet = Image.new("RGB", (T * cols, (T + LAB) * -(-len(cells) // cols)), (25, 25, 28))
d = ImageDraw.Draw(sheet)
for i, (l1, l2, p) in enumerate(cells):
    x, y = T * (i % cols), (T + LAB) * (i // cols)
    sheet.paste(Image.open(p).convert("RGB").resize((T, T), Image.LANCZOS), (x, y + LAB))
    caption(d, x, y, [l1, l2])
sheet.save(os.path.join(WORK, "quality_test", f"QUALITY_{VIEW}.png"))

A, tp = 520, TEXTURE_PX.get(VIEW, 512)
fa = np.asarray(flat.resize((A, A), Image.BILINEAR)).astype(int)
inside = fa[..., 3] > 128
sil, skin = edge(inside), edge(inside & (fa[..., 0] - fa[..., 1] > 18))
c = CROP.get(VIEW, (0.25, 0.25, 0.75, 0.75))
sheet = Image.new("RGB", (A * len(results), 2 * (A + LAB)), (25, 25, 28))
d = ImageDraw.Draw(sheet)
for i, (label, p, cost) in enumerate(results):
    im = Image.open(p).convert("RGB")
    ov = np.asarray(im.resize((A, A), Image.LANCZOS)).copy()
    ov[skin], ov[sil] = (255, 220, 0), (0, 255, 255)
    sheet.paste(Image.fromarray(ov), (i * A, LAB))
    held = im.resize((tp, tp), Image.LANCZOS)
    box = tuple(round(v * tp) for v in c)
    sheet.paste(held.crop(box).resize((A, A), Image.BICUBIC), (i * A, 2 * LAB + A))
    caption(d, i * A, 0, [label, "lines = the 3D model (should sit on the painting)"])
    caption(d, i * A, LAB + A, ["close-up as the texture keeps it", f"({tp} px across the whole view)"])
sheet.save(os.path.join(WORK, "quality_test", f"ALIGN_{VIEW}.png"))
print("QUALITY_OK", os.path.join(WORK, "quality_test", f"QUALITY_{VIEW}.png"),
      os.path.join(WORK, "quality_test", f"ALIGN_{VIEW}.png"), flush=True)
