"""One Kimodo cell at a time, with the model loaded once.

    python serve_one.py [--model Kimodo-SOMA-RP-v1] [--out /workspace/runs]
    python serve_one.py --once cell.json

Stdin, when --once is absent, is one JSON cell per line. The process stays up.
The default model is Kimodo-SOMA-RP-v1. driver.py's own default is SEED-v1.1, a different
training set, and the graded batches were not made on it.

Export uses skeleton.somaskel77. Generation uses the 30-joint skeleton. Mixing them raises
einsum size 77 versus size 30 after the motion has already been generated.
"""
import argparse
import json
import os
import sys
import traceback

import torch
from kimodo import load_model
from kimodo.constraints import load_constraints_lst
from kimodo.exports.bvh import save_motion_bvh
from kimodo.skeleton import SOMASkeleton30, global_rots_to_local_rots
from kimodo.tools import seed_everything


def texts_and_frames(model, prompt, duration):
    texts = [t.strip() + "." for t in prompt.split(".") if t.strip()]
    if " " in str(duration).strip():
        ds = [float(x) for x in str(duration).split()]
        if len(ds) != len(texts):
            raise ValueError("%d durations vs %d sentences" % (len(ds), len(texts)))
    else:
        ds = [float(duration)] * len(texts)
    return texts, [int(d * model.fps) for d in ds]


def generate(model, bskel, out_root, cell, cons_cache, dev):
    name = cell["name"]
    if any(c in name for c in ". /\\"):
        raise ValueError("cell name has a dot or a slash: %r" % name)
    texts, nframes = texts_and_frames(model, cell["prompt"], cell["duration"])
    seed_everything(int(cell.get("seed", 12345)))
    ct = cell.get("cfg_type", "separated")
    kw = {}
    if ct != "nocfg":
        kw["cfg_type"] = ct
        w = cell.get("cfg_weight", [3.0, 2.0])
        kw["cfg_weight"] = float(w[0]) if ct == "regular" and isinstance(w, list) else w
    else:
        kw["cfg_type"] = "nocfg"
    path = cell.get("constraints") or ""
    if path and path not in cons_cache:
        cons_cache[path] = load_constraints_lst(path, model.skeleton)
    out = model(
        texts, nframes,
        constraint_lst=cons_cache.get(path, []),
        num_denoising_steps=int(cell.get("steps", 100)),
        num_samples=int(cell.get("samples", 1)),
        multi_prompt=True,
        num_transition_frames=int(cell.get("transition", 5)),
        post_processing=not cell.get("no_post", False),
        return_numpy=True,
        **kw,
    )
    dest = os.path.join(out_root, name)
    os.makedirs(dest, exist_ok=True)
    n = int(out["posed_joints"].shape[0])
    for s in range(n):
        jp = torch.from_numpy(out["posed_joints"][s]).to(dev)
        jr = torch.from_numpy(out["global_rot_mats"][s]).to(dev)
        save_motion_bvh(os.path.join(dest, "%s_%02d.bvh" % (name, s)),
                        global_rots_to_local_rots(jr, bskel),
                        jp[:, bskel.root_idx, :],
                        skeleton=bskel, fps=model.fps,
                        standard_tpose=bool(cell.get("tpose", False)))
    print("CELL_DONE %s %d" % (name, n), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kimodo, one cell, model stays loaded")
    ap.add_argument("--model", default="Kimodo-SOMA-RP-v1")
    ap.add_argument("--out", default=os.environ.get("KIMODO_OUT", "/workspace/runs"))
    ap.add_argument("--once", help="a cell json path; generate it and exit")
    args = ap.parse_args(argv)
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = load_model(args.model, device=dev)
    mskel = model.skeleton
    bskel = mskel.somaskel77.to(dev) if isinstance(mskel, SOMASkeleton30) else mskel
    print("loaded %s  gen=%s export=%s" % (args.model, mskel.name, bskel.name), flush=True)
    cache = {}
    if args.once:
        cell = json.load(open(args.once, encoding="utf-8"))
        try:
            generate(model, bskel, args.out, cell, cache, dev)
        except Exception:
            print("CELL_FAIL %s" % cell.get("name"), flush=True)
            traceback.print_exc()
            return 1
        return 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            generate(model, bskel, args.out, json.loads(line), cache, dev)
        except Exception:
            print("CELL_FAIL", flush=True)
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
