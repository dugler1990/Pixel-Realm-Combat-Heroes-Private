#!/usr/bin/env bash
# One-off install of the open-weight ML tools on the GPU box.
#
#   bash tools/boss_sprite_pipeline/gpu_box/setup.sh [hunyuan3d] [unirig] [trellis]
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
mkdir -p "$VENDOR"
TOOLS=("$@"); [ ${#TOOLS[@]} -eq 0 ] && TOOLS=(hunyuan3d unirig)

command -v uv >/dev/null || { echo "install uv first: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "WARNING: nvidia-smi not found"

clone() { # clone <url> <dir>
  if [ -d "$2/.git" ]; then git -C "$2" pull --ff-only; else git clone --depth 1 "$1" "$2"; fi
}

for tool in "${TOOLS[@]}"; do
  case "$tool" in
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
