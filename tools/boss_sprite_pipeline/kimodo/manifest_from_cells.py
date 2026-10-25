"""Build the cell -> prompt/params manifest straight from cells.json.

    manifest_from_cells.py <cells.json> <out.json>

cell_manifest.py kept its own copy of the prompt tables, which is exactly how the plan and the
run drifted apart the first time. cells.json is what the driver actually generated from, so the
labels on the reel come from that file and cannot disagree with it. Cells generated before
cells.json existed (the runall.sh block) are merged in from cell_manifest.py's output if it is
passed as a third argument.
"""
import json
import os
import sys

cells = json.load(open(sys.argv[1]))
out = {}
if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
    out.update(json.load(open(sys.argv[3])))

for c in cells:
    bits = ["dur %s" % c["duration"]]
    if c.get("constraints"):
        bits.append("cons %s" % os.path.basename(c["constraints"]))
    else:
        bits.append("cons none")
    ct = c.get("cfg_type", "separated")
    bits.append("cfg %s %s" % (ct, c.get("cfg_weight", [3.0, 2.0]) if ct != "nocfg" else ""))
    if c.get("steps", 100) != 100:
        bits.append("steps %d" % c["steps"])
    if c.get("transition", 5) != 5:
        bits.append("trans %d" % c["transition"])
    if c.get("no_post"):
        bits.append("no_post")
    if c.get("tpose"):
        bits.append("tpose")
    nch = len([t for t in c["prompt"].split(".") if t.strip()])
    bits.append("%d chunk%s" % (nch, "" if nch == 1 else "s"))
    out[c["name"]] = {"prompt": c["prompt"], "params": "  ".join(bits)}

json.dump(out, open(sys.argv[2], "w"), indent=1)
print("manifest", len(out), "cells ->", sys.argv[2])
