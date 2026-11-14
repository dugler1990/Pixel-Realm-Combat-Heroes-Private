"""Pod steps of the outfit pipeline: copy the inputs up, run, copy the results back.

    python tools/boss_sprite_pipeline/gpu_box/pod.py <step> push|run|pull|token --host <ip> --port <port>
        --work <outfit run folder> [--key <ppp>] [--models a,b]
    python tools/boss_sprite_pipeline/gpu_box/pod.py address "<the ssh line from RunPod's Connect tab>"
    python tools/boss_sprite_pipeline/gpu_box/pod.py status --host <ip> --port <port>

<step>: trellis | sam3 | holopart. --host / --port default to POD_HOST / POD_PORT; --key to POD_KEY, else the
key `ppp` in the main repo folder. You start and stop the pod; this never does. outfit.py says "stop the pod"
after the outfit's last pod step.
address  asks the ssh.runpod.io proxy (TTY, commands on stdin) for the pod's direct address; prints POD <ip> <port>.
status   one line, POD_STATUS {json}: GPU %, memory, what runs (TRELLIS / SAM3 / HoloPart / pip), what is installed.

token   the HF token from HF_TOKEN (set it from the clipboard, never typed or printed) into the pod's
        /workspace/.cache/huggingface/token, through ssh's stdin; without HF_TOKEN, a token already on the pod
        does. TRELLIS needs it. Prints TOKEN_OK.
trellis push: gpu_box's TRELLIS files + the accepted views (<work>/gate/front.png, back.png, side_*.png) -> /workspace/in/
        run:  trellis_outfit.sh <models> (install once, then each model not built yet) until TRELLIS_OK
        pull: /workspace/out/<model>_from_front.glb -> <work>/trellis/
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
MODELS = ("front_only", "front_back", "front_back_sides", "eight_views")
VIEWS = ("front", "back", "side_left", "side_right", "side_front_left", "side_front_right", "side_back_left",
         "side_back_right")


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
        # Windows checkouts have CRLF; bash on the pod reads "\r" as part of each command.
        self.ssh(f"find {shlex.quote(remote)} -name '*.sh' -exec sed -i 's/\\r$//' {{}} +")

    def get(self, remote: str, local: Path) -> None:
        print(f"  pull {remote} -> {local}", flush=True)
        local.mkdir(parents=True, exist_ok=True)
        subprocess.run(["scp", *self.opts, "-P", self.port, "-r", f"root@{self.host}:{remote}", str(local)],
                       check=True)

    def run_detached(self, cmd: str, log: str) -> None:
        cmd = f"{cmd}; echo RUN_EXIT $?"
        self.ssh(f"mkdir -p /workspace/logs; nohup bash -c {shlex.quote(cmd)} > {log} 2>&1 < /dev/null &")

    def wait_for(self, log: str, ok: str, bad: tuple[str, ...] = ()) -> str:
        """Poll `log` until a line holds `ok` (returns the log), one of `bad`, or the run ended without `ok`
        (RUN_EXIT, written by run_detached): those exit."""
        bad = (*bad, "RUN_EXIT")
        seen = 0
        while True:
            text = self.ssh(f"cat {log} 2>/dev/null || true", check=False)
            lines = text.splitlines()
            for line in lines[seen:]:
                print("  | " + line, flush=True)
            seen = len(lines)
            if ok in text:
                return text
            if any(b in text for b in bad):
                sys.exit(f"FAILED: {log} says {[b for b in bad if b in text]}")
            time.sleep(POLL)


def step_trellis(pod: Pod, action: str, work: Path, models: list[str]) -> None:
    if action == "push":
        pod.ssh("mkdir -p /workspace/gpu_box /workspace/in /workspace/out /workspace/logs")
        for f in TRELLIS_FILES:
            pod.put(HERE / f, f"/workspace/gpu_box/{f}")
        for v in VIEWS:
            src = work / "gate" / f"{v}.png"
            if src.is_file():
                pod.put(src, f"/workspace/in/{v}.png")
            elif v == "front":
                sys.exit(f"no accepted front: {src}")
    elif action == "run":
        pod.run_detached("bash /workspace/gpu_box/trellis_outfit.sh " + " ".join(models),
                         "/workspace/logs/trellis_outfit.log")
        pod.wait_for("/workspace/logs/trellis_outfit.log", "TRELLIS_OK", ("TRELLIS_FAILED",))
    elif action == "pull":
        for n in models:
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
        if pod.ssh("test -s /workspace/.cache/huggingface/token && echo yes || true", check=False).strip() == "yes":
            print("TOKEN_OK already on the pod", flush=True)
            return
        sys.exit("HF_TOKEN is not set and the pod has none (PowerShell: $env:HF_TOKEN = (Get-Clipboard).Trim())")
    pod.ssh("mkdir -p /workspace/.cache/huggingface && tr -cd 'A-Za-z0-9_' > /workspace/.cache/huggingface/token",
            stdin=token.encode())
    print("TOKEN_OK written on the pod", flush=True)


def address(line: str, key: Path) -> tuple[str, str]:
    """The pod's direct address, asked through the proxy line RunPod shows (user@ssh.runpod.io). The proxy ignores
    a command argument and needs a TTY, so the command goes in on stdin (explode/PROCESS_explode.md)."""
    user = next((t for t in line.split() if t.endswith("@ssh.runpod.io")), None)
    if not user:
        sys.exit("no <user>@ssh.runpod.io in that line")
    cmd = 'echo "POD_ADDR=$RUNPOD_PUBLIC_IP:$RUNPOD_TCP_PORT_22"; exit\n'
    r = subprocess.run(["ssh", "-tt", "-i", str(key), "-o", "StrictHostKeyChecking=accept-new", "-o",
                        "ConnectTimeout=25", user], input=cmd.encode(), capture_output=True, timeout=90)
    out = r.stdout.decode("utf-8", "replace").replace("\r", "\n")
    hits = [h for h in out.split() if h.startswith("POD_ADDR=") and "$" not in h and h != "POD_ADDR=:"]
    if not hits:
        sys.exit("the pod gave no public IP / TCP 22 port (deploy it with Public IP and TCP port 22 exposed)")
    host, port = hits[-1].split("=", 1)[1].split(":")
    return host, port


# GPU line; RUN_<name> for each job that runs (the [x]yz pattern keeps pgrep from matching this shell itself);
# HAVE_<name> for what is installed.
STATUS_CMD = (
    "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits | head -1; "
    "pgrep -f '[t]rellis2_mv_run' >/dev/null && echo RUN_trellis; "
    "pgrep -f '[t]rellis2_setup' >/dev/null && echo RUN_trellis_install; "
    "pgrep -f '[e]xplode_sam' >/dev/null && echo RUN_sam3; "
    "pgrep -f '[i]nference_holopart' >/dev/null && echo RUN_holopart; "
    "pgrep -f '[p]ip install' >/dev/null && echo RUN_pip; "
    "grep -q INSTALL_OK /workspace/setup.log 2>/dev/null && echo HAVE_trellis; "
    "test -x /workspace/sv/bin/python && echo HAVE_sam3; test -d /workspace/hp && echo HAVE_holopart; "
    "test -s /workspace/.cache/huggingface/token && echo HAVE_token; true")


def status(pod: Pod) -> dict:
    import json
    lines = [l.strip() for l in pod.ssh(STATUS_CMD, check=False).splitlines()]
    if not lines:
        d = {"error": f"no answer from {pod.host}:{pod.port} (stopped, or a new address?)"}
        print("POD_STATUS " + json.dumps(d), flush=True)
        return d
    gpu = [x.strip() for x in lines[0].split(",")] if lines[0].count(",") == 2 else []
    d = {"gpu_pct": int(gpu[0]) if gpu else None, "mem_mb": int(gpu[1]) if gpu else None,
         "mem_total_mb": int(gpu[2]) if gpu else None,
         "running": [l[4:] for l in lines if l.startswith("RUN_")],
         "installed": [l[5:] for l in lines if l.startswith("HAVE_")]}
    print("POD_STATUS " + json.dumps(d), flush=True)
    return d


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    key = Path(os.environ.get("POD_KEY", MAIN_KEY))
    if argv[:1] == ["address"]:
        host, port = address(" ".join(argv[1:]), key)
        print(f"POD {host} {port}")
        return
    if argv[:1] == ["status"]:
        sp = argparse.ArgumentParser()
        sp.add_argument("status")
        sp.add_argument("--host", default=os.environ.get("POD_HOST"))
        sp.add_argument("--port", default=os.environ.get("POD_PORT"))
        b = sp.parse_args(argv)
        status(Pod(b.host, b.port, key))
        return
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("trellis", "sam3", "holopart"))
    ap.add_argument("action", choices=("push", "run", "pull", "token"))
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--host", default=os.environ.get("POD_HOST"))
    ap.add_argument("--port", default=os.environ.get("POD_PORT"))
    ap.add_argument("--key", type=Path, default=Path(os.environ.get("POD_KEY", MAIN_KEY)))
    ap.add_argument("--prompts", type=Path, help="sam3: the prompts file (crop -> prompts)")
    ap.add_argument("--models", default=",".join(MODELS), help="trellis: the models to build / pull, comma-separated")
    a = ap.parse_args(argv)
    if not a.host or not a.port:
        ap.error("give --host and --port (or POD_HOST / POD_PORT)")
    if not a.key.is_file():
        ap.error(f"no key at {a.key}")
    pod = Pod(a.host, a.port, a.key)
    if a.action == "token":
        send_token(pod)
    elif a.step == "trellis":
        models = [m for m in a.models.split(",") if m]
        if set(models) - set(MODELS):
            ap.error(f"unknown models {sorted(set(models) - set(MODELS))}; choose from {MODELS}")
        step_trellis(pod, a.action, a.work, models)
    elif a.step == "sam3":
        step_sam3(pod, a.action, a.work, a.prompts)
    else:
        step_holopart(pod, a.action, a.work)
    if a.action == "pull":
        print(f"PULL_OK {a.step}")


if __name__ == "__main__":
    main()
