#!/usr/bin/env bash
# One-off install of the open-weight ML tools on the GPU box.
#
#   bash tools/boss_sprite_pipeline/gpu_box/setup.sh [stable_fast_3d] [hunyuan3d] [unirig] [trellis]
#
# Each tool gets its own checkout + venv under gpu_box/vendor/<tool>/ because
# their torch/CUDA pins disagree. The pipeline only ever calls
# gpu_box/<tool>_cli.py with that tool's venv python, so nothing here touches
# the project venv. Needs: git, uv (https://astral.sh/uv), an NVIDIA driver.
#
# STATUS: written from the upstream READMEs, not yet run on the box. Expect to
# iterate on pins here — fix them in this file, not by hand.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="$HERE/vendor"
SF3D_REV="ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2"
UV_VERSION="0.8.17"
mkdir -p "$VENDOR"
TOOLS=("$@"); [ ${#TOOLS[@]} -eq 0 ] && TOOLS=(hunyuan3d unirig)

command -v uv >/dev/null || { echo "install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
test "$(uv --version)" = "uv $UV_VERSION" || {
  echo "need uv $UV_VERSION (found: $(uv --version))"
  echo "install with: curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | sh"
  exit 1
}
command -v nvidia-smi >/dev/null || { echo "nvidia-smi is required"; exit 1; }
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
command -v nvcc >/dev/null || { echo "nvcc is required to build GPU extensions; use a CUDA devel image"; exit 1; }
command -v g++ >/dev/null || { echo "g++ is required to build the texture extensions"; exit 1; }

clone() { # clone <url> <dir>
  if [ -d "$2/.git" ]; then git -C "$2" pull --ff-only; else git clone --depth 1 "$1" "$2"; fi
}

checkout() { # checkout <url> <dir> <revision>
  if [ ! -d "$2/.git" ]; then git clone --filter=blob:none --no-checkout "$1" "$2"; fi
  git -C "$2" fetch --depth 1 origin "$3"
  git -C "$2" checkout --detach "$3"
  test "$(git -C "$2" rev-parse HEAD)" = "$3"
}

for tool in "${TOOLS[@]}"; do
  case "$tool" in
    stable_fast_3d)
      D="$VENDOR/stable_fast_3d"
      checkout https://github.com/Stability-AI/stable-fast-3d.git "$D" "$SF3D_REV"
      git -C "$D" submodule update --init --recursive
      uv venv --python 3.10 "$D/.venv"
      uv pip install --python "$D/.venv/bin/python" \
        "torch==2.4.1" "torchvision==0.19.1" --index-url https://download.pytorch.org/whl/cu124
      uv pip install --python "$D/.venv/bin/python" "setuptools==69.5.1" "wheel==0.44.0"
      ( cd "$D" && USE_CUDA=1 MAX_JOBS="${MAX_JOBS:-4}" \
        uv pip install --python "$D/.venv/bin/python" --no-build-isolation -r requirements.txt )
      "$D/.venv/bin/python" -c \
        "import sys, torch; sys.path.insert(0, '$D'); from sf3d.system import SF3D; assert torch.cuda.is_available(); print(torch.__version__, torch.cuda.get_device_name())"
      ;;
    hunyuan3d)
      D="$VENDOR/hunyuan3d"; clone https://github.com/Tencent/Hunyuan3D-2.git "$D"
      uv venv --python 3.10 "$D/.venv"
      uv pip install --python "$D/.venv/bin/python" torch torchvision --index-url https://download.pytorch.org/whl/cu124
      uv pip install --python "$D/.venv/bin/python" -r "$D/requirements.txt"
      uv pip install --python "$D/.venv/bin/python" -e "$D"
      # texture painting needs two compiled extensions
      ( cd "$D/hy3dgen/texgen/custom_rasterizer" && "$D/.venv/bin/python" setup.py install )
      ( cd "$D/hy3dgen/texgen/differentiable_renderer" && "$D/.venv/bin/python" setup.py install )
      ;;
    unirig)
      D="$VENDOR/unirig"; clone https://github.com/VAST-AI-Research/UniRig.git "$D"
      uv venv --python 3.11 "$D/.venv"
      uv pip install --python "$D/.venv/bin/python" torch torchvision --index-url https://download.pytorch.org/whl/cu124
      uv pip install --python "$D/.venv/bin/python" -r "$D/requirements.txt"
      # UniRig's launch scripts drive Blender for import/export; the bpy wheel
      # replaces a system Blender for headless use.
      uv pip install --python "$D/.venv/bin/python" "bpy==4.2.*" || true
      ;;
    trellis)
      D="$VENDOR/trellis"; clone https://github.com/microsoft/TRELLIS.git "$D"
      echo "TRELLIS has a compiled-extension chain (flash-attn, kaolin, nvdiffrast, spconv)."
      echo "Run its own installer inside a venv:  cd $D && . setup.sh --new-env --basic --xformers --flash-attn --diffoctreerast --spconv --mipgaussian --kaolin --nvdiffrast"
      echo "then symlink that env to $D/.venv so gpu_exec.py finds it."
      ;;
    *) echo "unknown tool $tool"; exit 1;;
  esac
done
echo "done: ${TOOLS[*]}"
