#!/bin/bash
# Every remaining block. Runs after blockM. Each cell is skipped if it already has BVH, so this
# is safe to re-run after an interruption. Fixed seed throughout: every cell is comparable, and
# none of it carries the seed noise our earlier comparisons had.
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=0 PYTHONUNBUFFERED=1
export HF_TOKEN=$(cat /workspace/.cache/huggingface/token)
. /workspace/kimodo-venv/bin/activate
MODEL=${MODEL:-Kimodo-SOMA-RP-v1}      # overridden to block M's winner
SEED=12345
R=/workspace/runs
mkdir -p $R

# wording: ORIG produced the clips Douglas rated; HEAVY is the rewrite whose energy collapsed
declare -A ORIG HEAVY SINGLE NOCRE
ORIG[haymaker]="A huge fat drunk brute throws a wild haymaker punch, swinging his whole heavy body around and stumbling off balance."
ORIG[groundsmash]="A huge drunken brute raises both arms high and slams them down into the ground, its whole body lurching after the blow."
ORIG[jump]="A massive clumsy creature crouches then launches itself upward off both legs, flailing, and crashes back down off balance."
ORIG[damage]="A huge fat drunk brute takes a hard hit to the chest, staggering backwards and nearly falling over."
ORIG[slap]="A massive obese ogre swings a giant open hand in a sloppy violent sideways slap, his whole bulk lurching after it."
HEAVY[haymaker]="A giant gorilla loads all its weight onto its right side, then swings one massive arm in a single wide bear swipe across to the left, following through with its whole body."
HEAVY[groundsmash]="A giant gorilla raises both fists high above its head and smashes them straight down into the ground with enormous force, staying planted and heavy."
HEAVY[jump]="A huge heavy monster crouches deep then explodes upward off both legs as high as it can, hangs at the top, and crashes back down."
HEAVY[damage]="A massive heavy creature is struck in the chest and steps back, absorbing the impact."
HEAVY[slap]="A huge heavy creature swings one open hand across in a single clear sideways slap, arm fully extended away from its body."
SINGLE[haymaker]="A huge brute throws a haymaker punch."
SINGLE[groundsmash]="A huge brute slams both arms into the ground."
SINGLE[jump]="A huge brute jumps as high as it can."
SINGLE[damage]="A huge brute is hit and staggers back."
SINGLE[slap]="A huge brute slaps sideways with an open hand."
NOCRE[haymaker]="A big heavy man throws a wild haymaker punch, swinging his whole body around and stumbling off balance."
NOCRE[groundsmash]="A big heavy man raises both arms high and slams them down into the ground, lurching after the blow."
NOCRE[jump]="A big heavy man crouches then launches himself upward off both legs, flailing, and crashes back down."
NOCRE[damage]="A big heavy man takes a hard hit to the chest, staggering backwards and nearly falling over."
NOCRE[slap]="A big heavy man swings an open hand in a violent sideways slap, his bulk lurching after it."

gen () {  # name  prompt  duration  [extra args...]
  local name=$1 prompt=$2 dur=$3; shift 3
  local D="$R/$name"
  if [ -d "$D" ] && [ "$(find "$D" -name '*.bvh' 2>/dev/null | wc -l)" -gt 0 ]; then
    echo "SKIP $name"; return
  fi
  echo "=== $name  dur=$dur  $*  $(date +%H:%M:%S)"
  kimodo_gen "$prompt" --model "$MODEL" --duration "$dur" --diffusion_steps 100 \
    --num_samples 2 --seed $SEED --bvh --output "$D" "$@" 2>&1 | tail -2
}
CFG="--cfg_type separated --cfg_weight 3.0 2.0"

# ---- B0 replication: the rated clips on their original wording -------------------------
for A in haymaker groundsmash jump damage slap; do
  gen "B0_${A}" "${ORIG[$A]}" 4.0 $CFG
done

# ---- B1 duration sweep, no anchor vs anchor fitted to the clip's own frame count --------
for A in haymaker groundsmash; do
  for D in 2.0 3.0 4.0 5.0 6.0 8.0; do
    FR=$(python -c "print(int($D*30))")
    gen "B1_none_${D%%.*}s_${A}" "${ORIG[$A]}" $D $CFG
    if [ -f /workspace/cons/constraints_${FR}.json ]; then
      gen "B1_fit_${D%%.*}s_${A}"  "${ORIG[$A]}" $D $CFG --constraints /workspace/cons/constraints_${FR}.json
    fi
  done
  # ---- B1b the bug: 240-frame clip driven by the 150-frame constraint -------------------
  [ -f /workspace/cons/constraints_150.json ] && \
    gen "B1b_stale_8s_${A}" "${ORIG[$A]}" 8.0 $CFG --constraints /workspace/cons/constraints_150.json
done

# ---- C chaining: Kimodo's native idle -> action -> idle ---------------------------------
for A in haymaker groundsmash jump; do
  P="${ORIG[$A]}"
  gen "C1_bal_${A}"    "A huge heavy brute stands ready. ${P} It returns to standing." "1.0 2.5 1.0" $CFG
  gen "C2_longact_${A}" "A huge heavy brute stands ready. ${P} It returns to standing." "0.5 4.0 0.5" $CFG
  gen "C3_even_${A}"   "A huge heavy brute stands ready. ${P} It returns to standing." "2.0 2.0 2.0" $CFG
  gen "C4_stance_${A}" "A huge heavy brute crouches low in a fighting stance. ${P} It settles back into the fighting stance." "1.0 2.5 1.0" $CFG
  gen "C5_trans_${A}"  "A huge heavy brute stands ready. ${P} It returns to standing." "1.0 2.5 1.0" $CFG --num_transition_frames 15
  gen "C7_nochain_${A}" "$P" 4.5 $CFG
  gen "Cp_5chunk_${A}" "A huge heavy brute stands ready. It winds up. ${P} It recovers. It stands ready again." "0.8 0.8 2.0 0.8 0.8" $CFG
done

# ---- CW chaining x wording --------------------------------------------------------------
for A in haymaker groundsmash jump; do
  gen "CW_heavy_${A}" "A huge heavy brute stands ready. ${HEAVY[$A]} It returns to standing." "1.0 2.5 1.0" $CFG
done

# ---- G guidance mode --------------------------------------------------------------------
for A in haymaker groundsmash; do
  P="A huge heavy brute stands ready. ${ORIG[$A]} It returns to standing."
  gen "G_nocfg_${A}"   "$P" "1.0 2.5 1.0" --cfg_type nocfg
  gen "G_regular_${A}" "$P" "1.0 2.5 1.0" --cfg_type regular --cfg_weight 3.0
  gen "G_sep6_${A}"    "$P" "1.0 2.5 1.0" --cfg_type separated --cfg_weight 3.0 6.0
done

# ---- W wording sweep ---------------------------------------------------------------------
for A in haymaker groundsmash jump damage slap; do
  gen "W_heavy_${A}"  "${HEAVY[$A]}"  4.0 $CFG
  gen "W_single_${A}" "${SINGLE[$A]}" 4.0 $CFG
  gen "W_nocre_${A}"  "${NOCRE[$A]}"  4.0 $CFG
done

# ---- O one-offs ---------------------------------------------------------------------------
for A in haymaker groundsmash; do
  gen "O_nopost_${A}" "${ORIG[$A]}" 4.0 $CFG --no-postprocess
  gen "O_tpose_${A}"  "${ORIG[$A]}" 4.0 $CFG --bvh_standard_tpose
  gen "O_steps250_${A}" "${ORIG[$A]}" 4.0 $CFG --diffusion_steps 250
done

echo "total bvh: $(find $R -name '*.bvh' | wc -l)"
echo RUNALL_DONE
