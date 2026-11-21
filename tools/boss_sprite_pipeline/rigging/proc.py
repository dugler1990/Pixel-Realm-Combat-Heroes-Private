"""Subprocesses a job can stop. The page's job thread sets `current.job`; run() registers its process
there and streams output into the job's lines as it comes, so a stop kills the process tree at once.
"""
from __future__ import annotations

import os
import subprocess
import threading

current = threading.local()      # .job = the page job dict ({"lines", "cancel", "proc"}) or unset


class Stopped(RuntimeError):
    pass


def _job():
    return getattr(current, "job", None)


def stopped() -> bool:
    j = _job()
    return bool(j and j.get("cancel"))


def check():
    if stopped():
        raise Stopped("stopped")


def run(cmd, lines, env=None, cwd=None, keep=400) -> str:
    """Run, stream stdout+stderr into `lines`, raise on a non-zero exit or a stop. Returns the output."""
    check()
    merged = os.environ.copy()
    if env:
        merged.update(env)
    lines.append("$ " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=merged, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace")
    j = _job()
    if j is not None:
        j["proc"] = p
    out = []
    try:
        for line in p.stdout:
            line = line.rstrip("\n")
            out.append(line)
            lines.append(line)
            del lines[:-keep]
        p.wait()
    finally:
        if j is not None:
            j["proc"] = None
    check()
    if p.returncode != 0:
        raise RuntimeError(f"{os.path.basename(str(cmd[1]) if len(cmd) > 1 else str(cmd[0]))} exit {p.returncode}")
    return "\n".join(out)


def kill(job) -> None:
    """Stop a job: flag it and kill its running process tree."""
    job["cancel"] = True
    p = job.get("proc")
    if p is None or p.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()
