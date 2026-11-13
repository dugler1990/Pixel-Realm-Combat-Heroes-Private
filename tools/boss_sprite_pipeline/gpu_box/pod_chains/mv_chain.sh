#!/usr/bin/env bash
# New pod (RTX PRO 4000 Blackwell): models in parallel with the install, flash-attn check, then the back-only
# orientation test and the front + back multi-view run once the back image is uploaded.
set -uo pipefail
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH HF_HOME=/workspace/.cache/huggingface \
  HF_HUB_ENABLE_HF_TRANSFER=0 ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
V=/workspace/vendor/trellis2-venv/bin/python
until $V -c "import huggingface_hub" 2>/dev/null; do sleep 15; done
echo "=== $(date +%T) downloads"
$V -c "from huggingface_hub import snapshot_download as s; s('microsoft/TRELLIS.2-4B'); s('facebook/dinov3-vitl16-pretrain-lvd1689m'); print('DL_OK')" > /workspace/logs/dl.log 2>&1 &
DL=$!
while pgrep -f "[t]rellis2_setup.sh" >/dev/null; do sleep 10; done
grep -q INSTALL_OK /workspace/setup.log || { echo "SETUP_FAILED"; grep -a -E "error|Error" /workspace/setup.log | tail -15; exit 1; }
echo "=== $(date +%T) INSTALL_OK"
$V -c "
import torch
from flash_attn import flash_attn_varlen_func
q = torch.randn(64, 8, 64, device='cuda', dtype=torch.float16)
cu = torch.tensor([0, 64], dtype=torch.int32, device='cuda')
o = flash_attn_varlen_func(q, q, q, cu, cu, 64, 64); torch.cuda.synchronize()
print('FA_OK', tuple(o.shape), torch.cuda.get_device_name(0))" 2>&1 | tail -3
wait $DL; tail -1 /workspace/logs/dl.log
echo "=== $(date +%T) waiting for the back image"
until [ -s /workspace/in/barb_fullplate_v2_back.png ]; do sleep 10; done
cd /workspace
echo "=== $(date +%T) back only (orientation test)"
$V -u /workspace/gpu_box/trellis2_run.py --image /workspace/in/barb_fullplate_v2_back.png --out-dir /workspace/out \
  --name barb_fullplate_v2_backonly --skip-texture > /workspace/logs/backonly.log 2>&1
echo "exit $? backonly"; [ -s /workspace/out/barb_fullplate_v2_backonly_from_front.glb ] && echo "GLB_OK backonly" || { echo GLB_MISSING backonly; tail -20 /workspace/logs/backonly.log; }
echo "=== $(date +%T) multiview front + back"
$V -u /workspace/gpu_box/trellis2_mv_run.py --front /workspace/in/barb_fullplate_v2.png --back /workspace/in/barb_fullplate_v2_back.png \
  --out-dir /workspace/out --name barb_fullplate_v2_mv > /workspace/logs/mv.log 2>&1
echo "exit $? mv"; [ -s /workspace/out/barb_fullplate_v2_mv_from_front.glb ] && echo "GLB_OK mv" || { echo GLB_MISSING mv; tail -30 /workspace/logs/mv.log; }
echo "ALL_DONE $(date +%T)"
