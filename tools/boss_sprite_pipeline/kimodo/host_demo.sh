#!/bin/bash
# Host Kimodo's interactive demo (kimodo_demo, port 7860) on a RunPod pod. Run ON THE POD:
#     bash /workspace/host_demo.sh
# Then on the PC (PowerShell), tunnel the port and open http://localhost:7860 :
#     ssh -N -L 7860:localhost:7860 -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp -p <port> root@<ip>
# Needs: an HF read token with access to meta-llama/Meta-Llama-3-8B-Instruct (gated) in
# /workspace/.cache/huggingface/token (PROCESS.md 7: Get-Clipboard | ssh ... "tr -cd 'A-Za-z0-9_' > ...").
# VRAM ~17 GB; TEXT_ENCODER_DEVICE=cpu bash host_demo.sh runs the text encoder on CPU (<3 GB GPU, slower).
# Install as install_kimodo.sh (uv venv, cu126 torch, kimodo[all]); skipped when the venv is already there.
set -uo pipefail
cd /workspace
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=0
mkdir -p "$HF_HOME"
TOKEN=/workspace/.cache/huggingface/token
until [ -s "$TOKEN" ]; do echo "waiting for the HF token at $TOKEN"; sleep 10; done
cp "$TOKEN" "$HF_HOME/token"
if [ ! -x /workspace/kimodo-venv/bin/kimodo_demo ]; then
  command -v uv >/dev/null || pip install -q uv
  uv venv --python 3.10 /workspace/kimodo-venv
  . /workspace/kimodo-venv/bin/activate
  uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
  uv pip install "kimodo[all] @ git+https://github.com/nv-tlabs/kimodo.git"
else
  . /workspace/kimodo-venv/bin/activate
fi
python -c "import torch, kimodo; print('IMPORTS_OK', torch.__version__, torch.cuda.is_available())" || exit 1
HF_TOKEN=$(cat "$HF_HOME/token") nohup kimodo_demo > /workspace/kimodo_demo.log 2>&1 &
echo "kimodo_demo started (pid $!), log /workspace/kimodo_demo.log; first launch downloads the models."
until grep -qi "7860\|running on\|error" /workspace/kimodo_demo.log 2>/dev/null; do sleep 10; done
tail -5 /workspace/kimodo_demo.log
