#!/usr/bin/env bash
# UniRig on the pod: /workspace/unirig_in/mesh.glb -> /workspace/unirig_out/rigged.glb (skeleton + skin weights).
# pod.py unirig push / run / pull drives it (outfit.py's rig step); prints RIG_OK or RIG_FAILED.
# The install is the one that worked by hand (NOTES_rig_jaw_sam3.md section 1, 2026-09): python 3.11 (UniRig's bpy
# 4.2 wheel), torch 2.7.0 cu126, requirements without flash_attn, then the prebuilt flash_attn wheel fetched with
# curl (uv crawled at 130 KB/s on the github url), spconv-cu126, pyg wheels, numpy 1.26.4, libegl1 / libgl1 (the
# skin stage imports open3d / pyrender), TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 (the skin checkpoint pickles box.Box).
# Installed once per pod (~15 min; /workspace/unirig/.installed), then ~3 min a mesh. No xformers.
set -euo pipefail
trap 'echo RIG_FAILED' ERR
D=/workspace/unirig
mkdir -p /workspace/unirig_out
if [ ! -f "$D/.installed" ]; then
  echo "== install UniRig"
  (apt-get update -qq && apt-get install -y -qq libegl1 libgl1 git curl) >/dev/null
  [ -d "$D/.git" ] || git clone -q https://github.com/VAST-AI-Research/UniRig.git "$D"
  command -v uv >/dev/null || pip install -q uv
  cd "$D"
  [ -x .venv/bin/python ] || uv venv -q --python 3.11 .venv
  PY=.venv/bin/python
  uv pip install -q --python $PY torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu126
  grep -v -i flash_attn requirements.txt > /tmp/unirig_req.txt
  uv pip install -q --python $PY -r /tmp/unirig_req.txt
  uv pip install -q --python $PY spconv-cu126
  uv pip install -q --python $PY torch_scatter torch_cluster -f https://data.pyg.org/whl/torch-2.7.0+cu126.html
  uv pip install -q --python $PY numpy==1.26.4 pip psutil
  ABI=$($PY -c "import torch; print('TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE')")
  WHL="flash_attn-2.8.3+cu12torch2.7cxx11abi${ABI}-cp311-cp311-linux_x86_64.whl"
  curl -sSL -o "$D/$WHL" "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/$WHL"   # not /tmp: TRELLIS globs /tmp/flash_attn-*.whl
  uv pip install -q --python $PY "$D/$WHL"
  touch .installed
  echo "== installed"
fi
[ -n "${UNIRIG_INSTALL_ONLY:-}" ] && { echo UNIRIG_INSTALLED; exit 0; }
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
export PATH="$D/.venv/bin:$PATH"
cd "$D"
IN=/workspace/unirig_in/mesh.glb
OUT=/workspace/unirig_out
rm -f "$OUT"/skeleton.fbx "$OUT"/skin.fbx "$OUT"/rigged.glb
echo "== skeleton"
bash launch/inference/generate_skeleton.sh --input "$IN" --output "$OUT/skeleton.fbx" --seed "${SEED:-0}"
echo "== skin"
bash launch/inference/generate_skin.sh --input "$OUT/skeleton.fbx" --output "$OUT/skin.fbx"
echo "== merge"
bash launch/inference/merge.sh --source "$OUT/skin.fbx" --target "$IN" --output "$OUT/rigged.glb"
test -s "$OUT/rigged.glb"
echo RIG_OK
