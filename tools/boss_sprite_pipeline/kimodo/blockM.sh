#!/bin/bash
# Block M - model comparison. Runs FIRST: if a newer checkpoint is visibly stronger there is no
# point tuning constraints on a superseded one. Identical prompt, identical seed, identical
# duration across all four - the model is the only thing that varies.
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=0 PYTHONUNBUFFERED=1
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
. /workspace/kimodo-venv/bin/activate
OUT=/workspace/blockM
mkdir -p $OUT
SEED=12345
DUR=4.0

declare -A P
P[haymaker]="A huge fat drunk brute throws a wild haymaker punch, swinging his whole heavy body around and stumbling off balance."
P[groundsmash]="A huge drunken brute raises both arms high and slams them down into the ground, its whole body lurching after the blow."
P[jump]="A massive clumsy creature crouches then launches itself upward off both legs, flailing, and crashes back down off balance."

for MODEL in Kimodo-SOMA-RP-v1 Kimodo-SOMA-RP-v1.1 Kimodo-SOMA-SEED-v1 Kimodo-SOMA-SEED-v1.1; do
  for A in haymaker groundsmash jump; do
    D="$OUT/${MODEL}__${A}"
    [ -d "$D" ] && [ "$(find "$D" -name '*.bvh' | wc -l)" -gt 0 ] && { echo "SKIP $MODEL $A"; continue; }
    echo "=== $MODEL / $A  $(date +%H:%M:%S)"
    kimodo_gen "${P[$A]}" --model "$MODEL" --duration $DUR --diffusion_steps 100 \
      --cfg_type separated --cfg_weight 3.0 2.0 --num_samples 2 --seed $SEED --bvh \
      --output "$D" 2>&1 2>&1 | tail -3
  done
done
echo "bvh: $(find $OUT -name '*.bvh' | wc -l)"
echo BLOCK_M_DONE
