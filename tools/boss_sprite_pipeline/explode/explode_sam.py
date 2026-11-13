"""Step 2: SAM3 text prompts on the lit renders -> 2D masks.

    C:\\Users\\Douglas\\sam3local\\.venv\\Scripts\\python.exe explode_sam.py <work_dir> [prompts.json]

Loads SAM3 once: by default the local copy (C:\\Users\\Douglas\\sam3local, GTX 1050: 560 px, fp16).
On a pod set SAM3_SRC (the sam3local/src dir), SAM3_MODEL (folder with the facebook/sam3 files),
SAM3_SIZE=1008 (SAM3's native input size) and SAM3_DTYPE=float32. For every
<cam>_lit.png in work_dir and every prompt for that crop, writes each instance scoring >= MIN_SCORE
as masks/<cam>__<prompt>__<k>__<score>.png (1-bit, top-down rows like the render), and
masks/<cam>_overlay.png with the best instance per prompt drawn in colour.
"""
import json
import os
import sys

sys.path.insert(0, os.environ.get("SAM3_SRC", r"C:\Users\Douglas\sam3local\src"))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from sam3_local.infer import segment_prompt  # noqa: E402

WORK = os.path.abspath(sys.argv[1])
CONFIG = {"model_id": os.environ.get("SAM3_MODEL", "facebook/sam3"), "image_size": int(os.environ.get("SAM3_SIZE", "560")),
          "dtype": os.environ.get("SAM3_DTYPE", "float16"), "threshold": 0.0, "mask_threshold": 0.5}
MIN_SCORE = 0.2
PROMPTS = {
    "upper": ["head", "hair", "beard", "breastplate", "shoulder armor", "upper arm armor", "elbow armor",
              "forearm armor", "gauntlet", "belt", "armored skirt", "neck armor"],
    "lower": ["belt", "armored skirt", "thigh armor", "knee armor", "shin armor", "armored boot", "gauntlet",
              "forearm armor"],
}
TAG = ""
if len(sys.argv) > 2:                      # extra prompts: overlays/scores get the file's name as a tag
    PROMPTS = json.load(open(sys.argv[2]))
    TAG = "_" + os.path.splitext(os.path.basename(sys.argv[2]))[0]
out = os.path.join(WORK, "masks")
os.makedirs(out, exist_ok=True)
cams = json.load(open(os.path.join(WORK, "cams.json")))["cams"]
# SAM3_SHARD=i/k: this process takes every k-th camera from i. The GPU idles (~14 %) while one CPU core
# post-processes masks, so k processes side by side finish ~k times sooner (each loads its own model).
SHARD = os.environ.get("SAM3_SHARD")
if SHARD:
    _i, _k = map(int, SHARD.split("/"))
    cams = cams[_i::_k]
    TAG += f"_shard{_i}"
rng = np.random.default_rng(3)
summary = {}
for c in cams:
    rgba = Image.open(os.path.join(WORK, c["name"] + "_lit.png")).convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (110, 110, 110, 255))
    bg.alpha_composite(rgba)
    img = bg.convert("RGB")
    over = np.asarray(img).astype(np.float32).copy()
    legend = []
    for p in PROMPTS[c["crop"]]:
        inst = sorted(segment_prompt(img, p, CONFIG), key=lambda r: -r.score)
        kept = [r for r in inst if r.score >= MIN_SCORE]
        for k, r in enumerate(kept):
            Image.fromarray(r.mask).convert("1").save(os.path.join(out, f"{c['name']}__{p.replace(' ', '_')}__{k}__{r.score:.2f}.png"))
        summary[f"{c['name']}|{p}"] = [round(r.score, 2) for r in inst[:4]]
        if kept:
            colr = rng.integers(60, 255, 3)
            m = np.zeros(kept[0].mask.shape, bool)
            for r in kept:
                m |= r.mask
            over[m] = over[m] * 0.4 + colr * 0.6
            legend.append((p, tuple(int(x) for x in colr), [round(r.score, 2) for r in kept]))
        print(f"{c['name']:13s} {p:16s} " + " ".join(f"{r.score:.2f}" for r in inst[:5]), flush=True)
    ov = Image.fromarray(over.astype(np.uint8))
    d = ImageDraw.Draw(ov)
    for i, (p, colr, sc) in enumerate(legend):
        d.rectangle((6, 6 + 18 * i, 20, 20 + 18 * i), fill=colr)
        d.text((26, 6 + 18 * i), f"{p} {sc}", fill=(255, 255, 255))
    ov.save(os.path.join(out, c["name"] + f"_overlay{TAG}.png"))
json.dump(summary, open(os.path.join(out, f"scores{TAG}.json"), "w"), indent=1)
print("SAM_OK", flush=True)
