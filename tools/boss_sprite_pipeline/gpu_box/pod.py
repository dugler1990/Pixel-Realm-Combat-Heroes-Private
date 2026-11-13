"""Pod steps of the outfit pipeline: copy the inputs up, run, copy the results back.

    python tools/boss_sprite_pipeline/gpu_box/pod.py <step> push|run|pull|token --host <ip> --port <port>
        --work <outfit run folder> [--key <ppp>]

<step>: trellis | sam3 | holopart. --host / --port default to POD_HOST / POD_PORT; --key to POD_KEY, else the
key `ppp` in the main repo folder. You start and stop the pod; this never does. `pull` ends by saying
"stop the pod" on its own line.

token   the HF token from HF_TOKEN (set it from the clipboard, never typed or printed) into the pod's
        /workspace/.cache/huggingface/token, through ssh's stdin. trellis and sam3 need it.
trellis push: gpu_box's TRELLIS files + <work>/gate/front.png [back.png] -> /workspace/in/
        run:  trellis_outfit.sh (install, both models) until TRELLIS_OK
        pull: /workspace/out/{front_only,front_back}_from_front.glb -> <work>/trellis/
sam3    push: the SAM3 snapshot (HF cache), sam3local src, explode_sam.py, sam3_pod.sh, the prompts, <work>/views
        run:  sam3_pod.sh until SAM_DONE; every sam_shard*.log must end in SAM_OK
        pull: /workspace/views/masks -> <work>/views/masks
holopart push: holopart_pod.sh, holopart_patch.py, <work>/cut/input_parts.glb
        run:  install (once) then run until HP_DONE
        pull: /workspace/holopart_out/* -> <work>/holopart/
Long runs are started detached (nohup) and watched by polling their log, so a dropped connection does not
stop them; `run` again re-attaches.
"""
from __future__ import annotations

import argparse
import glob
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOSS = HERE.parent
MAIN_KEY = Path(r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp")
TRELLIS_FILES = ["trellis2_setup.sh", "trellis2_patch.py", "trellis2_run.py", "trellis2_multiview.py",
                 "trellis2_mv_run.py", "trellis_outfit.sh"]
SAM3_SNAPSHOTS = Path.home() / ".cache" / "huggingface" / "hub" / "models--facebook--sam3" / "snapshots"
SAM3_SRC = Path(r"C:\Users\Douglas\sam3local\src")
POLL = 30


class Pod:
    def __init__(self, host: str, port: str, key: Path):
        self.host, self.port, self.key = host, str(port), key
        self.opts = ["-i", str(key), "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30"]

    def ssh(self, cmd: str, stdin: bytes | None = None, check: bool = True) -> str:
        r = subprocess.run(["ssh", *self.opts, "-p", self.port, f"root@{self.host}", cmd], input=stdin,
                           capture_output=True)
        out = r.stdout.decode("utf-8", "replace")
        if check and r.returncode:
            sys.exit(f"ssh failed ({r.returncode}): {cmd}\n{r.stderr.decode('utf-8', 'replace')[-2000:]}")
        return out

    def put(self, local: Path, remote: str) -> None:
        print(f"  push {local} -> {remote}", flush=True)
        args = ["scp", *self.opts, "-P", self.port] + (["-r"] if local.is_dir() else []) + [
            str(local), f"root@{self.host}:{remote}"]
        subprocess.run(args, check=True)

    def get(self, remote: str, local: Path) -> None:
        print(f"  pull {remote} -> {local}", flush=True)
        local.mkdir(parents=True, exist_ok=True)
        subprocess.run(["scp", *self.opts, "-P", self.port, "-r", f"root@{self.host}:{remote}", str(local)],
                       check=True)

    def run_detached(self, cmd: str, log: str) -> None:
        self.ssh(f"mkdir -p /workspace/logs; nohup bash -c {shlex.quote(cmd)} > {log} 2>&1 < /dev/null &")

    def wait_for(self, log: str, ok: str, bad: tuple[str, ...] = ()) -> str:
        """Poll `log` until a line holds `ok` (returns the log) or one of `bad` (exits)."""
        seen = 0
        while True:
            text = self.ssh(f"cat {log} 2>/dev/null || true", check=False)
            lines = text.splitlines()
            for line in lines[seen:]:
                print("  | " + line, flush=True)
            seen = len(lines)
            if any(b in text for b in bad):
                sys.exit(f"FAILED: {log} says {[b for b in bad if b in text]}")
            if ok in text:
                return text
            time.sleep(POLL)


def step_trellis(pod: Pod, action: str, work: Path) -> None:
    if action == "push":
        pod.ssh("mkdir -p /workspace/gpu_box /workspace/in /workspace/out /workspace/logs")
        for f in TRELLIS_FILES:
            pod.put(HERE / f, f"/workspace/gpu_box/{f}")
        for v in ("front", "back"):
            src = work / "gate" / f"{v}.png"
            if src.is_file():
                pod.put(src, f"/workspace/in/{v}.png")
            elif v == "front":
                sys.exit(f"no accepted front: {src}")
    elif action == "run":
        pod.run_detached("bash /workspace/gpu_box/trellis_outfit.sh", "/workspace/logs/trellis_outfit.log")
        pod.wait_for("/workspace/logs/trellis_outfit.log", "TRELLIS_OK", ("TRELLIS_FAILED",))
    elif action == "pull":
        for n in ("front_only", "front_back"):
            have = pod.ssh(f"test -s /workspace/out/{n}_from_front.glb && echo yes || true", check=False).strip()
            if have == "yes":
                pod.get(f"/workspace/out/{n}_from_front.glb", work / "trellis")


def step_sam3(pod: Pod, action: str, work: Path, prompts: Path | None) -> None:
    if action == "push":
        snaps = sorted(glob.glob(str(SAM3_SNAPSHOTS / "*")))
        if not snaps:
            sys.exit(f"no SAM3 snapshot under {SAM3_SNAPSHOTS} (gated on HF: download it once locally)")
        if not SAM3_SRC.is_dir():
            sys.exit(f"no sam3local source at {SAM3_SRC}")
        pod.ssh("rm -rf /workspace/views /workspace/sam_shard*.log; mkdir -p /workspace")
        if pod.ssh("test -d /workspace/sam3 && echo yes || true", check=False).strip() != "yes":
            pod.put(Path(snaps[-1]), "/workspace/sam3")
        if pod.ssh("test -d /workspace/sam3local_src && echo yes || true", check=False).strip() != "yes":
            pod.put(SAM3_SRC, "/workspace/sam3local_src")
        pod.put(BOSS / "explode" / "explode_sam.py", "/workspace/explode_sam.py")
        pod.put(BOSS / "explode" / "sam3_pod.sh", "/workspace/sam3_pod.sh")
        if prompts is not None:
            pod.put(prompts, "/workspace/prompts.json")
        pod.put(work / "views", "/workspace/views")
    elif action == "run":
        prompts = " /workspace/prompts.json" if pod.ssh("test -s /workspace/prompts.json && echo yes || true",
                                                        check=False).strip() == "yes" else ""
        pod.run_detached(f"bash /workspace/sam3_pod.sh /workspace/views{prompts}", "/workspace/logs/sam3.log")
        pod.wait_for("/workspace/logs/sam3.log", "SAM_DONE")
        ends = pod.ssh("for f in /workspace/sam_shard*.log; do tail -n 1 $f; done", check=False).split()
        if not ends or any(e != "SAM_OK" for e in ends):
            sys.exit(f"a SAM3 shard did not end in SAM_OK: {ends} (see /workspace/sam_shard*.log)")
        print("  every shard ended in SAM_OK", flush=True)
    elif action == "pull":
        pod.get("/workspace/views/masks", work / "views")


def step_holopart(pod: Pod, action: str, work: Path) -> None:
    if action == "push":
        pod.ssh("mkdir -p /workspace")
        for f in ("holopart_pod.sh", "holopart_patch.py"):
            pod.put(BOSS / "explode" / f, f"/workspace/{f}")
        pod.put(work / "cut" / "input_parts.glb", "/workspace/input_parts.glb")
    elif action == "run":
        if pod.ssh("test -d /workspace/hp && echo yes || true", check=False).strip() != "yes":
            pod.run_detached("bash /workspace/holopart_pod.sh install", "/workspace/logs/hp_install.log")
            pod.wait_for("/workspace/logs/hp_install.log", "HP_READY")
        pod.run_detached("rm -rf /workspace/holopart_out; mkdir -p /workspace/holopart_out; "
                         "bash /workspace/holopart_pod.sh run /workspace/input_parts.glb /workspace/holopart_out",
                         "/workspace/logs/hp_run.log")
        pod.wait_for("/workspace/logs/hp_run.log", "HP_DONE")
    elif action == "pull":
        out = work / "holopart"
        out.mkdir(parents=True, exist_ok=True)
        for f in pod.ssh("ls /workspace/holopart_out", check=False).split():
            pod.get(f"/workspace/holopart_out/{f}", out)


def send_token(pod: Pod) -> None:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        sys.exit("HF_TOKEN is not set (PowerShell: $env:HF_TOKEN = (Get-Clipboard).Trim())")
    pod.ssh("mkdir -p /workspace/.cache/huggingface && tr -cd 'A-Za-z0-9_' > /workspace/.cache/huggingface/token",
            stdin=token.encode())
    print("  token written on the pod", flush=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("trellis", "sam3", "holopart"))
    ap.add_argument("action", choices=("push", "run", "pull", "token"))
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--host", default=os.environ.get("POD_HOST"))
    ap.add_argument("--port", default=os.environ.get("POD_PORT"))
    ap.add_argument("--key", type=Path, default=Path(os.environ.get("POD_KEY", MAIN_KEY)))
    ap.add_argument("--prompts", type=Path, help="sam3: the prompts file (crop -> prompts)")
    a = ap.parse_args(argv)
    if not a.host or not a.port:
        ap.error("give --host and --port (or POD_HOST / POD_PORT)")
    if not a.key.is_file():
        ap.error(f"no key at {a.key}")
    pod = Pod(a.host, a.port, a.key)
    if a.action == "token":
        send_token(pod)
    elif a.step == "trellis":
        step_trellis(pod, a.action, a.work)
    elif a.step == "sam3":
        step_sam3(pod, a.action, a.work, a.prompts)
    else:
        step_holopart(pod, a.action, a.work)
    if a.action == "pull":
        print(f"PULL_OK {a.step}")
        print("stop the pod")


if __name__ == "__main__":
    main()
