#!/usr/bin/env bash
# Fresh pod: install for this GPU's architecture, models in parallel, flash-attn check, then gate front + back multi-view.
set -uo pipefail
CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3 \
  TORCH_CUDA_ARCH_LIST=$CC MAX_JOBS=4 HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0 \
  ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
echo "=== $(date +%T) GPU $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) arch $CC"
bash /workspace/gpu_box/trellis2_setup.sh > /workspace/setup.log 2>&1 &
SETUP=$!
V=/workspace/vendor/trellis2-venv/bin/python
until $V -c "import huggingface_hub" 2>/dev/null; do sleep 15; done
until [ -s /workspace/.cache/huggingface/token ]; do sleep 10; done
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
$V -c "from huggingface_hub import snapshot_download as s; s('microsoft/TRELLIS.2-4B'); s('facebook/dinov3-vitl16-pretrain-lvd1689m'); print('DL_OK')" > /workspace/logs/dl.log 2>&1 &
DL=$!
wait $SETUP
grep -q INSTALL_OK /workspace/setup.log || { echo "SETUP_FAILED"; grep -a -E "error|Error" /workspace/setup.log | tail -15; exit 1; }
echo "=== $(date +%T) INSTALL_OK"
$V -c "
import torch
from flash_attn import flash_attn_varlen_func
q = torch.randn(64, 8, 64, device='cuda', dtype=torch.float16)
cu = torch.tensor([0, 64], dtype=torch.int32, device='cuda')
o = flash_attn_varlen_func(q, q, q, cu, cu, 64, 64); torch.cuda.synchronize(); print('FA_OK')" 2>&1 | tail -2
wait $DL; tail -1 /workspace/logs/dl.log
cd /workspace
echo "=== $(date +%T) multiview gate front + back"
$V -u /workspace/gpu_box/trellis2_mv_run.py --front /workspace/in/gate_front.png --back /workspace/in/gate_back.png \
  --out-dir /workspace/out --name barb_fullplate_v2_gate_mv > /workspace/logs/gate_mv.log 2>&1
echo "exit $? gate_mv"; [ -s /workspace/out/barb_fullplate_v2_gate_mv_from_front.glb ] && echo "GLB_OK gate_mv" || { echo GLB_MISSING gate_mv; tail -30 /workspace/logs/gate_mv.log; }
echo "ALL_DONE $(date +%T)"
