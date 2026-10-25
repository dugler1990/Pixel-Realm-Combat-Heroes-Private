#!/bin/bash
# Block N - constraint CLASS. We have only ever used FullBodyConstraintSet, which pins all 78
# joints at the anchor frames; that is almost certainly why anchored attacks go limp. Root2D
# pins only where he stands, EndEffector only hands and feet - both leave the body free to
# perform the motion while still returning him home.
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=0 PYTHONUNBUFFERED=1
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
. /workspace/kimodo-venv/bin/activate
MODEL=${MODEL:-Kimodo-SOMA-RP-v1}
SEED=12345
R=/workspace/runs
mkdir -p $R
C=/workspace/cons
declare -A P
P[haymaker]="A huge fat drunk brute throws a wild haymaker punch, swinging his whole heavy body around and stumbling off balance."
P[groundsmash]="A huge drunken brute raises both arms high and slams them down into the ground, its whole body lurching after the blow."
P[jump]="A massive clumsy creature crouches then launches itself upward off both legs, flailing, and crashes back down off balance."

gen () {
  local name=$1 prompt=$2 dur=$3; shift 3
  local D="$R/$name"
  [ -d "$D" ] && [ "$(find "$D" -name '*.bvh' 2>/dev/null | wc -l)" -gt 0 ] && { echo "SKIP $name"; return; }
  echo "=== $name $(date +%H:%M:%S)"
  kimodo_gen "$prompt" --model "$MODEL" --duration "$dur" --diffusion_steps 100 \
    --num_samples 2 --seed $SEED --bvh --output "$D" "$@" 2>&1 | tail -2
}
CFG="--cfg_type separated --cfg_weight 3.0 2.0"
for A in haymaker groundsmash jump; do
  [ -f $C/full_120.json   ] && gen "N1_full_${A}"   "${P[$A]}" 4.0 $CFG --constraints $C/full_120.json
  [ -f $C/root2d_120.json ] && gen "N2_root2d_${A}" "${P[$A]}" 4.0 $CFG --constraints $C/root2d_120.json
  [ -f $C/endeff_120.json ] && gen "N3_endeff_${A}" "${P[$A]}" 4.0 $CFG --constraints $C/endeff_120.json
done
echo BLOCK_N_DONE
