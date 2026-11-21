"""Runs ON the pod (or locally, for a test): bake many clips in parallel Blender processes.

    python pod_side.py <job_dir> <out_dir> <bpy_python> <parallel> <pair_id> <source> <need_base 0|1>

<job_dir>: rig.glb, roles.json (canonical), map.json (the character's map block), bvh/*.bvh.
Splits the clips round-robin into <parallel> parts; each part is one retarget_bvh.py run (SKIP_GLB)
and one export_split.py run. Part 0 also writes base.glb when need_base is 1. Stdlib only.
Writes <out_dir>/part_<i>/run.json and <out_dir>/part_<i>/view/clips/*.glb; prints POD_BAKE_DONE last.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.abspath(os.path.join(HERE, "..", ".."))


def main(argv):
    job, out, py, parallel, pair_id, source, need_base = argv
    parallel, need_base = max(1, int(parallel)), need_base == "1"
    bvhs = sorted(f for f in os.listdir(os.path.join(job, "bvh")) if f.endswith(".bvh"))
    parts = [bvhs[i::parallel] for i in range(parallel)]
    parts = [p for p in parts if p]
    print(f"POD_BAKE {len(bvhs)} clips in {len(parts)} parallel parts", flush=True)
    procs = []
    t0 = time.time()
    for i, files in enumerate(parts):
        d = os.path.join(out, f"part_{i}")
        stage = os.path.join(d, "bvh")
        os.makedirs(stage, exist_ok=True)
        for f in files:
            shutil.copy(os.path.join(job, "bvh", f), stage)
        bake = [py, os.path.join(PIPE, "retarget_bvh.py"), "--rig", os.path.join(job, "rig.glb"),
                "--roles", os.path.join(job, "roles.json"), "--map", os.path.join(job, "map.json"),
                "--source", source, "--pair-id", pair_id, stage, d]
        split = [py, os.path.join(PIPE, "viewer", "export_split.py"), os.path.join(d, "animated.blend"),
                 os.path.join(d, "view")] + ([] if (i == 0 and need_base) else ["--clips-only"])
        log = open(os.path.join(d, "log.txt"), "w")
        env = dict(os.environ, SKIP_GLB="1")
        cmd = " && ".join(subprocess.list2cmdline(c) if os.name == "nt" else " ".join(_q(x) for x in c)
                          for c in (bake, split))
        procs.append((i, len(files), subprocess.Popen(cmd, shell=True, stdout=log, stderr=subprocess.STDOUT, env=env),
                      log))
    bad = 0
    for i, n, p, log in procs:
        rc = p.wait()
        log.close()
        tail = open(os.path.join(out, f"part_{i}", "log.txt"), errors="replace").read().splitlines()
        checks = [l for l in tail if "POSE_CHECK" in l]
        print(f"part {i}: {n} clips rc {rc} ({len(checks)} pose checks)", flush=True)
        if rc != 0:
            bad += 1
            print("\n".join(tail[-15:]), flush=True)
    print(f"POD_BAKE_TIME {time.time() - t0:.0f} s", flush=True)
    print("POD_BAKE_DONE" if not bad else f"POD_BAKE_FAILED {bad} parts", flush=True)


def _q(s):
    import shlex
    return shlex.quote(str(s))


if __name__ == "__main__":
    main(sys.argv[1:])
