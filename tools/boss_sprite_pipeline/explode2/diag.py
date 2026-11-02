"""One page with every setting and number of an outfit's run: <work>/DIAGNOSTICS.md.

    python diag.py <work>        e.g. generated\\bosses\\barb\\explode2\\fullplate

Collects what each step leaves in <work>:
  diag_*.json            written by the steps (outfit_skeleton.py, explode_visibility.py --json, ...)
  paint/                 repaint.py's work dir: cost per painting (gen/*/attempt_*/check.json) and
                         the patch report (result/patches/patches.json)
Re-run it after any step; it rewrites the page from scratch.
"""
import glob
import json
import os
import sys

WORK = os.path.abspath(sys.argv[1])
out = [f"# Diagnostics - {os.path.basename(WORK)}", "", f"`{WORK}`", ""]


def flat(d, pre=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, f"{pre}{k}.")
        else:
            yield f"{pre}{k}", v


for path in sorted(glob.glob(os.path.join(WORK, "diag_*.json"))):
    d = json.load(open(path, encoding="utf-8"))
    out += [f"## {d.get('step', os.path.basename(path))}", ""]
    for k in ("base", "outfit", "glb", "out", "pose"):
        if k in d:
            out.append(f"- {k}: `{d[k]}`")
    for sect in ("settings", "results"):
        if d.get(sect):
            out += ["", f"| {sect} | value |", "|---|---|"]
            out += [f"| {k} | {v} |" for k, v in flat(d[sect])]
    out.append("")

paint = os.path.join(WORK, "paint")
if os.path.isdir(paint):
    rows, total = [], 0.0
    for chk in sorted(glob.glob(os.path.join(paint, "gen", "*", "attempt_*", "check.json"))):
        c = json.load(open(chk))
        u = c.get("usage") or {}
        i, o = u.get("input_tokens_details", {}), u.get("output_tokens_details", {})
        usd = (i.get("text_tokens", 0) * 5 + i.get("image_tokens", 0) * 8 + o.get("image_tokens", 0) * 30) / 1e6
        total += usd
        view, att = chk.split(os.sep)[-3:-1]
        rows.append(f"| {view} | {att} | {c.get('iou', 0):.3f} | {o.get('image_tokens', 0)} | ${usd:.2f} | {c.get('seconds', 0):.0f} s |")
    out += ["## 1 paint - generations (gpt-image-2: $5 text in, $8 image in, $30 image out per 1M tokens)", "",
            "| view | attempt | silhouette IoU | output tokens | cost | time |", "|---|---|---|---|---|---|"]
    out += rows + [f"| **total** | {len(rows)} | | | **${total:.2f}** | |", ""]
    pj = os.path.join(paint, "result", "patches", "patches.json")
    if os.path.isfile(pj):
        p = json.load(open(pj))
        out += ["## 1 paint - projection", ""]
        out += [f"- {k}: {v}" for k, v in p.items() if not isinstance(v, (dict, list))]
        for k, v in p.items():
            if isinstance(v, list):
                out.append(f"- {k}: {', '.join(map(str, v))}")
        for k, v in p.items():
            if isinstance(v, dict):
                out += ["", f"| {k} | value |", "|---|---|"]
                out += [f"| {a} | {b} |" for a, b in v.items()]
        out.append("")

open(os.path.join(WORK, "DIAGNOSTICS.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print("DIAG_OK", os.path.join(WORK, "DIAGNOSTICS.md"))
