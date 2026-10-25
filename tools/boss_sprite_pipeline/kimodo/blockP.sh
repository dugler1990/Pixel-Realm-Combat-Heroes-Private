#!/bin/bash
# Block P - prompts rewritten to NVIDIA's documented guidelines, against our current wording.
# Every prompt begins "A person", keeps to one or two behaviours, uses a supported style token
# (angry/injured) where styled, and ends at idle IN THE PROMPT - so no constraint file is
# involved and this also tests whether the constraint apparatus was ever needed.
# Chunks are standalone sentences: the docs warn against pronoun continuations ("Then the
# person stops"), which is exactly what our old chains did ("It returns to standing").
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=0 PYTHONUNBUFFERED=1
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
. /workspace/kimodo-venv/bin/activate
MODEL=${MODEL:-Kimodo-SOMA-SEED-v1.1}
R=/workspace/runs; mkdir -p $R
CFG="--cfg_type separated --cfg_weight 3.0 2.0"
STANCE="A person stands still in a combat stance."
RECOVER="A person recovers their balance."
RECIDLE="A person recovers their balance and stands idle."

declare -A V1 V2 V3 WIND STRIKE
V1[haymaker]="A person throws a heavy punch with their right arm, then stands idle."
V2[haymaker]="An angry person throws a heavy punch with their right arm, then stands idle."
V3[haymaker]="A person swings their right arm forcefully across their body at chest height, then stands idle."
WIND[haymaker]="A person winds up, shifting their weight onto their right leg."
STRIKE[haymaker]="A person throws a heavy punch with their right arm."
V1[groundsmash]="A person slams both fists down onto the ground, then stands idle."
V2[groundsmash]="An angry person slams both fists down onto the ground, then stands idle."
V3[groundsmash]="A person raises both arms overhead and strikes downward heavily onto the ground, then stands idle."
WIND[groundsmash]="A person raises both arms high above their head."
STRIKE[groundsmash]="A person slams both fists down onto the ground."
V1[jump]="A person jumps straight up as high as they can, then lands and stands idle."
V2[jump]="An angry person jumps straight up as high as they can, then lands and stands idle."
V3[jump]="A person crouches deeply and jumps powerfully straight upward, then lands and stands idle."
WIND[jump]="A person crouches deeply with both knees bent."
STRIKE[jump]="A person jumps straight up as high as they can."
V1[damage]="A person is struck in the chest and staggers backward, then stands idle."
V2[damage]="An injured person is struck in the chest and staggers backward, then stands idle."
V3[damage]="A person recoils sharply backward from a heavy impact to their chest, catching themselves on their right leg, then stands idle."
WIND[damage]="A person braces themselves in a combat stance."
STRIKE[damage]="A person is struck in the chest and staggers backward."
V1[slap]="A person swings their open right hand sideways in a wide slap, then stands idle."
V2[slap]="An angry person swings their open right hand sideways in a wide slap, then stands idle."
V3[slap]="A person sweeps their open right hand horizontally across their body at shoulder height, then stands idle."
WIND[slap]="A person twists their torso to the right, drawing their arm back."
STRIKE[slap]="A person swings their open right hand sideways in a wide slap."

gen () {
  local name=$1 prompt=$2 dur=$3
  local D="$R/$name"
  [ -d "$D" ] && [ "$(find "$D" -name '*.bvh' 2>/dev/null | wc -l)" -gt 0 ] && { echo "SKIP $name"; return; }
  echo "=== $name  [$dur]  $(date +%H:%M:%S)"
  kimodo_gen "$prompt" --model "$MODEL" --duration "$dur" --diffusion_steps 100 \
    --num_samples 2 --seed 12345 --bvh --output "$D" $CFG 2>&1 | tail -1
}

for A in haymaker groundsmash jump damage slap; do
  gen "P_V1_${A}" "${V1[$A]}" 4.0
  gen "P_V2_${A}" "${V2[$A]}" 4.0
  gen "P_V3_${A}" "${V3[$A]}" 4.0
  gen "P_K1_${A}" "$STANCE ${STRIKE[$A]} $STANCE"                                   "1.0 2.5 1.0"
  gen "P_K2_${A}" "$STANCE ${STRIKE[$A]} $STANCE"                                   "0.5 4.0 0.5"
  gen "P_K3_${A}" "$STANCE ${WIND[$A]} ${STRIKE[$A]} $RECOVER $STANCE"              "0.8 0.8 2.0 0.8 0.8"
  gen "P_K4_${A}" "$STANCE ${WIND[$A]} $(echo "${STRIKE[$A]}" | sed 's/^A person/An angry person/') $RECOVER $STANCE" "0.8 0.8 2.0 0.8 0.8"
  gen "P_K5_${A}" "${WIND[$A]} ${STRIKE[$A]} $RECIDLE"                              "1.0 2.0 1.5"
done
echo "P cells: $(ls $R | grep -c '^P_')"
echo BLOCK_P_DONE
