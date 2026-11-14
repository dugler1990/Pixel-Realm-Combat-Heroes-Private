#!/bin/bash
# SAM3 on a RunPod pod for the explode (step 4): set up, then label every rendered view.
# Recipe from explode/PROCESS_explode.md (v1) and explode2/PROCESS_explode2.md step 4. Run ON THE POD:
#     bash /workspace/sam3_pod.sh /workspace/views [/workspace/prompts.json]
# Upload first, from the PC (Git Bash; direct IP + port, key ppp):
#     scp -r <~/.cache/huggingface/hub/models--facebook--sam3/snapshots/<id>>  root@<ip>:/workspace/sam3   (3.2 GB; gated on HF)
#     scp -r C:/Users/Douglas/sam3local/src                                   root@<ip>:/workspace/sam3local_src
#     scp tools/boss_sprite_pipeline/explode/explode_sam.py <prompts.json> this file  root@<ip>:/workspace/
#     scp -r <work>/views                                                      root@<ip>:/workspace/views
# Venv with --system-site-packages reuses the template's torch (Ubuntu 24.04 refuses system pip, PEP 668).
# Versions as the working local sam3local venv (transformers 5.12.1 has Sam3Model).
# 3 shards side by side keep the GPU busy (explode2 step 4: 226 views, ~29 min; 55 views ~4 min).
set -uo pipefail
VIEWS=${1:?views dir}; PROMPTS=${2:-}
[ -x /workspace/sv/bin/python ] || {
  python3 -m venv --system-site-packages /workspace/sv
  /workspace/sv/bin/pip install -q "transformers==5.12.1" opencv-python-headless pillow numpy safetensors
}
/workspace/sv/bin/python -c "from transformers import Sam3Model; import cv2, torch; print('SAM3_READY', torch.cuda.is_available())" || exit 1
export SAM3_SRC=/workspace/sam3local_src SAM3_MODEL=/workspace/sam3 SAM3_SIZE=1008 SAM3_DTYPE=float32
for i in 0 1 2; do
  SAM3_SHARD=$i/3 /workspace/sv/bin/python /workspace/explode_sam.py "$VIEWS" $PROMPTS > /workspace/sam_shard$i.log 2>&1 &
done
wait
for f in /workspace/sam_shard*.log; do tail -n 2 $f; done
echo SAM_DONE
