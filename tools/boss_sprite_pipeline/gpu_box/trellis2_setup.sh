#!/usr/bin/env bash
# Repeatable TRELLIS.2 install for a disposable RunPod (A5000 24GB, torch 2.8+cu128).
#
#   bash tools/boss_sprite_pipeline/gpu_box/trellis2_setup.sh
#
# Does not download microsoft/TRELLIS.2-4B. Put an HF token at
# $HF_HOME/token (or export HF_TOKEN) before trellis2_run.py.
# Do not pip install unconstrained xformers: it pulls a second torch and fills 30GB.
set -euo pipefail

export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.6}"
export MAX_JOBS="${MAX_JOBS:-2}"
export HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa
export SPARSE_ATTN_BACKEND=flash_attn
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"

ROOT="${TRELLIS2_ROOT:-/workspace/vendor/TRELLIS.2}"
VENV="${TRELLIS2_VENV:-/workspace/vendor/trellis2-venv}"
EXT="${TRELLIS2_EXT:-/workspace/vendor/extensions}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v nvcc >/dev/null || { echo "nvcc missing; export CUDA_HOME=$CUDA_HOME"; exit 1; }
command -v g++ >/dev/null || { echo "g++ missing"; exit 1; }
command -v git >/dev/null || { echo "git missing"; exit 1; }
# o_voxel needs Eigen headers under /usr/include/eigen3
if [ ! -f /usr/include/eigen3/Eigen/Dense ]; then
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libeigen3-dev
fi
export CPATH="${CPATH:+$CPATH:}/usr/include/eigen3"
export CPLUS_INCLUDE_PATH="${CPLUS_INCLUDE_PATH:+$CPLUS_INCLUDE_PATH:}/usr/include/eigen3"
python3 - <<'PY'
import torch
assert torch.cuda.is_available(), "no CUDA torch"
print("TORCH", torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
PY
df -h / | tail -1

mkdir -p /workspace/vendor /workspace/in /workspace/out "$HF_HOME" "$EXT"
if [ ! -d "$ROOT/.git" ]; then
  git clone --depth 1 https://github.com/microsoft/TRELLIS.2.git "$ROOT"
fi
git -C "$ROOT" submodule update --init --recursive

python3 -m venv "$VENV" --system-site-packages
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install -U pip wheel setuptools ninja
pip install imageio imageio-ffmpeg tqdm easydict opencv-python-headless trimesh \
  transformers tensorboard pandas lpips zstandard kornia timm pillow einops
pip install git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

clone_ext() {
  local name="$1" url="$2" branch="${3:-}"
  if [ ! -d "$EXT/$name/.git" ]; then
    if [ -n "$branch" ]; then
      git clone --depth 1 -b "$branch" "$url" "$EXT/$name"
    else
      git clone --depth 1 "$url" "$EXT/$name"
    fi
    if [ -f "$EXT/$name/.gitmodules" ]; then
      git -C "$EXT/$name" submodule update --init --recursive
    fi
  fi
}

clone_ext nvdiffrast https://github.com/NVlabs/nvdiffrast.git v0.4.0
MAX_JOBS="$MAX_JOBS" pip install "$EXT/nvdiffrast" --no-build-isolation
clone_ext nvdiffrec https://github.com/JeffreyXiang/nvdiffrec.git renderutils
MAX_JOBS="$MAX_JOBS" pip install "$EXT/nvdiffrec" --no-build-isolation
clone_ext CuMesh https://github.com/JeffreyXiang/CuMesh.git
MAX_JOBS="$MAX_JOBS" pip install "$EXT/CuMesh" --no-build-isolation
clone_ext FlexGEMM https://github.com/JeffreyXiang/FlexGEMM.git
MAX_JOBS="$MAX_JOBS" pip install "$EXT/FlexGEMM" --no-build-isolation

rm -rf "$EXT/o-voxel"
cp -a "$ROOT/o-voxel" "$EXT/o-voxel"
pip install "$EXT/o-voxel" --no-build-isolation

python - <<'PY'
import sys
import torch
from pathlib import Path
import urllib.request

ver = torch.__version__.split("+")[0]
major_minor = ".".join(ver.split(".")[:2])
cuda = (torch.version.cuda or "12").split(".")[0]
py = f"cp{sys.version_info.major}{sys.version_info.minor}"
abi = "TRUE" if torch._C._GLIBCXX_USE_CXX11_ABI else "FALSE"
tag = "v2.8.3.post1"
name = f"flash_attn-2.8.3.post1+cu{cuda}torch{major_minor}cxx11abi{abi}-{py}-{py}-linux_x86_64.whl"
url = f"https://github.com/Dao-AILab/flash-attention/releases/download/{tag}/{name}"
dst = Path("/tmp") / name
print("FLASH_ATTN_WHEEL", url, flush=True)
try:
    urllib.request.urlretrieve(url, dst)
except Exception as exc:
    raise SystemExit(
        f"no prebuilt flash-attn wheel for torch={torch.__version__} py={py} abi={abi}: {exc}"
    ) from exc
print("WHEEL_OK", dst.stat().st_size, flush=True)
print(dst)
PY
pip install --no-deps /tmp/flash_attn-*.whl
python -c "import flash_attn, torch; print('flash_attn', flash_attn.__version__, 'torch', torch.__version__)"

python "$HERE/trellis2_patch.py"

python -c "import nvdiffrast, o_voxel, torch; print('INSTALL_OK', torch.__version__, torch.cuda.get_device_name(0))"
df -h / | tail -1
echo "HF_HOME=$HF_HOME"
if [ -n "${HF_TOKEN:-}" ]; then
  mkdir -p "$HF_HOME"
  printf '%s' "$HF_TOKEN" > "$HF_HOME/token"
  echo "HF_TOKEN_WRITTEN"
elif [ -f "$HF_HOME/token" ] || [ -f /root/.cache/huggingface/token ]; then
  echo "HF_TOKEN_PRESENT"
else
  echo "HF_TOKEN_MISSING  (export HF_TOKEN or run: hf auth login --token hf_...)"
fi
