#!/bin/bash
# Every category of the settled 374-clip plan -> its own contact sheet and its own labelled
# reel. One block per row of that table, same names, so a result can be pointed at by category.
#
# The model blocks live in /workspace/blockM* rather than /workspace/runs, so they are pulled
# separately; blockM3's cells are the abandoned n=6 attempt and are superseded by the M3_* cells.
set -u
S="$(cd "$(dirname "$0")" && pwd)"
cd "$S" || exit 1

for b in \
  "M_models:(Kimodo-SOMA|RPv1_1|SEEDv1_1)" \
  "M3_model_seeds:M3_" \
  "Mplus_steps:O_steps" \
  "B0_baseline:B0_" \
  "B1_duration:B1_" \
  "B1b_bug:B1b_" \
  "C_chaining:C[1-7]_" \
  "Cplus_depth:Cp_" \
  "CW_chain_wording:CW_" \
  "N_constraints:N[1-4]_" \
  "G_guidance:G_" \
  "W_wording:W_" \
  "O_oneoffs:O_(nopost|tpose)" \
  "P_prompts:P_" ; do
  bash make_block.sh "${b%%:*}" "${b#*:}" 2>&1 | grep -E "^SHEET|^BLOCK_REEL|^BLOCK_DONE|Traceback"
done
echo FINAL_PASS_DONE
