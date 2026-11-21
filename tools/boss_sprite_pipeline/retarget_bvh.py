"""Bake BVH clips onto a character's rig version. Runs under .venv-bpy. A thin driver:
blender/pose_io reads matrices, rigging.map computes (match, bind, transfer, pose_check), pose_io
writes the keys. Every setting comes from the character file; nothing has a default here.

    retarget_bvh.py --character <id> [--version N] [--source soma] <bvh_dir> <out_dir>
    retarget_bvh.py --rig <rig.glb> --roles <canonical roles.json> --map <map.json>
                    [--source soma] [--pair-id <character id>] <bvh_dir> <out_dir>

The second form is for scratch runs and locks: roles are canonical (rigging.roles), map.json is the
character file's "map" block.

Facts the method rests on (measured, see NOTES_retarget_kimodo.md):
  * SOMA legs are Leg -> Shin -> Foot (no UpLeg); the labeller in rigging/sources/soma.py has them.
  * The BVH rest skeleton lies along +X, so the transfer is a world-space delta against a reference
    pose (frame 1 by default), never an absolute copy.

Writes <out_dir>/animated.blend (+ animated.glb unless SKIP_GLB=1) with one action per clip, and
<out_dir>/run.json: rig version, resolved settings with sources, pairs, pose check, proportions.
Logs one line per clip: POSE_CHECK <clip> ok|FAIL worst <src>><bone> <deg> deg at frame <f>.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.boss_sprite_pipeline.rigging import paths, sources  # noqa: E402
from tools.boss_sprite_pipeline.rigging.map import character as C  # noqa: E402
from tools.boss_sprite_pipeline.rigging.map.match import match  # noqa: E402
from tools.boss_sprite_pipeline.rigging.map.transfer import transfer  # noqa: E402
from tools.boss_sprite_pipeline.rigging.rig import glb as G  # noqa: E402
from tools.boss_sprite_pipeline.rigging.rig import version as V  # noqa: E402


def log(*a):
    print("[retarget]", *a, flush=True)


def _opt(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return None


def _depth(parent, b):
    d = 0
    while parent.get(b):
        b, d = parent[b], d + 1
    return d


def main(argv):
    argv = list(argv)
    cid = _opt(argv, "--character")
    vnum = _opt(argv, "--version")
    source = _opt(argv, "--source") or "soma"
    rig_glb, roles_path, map_path = _opt(argv, "--rig"), _opt(argv, "--roles"), _opt(argv, "--map")
    pair_id = _opt(argv, "--pair-id") or ""
    if len(argv) != 2:
        raise SystemExit(__doc__)
    bvh_dir, out_dir = (os.path.abspath(x) for x in argv)
    os.makedirs(out_dir, exist_ok=True)

    if cid:
        char = C.load(cid)
        n = int(vnum) if vnum else int(char["rig"])
        rec = V.load(cid, n)
        rig_glb, roles = rec["glb_path"], rec["roles"]
        rig_id = {"character": cid, "version": n, "bone_hash": rec["bone_hash"], "roles_hash": rec["roles_hash"]}
    else:
        if not (rig_glb and roles_path and map_path):
            raise SystemExit("--character, or all of --rig --roles --map")
        roles = json.load(open(roles_path))
        char = {"id": pair_id, "map": json.load(open(map_path))}
        bones = G.skeleton(rig_glb)
        rig_id = {"character": pair_id or None, "version": None, "glb": rig_glb,
                  "bone_hash": G.bone_hash(bones), "roles_hash": V.roles_hash(roles)}
    settings = C.resolve(char, source)
    vals = {k: v["value"] for k, v in settings.items()}
    src_mod = sources.get(source)

    import bpy  # noqa: F401 - only after argument errors, so --help works without Blender
    from tools.boss_sprite_pipeline.rigging.blender import pose_io

    idle_rots = None
    if vals["reference_pose"] not in ("frame1", "tpose"):
        import numpy as np
        data = json.load(open(vals["reference_pose"]))
        idle_rots = {k: np.array(v)[:3, :3] for k, v in data["rots"].items()}

    tgt, mesh, rig = pose_io.load_target(rig_glb)
    log(f"rig {os.path.basename(rig_glb)} height {rig['height']:.3f}, source {source}")

    results = {}
    pairs_report = None
    for bvh in sorted(glob.glob(os.path.join(bvh_dir, "*.bvh"))):
        clip = pose_io.read_clip(bvh)
        src_roles = sources.label(clip["names"], source)
        m = match(src_roles, roles, rig["order"], static=src_mod.STATIC)
        use = [(p["role"], p["source"], p["target"]) for p in m["paired"]
               if p["target"] in rig["rest_arm"] and p["source"] in clip["world"][clip["frames"][0]]]
        use.sort(key=lambda u: _depth(rig["parent"], u[2]))
        vals["flags"] = C.bind_flags(settings, [u[0] for u in use])
        res = transfer(clip, rig, roles, use, vals, idle_rots)
        for line in res["info"]:
            log(" ", clip["name"], line)
        pose_io.write_action(tgt, clip["name"], res)
        pc = res["pose_check"]
        w = pc["worst"]
        if w:
            log("POSE_CHECK %s %s worst %s %.1f deg at frame %d (%d segments)%s"
                % (clip["name"], "FAIL" if pc["fail"] else "ok", w["bone"], w["deg"], w["frame"],
                   res["segments"], (" over %d: %s" % (pc["limit"], ", ".join(pc["fail"]))) if pc["fail"] else ""))
        results[clip["name"]] = {"frames": len(res["frames"]), "pose_check": pc,
                                 "proportions": res["proportions"]}
        pairs_report = {"paired": [list(u) for u in use], "missing": m["missing"],
                        "missing_required": m["missing_required"], "static": m["static"]}
        log("retargeted", clip["name"], len(res["frames"]), "frames")

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             cwd=HERE).stdout.strip()
    except Exception:  # noqa: BLE001
        sha = "?"
    run = {
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "code": sha,
        "rig": rig_id,
        "source": source,
        "bvh_dir": bvh_dir,
        "settings": {k: v for k, v in settings.items()},
        "bind_flags": vals.get("flags"),
        "pairs": pairs_report,
        "bones_driven": len(pairs_report["paired"]) if pairs_report else 0,
        "clips": results,
    }
    with open(os.path.join(out_dir, "run.json"), "w") as f:
        json.dump(run, f, indent=1)
    pose_io.finish(tgt, mesh, out_dir, skip_glb=bool(os.environ.get("SKIP_GLB")), log=log)
    log("DONE")


if __name__ == "__main__":
    main(sys.argv[1:])
