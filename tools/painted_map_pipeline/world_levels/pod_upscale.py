"""Send one level image to HYPIR on a pod the user already started.

The page is given RunPod's Connect SSH line. That pod already has its GPU.
This module parses the line, installs HYPIR-SD2 over SSH when it is missing,
runs one 2x pass, and writes the result next to the level. Tests pass a fake
remote, so nothing here dials a host unless a real remote is asked to.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

POD_ROOT = "/workspace/hypir"
WEIGHT_URL = "https://huggingface.co/lxq007/HYPIR/resolve/main/HYPIR_sd2.pth"
HYPIR_REPO = "https://github.com/XPixelGroup/HYPIR.git"
ICE_PROMPT = (
    "Richly detailed top-down painted pixel-art RPG ice ground. "
    "Sharp snow crust, cracked glacier, ice floes. Keep the layout."
)
LORA_MODULES = (
    "to_k,to_q,to_v,to_out.0,conv,conv1,conv2,conv_shortcut,conv_out,"
    "proj_in,proj_out,ff.net.2,ff.net.0.proj"
)
UPSCALE = 2

PROBE_SH = "echo CONNECTED\nnvidia-smi -L\n"
CHECK_SH = f"""if [ -x {POD_ROOT}/.venv/bin/python ] && [ -f {POD_ROOT}/weights/HYPIR_sd2.pth ]; then
  echo READY
else
  echo MISSING
fi
"""
INSTALL_SH = f"""set -euo pipefail
if [ -x {POD_ROOT}/.venv/bin/python ] && [ -f {POD_ROOT}/weights/HYPIR_sd2.pth ]; then
  echo READY
  exit 0
fi
if ! command -v git >/dev/null || ! command -v curl >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git curl
fi
mkdir -p {POD_ROOT}/weights
if [ ! -d {POD_ROOT}/.git ]; then
  git clone --depth 1 {HYPIR_REPO} {POD_ROOT}
fi
python3 -m venv {POD_ROOT}/.venv
{POD_ROOT}/.venv/bin/pip install -U pip
{POD_ROOT}/.venv/bin/pip install -r {POD_ROOT}/requirements.txt
{POD_ROOT}/.venv/bin/pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
if [ ! -f {POD_ROOT}/weights/HYPIR_sd2.pth ]; then
  curl -L --fail -o {POD_ROOT}/weights/HYPIR_sd2.pth {WEIGHT_URL}
fi
{POD_ROOT}/.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('stabilityai/stable-diffusion-2-1-base')"
echo READY
"""
RUN_SH = f"""set -euo pipefail
cd {POD_ROOT}
rm -rf job/out
mkdir -p job/in job/out
.venv/bin/python test.py \\
  --base_model_type sd2 \\
  --base_model_path stabilityai/stable-diffusion-2-1-base \\
  --model_t 200 \\
  --coeff_t 200 \\
  --lora_rank 256 \\
  --lora_modules '{LORA_MODULES}' \\
  --weight_path {POD_ROOT}/weights/HYPIR_sd2.pth \\
  --patch_size 512 \\
  --stride 256 \\
  --lq_dir {POD_ROOT}/job/in \\
  --scale_by factor \\
  --upscale {UPSCALE} \\
  --captioner fixed \\
  --fixed_caption '{ICE_PROMPT}' \\
  --output_dir {POD_ROOT}/job/out \\
  --seed 231 \\
  --device cuda
"""
REMOTE_IN = f"{POD_ROOT}/job/in/piece.png"
REMOTE_OUT = f"{POD_ROOT}/job/out/result/piece.png"


class PodError(RuntimeError):
    """The pod refused the SSH line, the install, or the HYPIR run."""


@dataclass(frozen=True)
class SshTarget:
    user: str
    host: str
    port: int
    key: Path


def parse_ssh_line(line: str) -> SshTarget:
    """RunPod's Connect line: ``ssh user@host -p PORT -i key``."""
    text = (line or "").strip()
    if not text:
        raise ValueError("paste the RunPod Connect SSH line")
    posix = os.name != "nt"
    try:
        parts = shlex.split(text, posix=posix)
    except ValueError as exc:
        raise ValueError(f"could not read the SSH line: {exc}") from exc
    if not parts or Path(parts[0]).name not in ("ssh", "ssh.exe"):
        raise ValueError("paste the Connect SSH line, starting with ssh")
    user_host = None
    port = None
    key = None
    index = 1
    while index < len(parts):
        token = parts[index]
        if token in ("-p", "-P") and index + 1 < len(parts):
            port = parts[index + 1]
            index += 2
            continue
        if token == "-i" and index + 1 < len(parts):
            key = parts[index + 1].strip('"')
            index += 2
            continue
        if token.startswith("-"):
            # -o Option=value and similar flags that take one argument.
            if token in ("-o", "-J", "-F", "-c", "-l", "-W") and index + 1 < len(parts):
                index += 2
                continue
            index += 1
            continue
        user_host = token
        index += 1
    if not user_host or "@" not in user_host:
        raise ValueError("the SSH line needs user@host")
    user, host = user_host.split("@", 1)
    if not user or not host:
        raise ValueError("the SSH line needs user@host")
    if port is None:
        raise ValueError("the SSH line needs -p and the port")
    try:
        port_n = int(port)
    except ValueError as exc:
        raise ValueError("the SSH port is not a number") from exc
    if not key:
        raise ValueError("the SSH line needs -i and the key file")
    return SshTarget(user, host, port_n, Path(os.path.expanduser(key)))


def ssh_argv(target: SshTarget) -> list[str]:
    return [
        _ssh_bin(),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=20",
        "-p", str(target.port),
        "-i", str(target.key),
        f"{target.user}@{target.host}",
    ]


def scp_argv(target: SshTarget, source: str, dest: str) -> list[str]:
    return [
        _scp_bin(),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-P", str(target.port),
        "-i", str(target.key),
        source,
        dest,
    ]


def _ssh_bin() -> str:
    return shutil.which("ssh") or "ssh"


def _scp_bin() -> str:
    return shutil.which("scp") or "scp"


def _tail(text: str, limit: int = 1500) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


class Remote:
    """One pod. ``run`` feeds a bash script to ``bash -s``."""

    def run(self, script: str, timeout: float | None = None) -> str:
        raise NotImplementedError

    def put(self, local: Path, remote: str) -> None:
        raise NotImplementedError

    def get(self, remote: str, local: Path) -> None:
        raise NotImplementedError


class SystemRemote(Remote):
    def __init__(self, target: SshTarget):
        self.target = target

    def run(self, script: str, timeout: float | None = None) -> str:
        try:
            done = subprocess.run(
                ssh_argv(self.target) + ["bash", "-s"],
                input=script.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PodError("the pod did not answer in time") from exc
        except FileNotFoundError as exc:
            raise PodError("ssh was not found on this machine") from exc
        if done.returncode != 0:
            detail = _tail(done.stderr.decode("utf-8", "replace") or done.stdout.decode("utf-8", "replace"))
            raise PodError(detail or f"ssh exited {done.returncode}")
        return done.stdout.decode("utf-8", "replace")

    def put(self, local: Path, remote: str) -> None:
        self._copy(str(local), f"{self.target.user}@{self.target.host}:{remote}", timeout=300)

    def get(self, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self._copy(f"{self.target.user}@{self.target.host}:{remote}", str(local), timeout=300)

    def _copy(self, source: str, dest: str, timeout: float) -> None:
        try:
            done = subprocess.run(
                scp_argv(self.target, source, dest),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PodError("copying to the pod did not finish in time") from exc
        except FileNotFoundError as exc:
            raise PodError("scp was not found on this machine") from exc
        if done.returncode != 0:
            detail = _tail(done.stderr.decode("utf-8", "replace"))
            raise PodError(detail or f"scp exited {done.returncode}")


def prepare_pod(remote: Remote, label=None) -> str:
    """Probe the pod and install HYPIR when the weights are not there yet."""
    if label:
        label("Checking the pod")
    probe = remote.run(PROBE_SH, timeout=40)
    if "CONNECTED" not in probe:
        raise PodError(_tail(probe) or "the pod did not answer")
    if label:
        label("Checking HYPIR on the pod")
    state = remote.run(CHECK_SH, timeout=40)
    if "READY" in state.split():
        return "HYPIR is already on the pod."
    if label:
        label("Installing HYPIR on the pod")
    installed = remote.run(INSTALL_SH, timeout=3600)
    if "READY" not in installed.split():
        raise PodError(_tail(installed) or "HYPIR install did not finish")
    return "HYPIR is installed on the pod."


def run_hypir(remote: Remote, source: Path, dest_dir: Path, label=None) -> tuple[Path, Path]:
    """Upload ``source``, run the 2x pass, save ``hypir.png`` and a same-size copy."""
    if label:
        label("Sending the level to the pod")
    remote.run("mkdir -p " + f"{POD_ROOT}/job/in", timeout=40)
    remote.put(source, REMOTE_IN)
    if label:
        label("Running HYPIR")
    remote.run(RUN_SH, timeout=3600)
    dest_dir.mkdir(parents=True, exist_ok=True)
    hypir = dest_dir / "hypir.png"
    native = dest_dir / "hypir_native.png"
    if label:
        label("Copying the result back")
    remote.get(REMOTE_OUT, hypir)
    save_native(source, hypir, native)
    return hypir, native


def save_native(source: Path, hypir: Path, dest: Path) -> None:
    """The 2x result scaled back to the source size, for a same-crop look."""
    with Image.open(source) as src, Image.open(hypir) as out:
        size = src.size
        picture = out.convert("RGB")
        if picture.size != size:
            picture = picture.resize(size, Image.Resampling.LANCZOS)
        picture.save(dest)
