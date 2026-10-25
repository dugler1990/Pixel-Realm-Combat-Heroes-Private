#!/bin/bash
set -uxo pipefail
cd /workspace
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=0
uv venv --python 3.10 /workspace/kimodo-venv
. /workspace/kimodo-venv/bin/activate
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
uv pip install "kimodo[all] @ git+https://github.com/nv-tlabs/kimodo.git"
python -c "import torch,kimodo;print('IMPORTS_OK',torch.__version__,torch.cuda.is_available())"
echo INSTALL_DONE
