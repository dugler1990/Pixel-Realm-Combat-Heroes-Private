#!/usr/bin/env bash
# TRELLIS.2 for the outfit pipeline: the chosen models in one pod session. Run ON THE POD (pod.py trellis run does):
#     bash /workspace/gpu_box/trellis_outfit.sh [model ...]     (front_only front_back front_back_sides eight_views)
# In: /workspace/in/front.png [and back.png] (view_gate's accepted cut-outs, real alpha); the HF token at
# /workspace/.cache/huggingface/token (pod.py token). Out: /workspace/out/front_only_from_front.glb and, with a
# back, front_back_from_front.glb; with side_left.png + side_right.png too, front_back_sides_from_front.glb; with
# the four 3/4 views too (side_front_left.png ...), eight_views_from_front.glb (a model
# already in out/ is kept, not remade). Ends with TRELLIS_OK, or TRELLIS_FAILED.
# From pod_chains/v9_chain.sh (2026-11-09, pod 5 A40): install for this GPU's architecture with the models
# downloading alongside, flash-attn check, then trellis2_mv_run.py per job (front only; front + back).
set -uo pipefail
mkdir -p /workspace/logs /workspace/out
CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3 \
  TORCH_CUDA_ARCH_LIST=$CC MAX_JOBS=4 HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0 \
  ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "=== $(date +%T) GPU $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) arch $CC"
V=/workspace/vendor/trellis2-venv/bin/python
# Installed = the last setup ended in INSTALL_OK ("import trellis2" fails outside the TRELLIS.2 folder, so it
# reinstalled every run: 2026-11-13, ~12 min lost).
if ! grep -q INSTALL_OK /workspace/setup.log 2>/dev/null; then
  bash /workspace/gpu_box/trellis2_setup.sh > /workspace/setup.log 2>&1 &
  SETUP=$!
  until $V -c "import huggingface_hub" 2>/dev/null; do sleep 15; done
else
  SETUP=""
fi
until [ -s /workspace/.cache/huggingface/token ]; do echo "waiting for the HF token (pod.py token)"; sleep 10; done
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
$V -c "from huggingface_hub import snapshot_download as s; s('microsoft/TRELLIS.2-4B'); s('facebook/dinov3-vitl16-pretrain-lvd1689m'); print('DL_OK')" > /workspace/logs/dl.log 2>&1 &
DL=$!
if [ -n "$SETUP" ]; then
  wait $SETUP
  grep -q INSTALL_OK /workspace/setup.log || { echo "SETUP_FAILED"; grep -a -E "error|Error" /workspace/setup.log | tail -15; echo TRELLIS_FAILED; exit 1; }
fi
echo "=== $(date +%T) INSTALL_OK"
$V -c "
import torch
from flash_attn import flash_attn_varlen_func
q = torch.randn(64, 8, 64, device='cuda', dtype=torch.float16)
cu = torch.tensor([0, 64], dtype=torch.int32, device='cuda')
o = flash_attn_varlen_func(q, q, q, cu, cu, 64, 64); torch.cuda.synchronize(); print('FA_OK')" 2>&1 | tail -2
wait $DL; tail -1 /workspace/logs/dl.log
cd /workspace
I=/workspace/in; O=/workspace/out
jobs=("front_only|--front $I/front.png")
[ -s $I/back.png ] && jobs+=("front_back|--front $I/front.png --back $I/back.png")
[ -s $I/back.png ] && [ -s $I/side_left.png ] && [ -s $I/side_right.png ] && \
  jobs+=("front_back_sides|--front $I/front.png --back $I/back.png --left $I/side_left.png --right $I/side_right.png")
EIGHT="--front $I/front.png --back $I/back.png"
for v in left right front_left front_right back_left back_right; do
  [ -s $I/side_$v.png ] && EIGHT="$EIGHT --$v $I/side_$v.png" || EIGHT=""
  [ -z "$EIGHT" ] && break
done
[ -n "$EIGHT" ] && [ -s $I/back.png ] && jobs+=("eight_views|$EIGHT")
WANT=" $* "                      # the models asked for (pod.py --models); none = every model the views allow
for m in "$@"; do
  printf '%s\n' "${jobs[@]}" | grep -q "^$m|" || { echo "MODEL_MISSING_VIEWS $m"; echo "TRELLIS_FAILED"; exit 1; }
done
ok=1
for job in "${jobs[@]}"; do
  n=${job%%|*}; args=${job#*|}
  [ $# -gt 0 ] && [[ "$WANT" != *" $n "* ]] && continue
  if [ -s $O/${n}_from_front.glb ]; then echo "GLB_OK $n (already made)"; continue; fi
  echo "=== $(date +%T) $n"
  $V -u /workspace/gpu_box/trellis2_mv_run.py $args --out-dir $O --name $n > /workspace/logs/$n.log 2>&1
  if [ -s $O/${n}_from_front.glb ]; then echo "GLB_OK $n"; else echo "GLB_MISSING $n"; tail -20 /workspace/logs/$n.log; ok=0; fi
done
ls -la $O
[ $ok = 1 ] && echo "TRELLIS_OK $(date +%T)" || echo "TRELLIS_FAILED $(date +%T)"
