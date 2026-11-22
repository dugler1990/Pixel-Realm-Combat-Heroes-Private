"""Bake many clips on a pod: pack code + job, set up bpy once, run pod_side.py in parallel, pull results.

The bake is CPU work (Blender's Python + numpy), not GPU: a CPU pod with many cores is the right box.
Measured here 2026-11-21: ~7 s per clip on this 4-core laptop (25 clips onto anun1).

Remote layout: /workspace/rb/{venv, repo, job, out, logs}. The venv (Python 3.11, bpy 4.5, numpy 1.26.4,
the same as the local .venv-bpy) survives between runs on the same pod.
"""
from __future__ import annotations

import io
import json
import shlex
import tarfile
import time
from pathlib import Path

from .. import paths, proc
from ..map import character as C

R = "/workspace/rb"
SETUP = f"""set -e
mkdir -p {R}/logs
if ! {R}/venv/bin/python -c "import bpy, numpy" 2>/dev/null; then
  (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libxrender1 libxi6 libxkbcommon0 \\
     libsm6 libgl1 libegl1 libxxf86vm1 libxfixes3 libxrandr2 >/dev/null) || echo "apt skipped"
  python3 -m pip install -q uv
  python3 -m uv venv --python 3.11 {R}/venv
  python3 -m uv pip install --python {R}/venv/bin/python "bpy==4.5.*" "numpy==1.26.4"
fi
{R}/venv/bin/python -c "import bpy; print('BPY_OK', bpy.app.version_string)"
"""
CODE = ["tools/boss_sprite_pipeline/__init__.py", "tools/boss_sprite_pipeline/retarget_bvh.py",
        "tools/boss_sprite_pipeline/viewer/export_split.py"]


def pack_code() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in CODE:
            tar.add(paths.REPO / rel, arcname=rel)
        for f in (paths.PIPE / "rigging").rglob("*.py"):
            tar.add(f, arcname=f.relative_to(paths.REPO).as_posix())
    return buf.getvalue()


def pack_job(rig_glb: str, roles: dict, map_block: dict, bvhs: list[Path]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(rig_glb, arcname="rig.glb")
        for name, obj in (("roles.json", roles), ("map.json", map_block)):
            data = json.dumps(obj).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for b in bvhs:
            tar.add(b, arcname=f"bvh/{b.name}")
    return buf.getvalue()


class PodError(RuntimeError):
    pass


def _call(fn, *a, **k):
    """gpu_box.pod exits the process on an ssh failure; inside a page job that must be an exception."""
    try:
        return fn(*a, **k)
    except SystemExit as e:
        raise PodError(str(e)) from None


def _follow(pod, log: str, ok: str, bad: tuple, lines: list, poll: float = 10.0, kill: str = "") -> str:
    seen = 0
    while True:
        if proc.stopped():
            if kill:
                _call(pod.ssh, kill, check=False)
            proc.check()
        text = _call(pod.ssh, f"cat {log} 2>/dev/null || true", check=False)
        new = text.splitlines()[seen:]
        seen += len(new)
        for line in new:
            lines.append("pod | " + line)
        del lines[:-400]
        if ok in text:
            return text
        hit = [b for b in bad if b in text] + (["the run ended"] if "RUN_EXIT" in text else [])
        if hit:
            raise PodError(f"{log}: {hit}")
        time.sleep(poll)


def _put_bytes(pod, data: bytes, remote: str, tmp: Path) -> None:
    tmp.write_bytes(data)
    _call(pod.put, tmp, remote)


def run(pod, cid: str, n: int, rec: dict, bvhs: list[Path], source: str, parallel: int, need_base: bool,
        work: Path, lines: list) -> Path:
    """Returns the local folder holding part_<i>/run.json and part_<i>/view/clips/*.glb (+ part_0/view/base.glb)."""
    work.mkdir(parents=True, exist_ok=True)
    lines.append(f"pod {pod.host}:{pod.port}: setting up bpy (first time on a pod: several minutes)")
    _call(pod.ssh, f"mkdir -p {R}/logs")
    _call(pod.ssh, f"cat > {R}/setup.sh", stdin=SETUP.encode())
    _call(pod.run_detached, f"bash {R}/setup.sh", f"{R}/logs/setup.log")
    _follow(pod, f"{R}/logs/setup.log", "BPY_OK", (), lines)
    lines.append(f"uploading code and {len(bvhs)} clips + rig")
    _put_bytes(pod, pack_code(), f"{R}/code.tgz", work / "code.tgz")
    char = C.load(cid)
    _put_bytes(pod, pack_job(rec["glb_path"], rec["roles"], char["map"], bvhs), f"{R}/job.tgz", work / "job.tgz")
    _call(pod.ssh, f"rm -rf {R}/repo {R}/job {R}/out && mkdir -p {R}/repo {R}/job {R}/out && "
                   f"tar xzf {R}/code.tgz -C {R}/repo && tar xzf {R}/job.tgz -C {R}/job")
    if parallel <= 0:
        info = _call(pod.ssh, "nproc; free -g | awk '/Mem:/{print $7}'", check=False).split()
        cores, mem = int(info[0]), int(info[1]) if len(info) > 1 else 8
        parallel = max(1, min(cores // 2, mem // 2, len(bvhs)))
    lines.append(f"baking {len(bvhs)} clips in {parallel} parallel Blender processes")
    side = f"{R}/repo/tools/boss_sprite_pipeline/rigging/pod/pod_side.py"
    cmd = " ".join(shlex.quote(x) for x in ("python3", side, f"{R}/job", f"{R}/out", f"{R}/venv/bin/python",
                                             str(parallel), cid, source, "1" if need_base else "0"))
    _call(pod.run_detached, cmd, f"{R}/logs/bake.log")
    _follow(pod, f"{R}/logs/bake.log", "POD_BAKE_DONE", ("POD_BAKE_FAILED",), lines,
            kill="pkill -f retarget_bvh; pkill -f export_split; pkill -f pod_side")
    _call(pod.ssh, f"cd {R}/out && tar czf {R}/result.tgz part_*/run.json part_*/view")
    _call(pod.get, f"{R}/result.tgz", work)
    with tarfile.open(work / "result.tgz") as tar:
        tar.extractall(work / "result", filter="data")
    return work / "result"
