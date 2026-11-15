#!/usr/bin/env bash
# Draw an outfit's back + side / 3/4 views unattended: accept a view that passes its check, else redraw once with
# the failure as the reason and accept that. OPENAI_API_KEY / OUTFIT_DATA_ROOT from the environment.
#     bash tools/boss_sprite_pipeline/views_auto.sh <character> <outfit>
set -u
C=$1; O=$2; PY=Code/sprite_venv/Scripts/python.exe
run() { $PY -m tools.boss_sprite_pipeline.outfit $C $O "$@" 2>&1; }
last() { echo "$1" | grep -o -E "attempt [0-9]+ drawn" | tail -1 | grep -o -E "[0-9]+"; }
step() {   # step [view]
  local v=${2:-} va=(); [ -n "$v" ] && va=(--view $v)
  out=$(run --only $1 "${va[@]}")
  if echo "$out" | grep -q "STEP_DONE"; then return 0; fi
  n=$(last "$out"); [ -z "$n" ] && { echo "$out" | tail -3; return 1; }
  if ! echo "$out" | grep -q -E "(back|side|front).*: PASS"; then
    out=$(run --only $1 "${va[@]}" --retry "r keep the same full height as Image 1: head top and feet at the same heights, the same figure")
    n=$(last "$out")
  fi
  out=$(run --only $1 "${va[@]}" --accept $n); echo "$C/$O $1 ${v} accepted $n"
}
step back || exit 1
for v in left front_left back_left; do
  run --status | grep -q "^  sides *done" && break
  step sides $v || exit 1
done
run --only sides | tail -1
echo "VIEWS_DONE $C/$O"
