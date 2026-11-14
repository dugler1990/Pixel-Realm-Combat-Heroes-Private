#!/bin/bash
# HoloPart on a RunPod pod for the explode: install (once), then complete every cut piece. Run ON THE POD:
#     bash /workspace/holopart_pod.sh install
#     bash /workspace/holopart_pod.sh run /workspace/input_parts.glb /workspace/holopart_out
# Upload first: this file and holopart_patch.py (both in tools/boss_sprite_pipeline/explode/), and the cut's
# input_parts.glb (explode_label.py output: one mesh per part). Pull back <out>/output.glb (+ latents).
# Recipe from explode/PROCESS_explode.md step 5 (v1, 2026-11-01) and explode2 step 8: HoloPart @ 48dd632,
# venv --system-site-packages on the PyTorch 2.8 template (needs nvcc), holopart_patch.py (150k faces per part,
# Taubin 10, latents saved). Weights download from HF VAST-AI/HoloPart (MIT). v1: 14 parts in ~9 min.
set -uo pipefail
cd /workspace
case "${1:-}" in
install)
  apt-get update -q > /dev/null && apt-get install -y -q libopengl0 libgl1 libglu1-mesa libegl1 > /dev/null   # pymeshlab's decimation plugin
  [ -d HoloPart ] || { git clone -q https://github.com/VAST-AI-Research/HoloPart && git -C HoloPart checkout -q 48dd632; }
  python3 -m venv --system-site-packages hp
  . hp/bin/activate
  # pinned (2026-11-12): diffusers 0.43 dropped models.normalization.LayerNorm, which HoloPart @ 48dd632 imports
  pip install -q "diffusers==0.32.2" "transformers==4.49.0" "peft==0.14.0" einops huggingface_hub opencv-python-headless trimesh omegaconf \
      scikit-image jaxtyping typeguard pymeshlab
  TV=$(python -c "import torch; print(torch.__version__.split('+')[0])"); CU=$(python -c "import torch; print('cu' + torch.version.cuda.replace('.', ''))")
  pip install -q torch-cluster -f "https://data.pyg.org/whl/torch-$TV+$CU.html"
  CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
  TORCH_CUDA_ARCH_LIST=$CC MAX_JOBS=16 pip install -q --no-build-isolation diso
  python /workspace/holopart_patch.py /workspace/HoloPart
  python -c "import diso, torch_cluster, pymeshlab; print('DECIMATE', hasattr(pymeshlab.MeshSet(), 'meshing_decimation_quadric_edge_collapse')); print('HP_READY')"
  ;;
run)
  IN=${2:?input_parts.glb}; OUT=${3:?output dir}
  . hp/bin/activate && cd HoloPart
  HP_LATENTS=$OUT/latents.pt python -m scripts.inference_holopart --mesh-input "$IN" --output-dir "$OUT" > "$OUT.log" 2>&1
  ls -la "$OUT"; tail -3 "$OUT.log"; echo HP_DONE
  ;;
*) echo "usage: holopart_pod.sh install | run <input_parts.glb> <out_dir>"; exit 1 ;;
esac
