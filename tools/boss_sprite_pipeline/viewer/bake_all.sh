#!/bin/bash
# Bake one staged BVH set onto several characters and lay the result out for the viewer.
#
#   bake_all.sh <source> <bvh_dir> <target>:<out_dir> [<target>:<out_dir> ...]
#   bake_all.sh --rebase <out_dir> [<out_dir> ...]      # re-export from an existing blend only
#
# ONE RULE, and it is the whole reason this script exists instead of a command line per run:
# **base.glb stays in the directory it was exported into.** An earlier version moved it up to a
# shared <parent>/_base.glb to avoid writing 60 MB per character. That is right for several
# bakes of ONE rig (every demon directory) and silently wrong for the four anunaki, which are
# four different UniRig outputs with 28, 40, 28 and 46 bones and different indices for the same
# role. index.html falls back to ../_base.glb when a directory has no base.glb, so all four
# loaded whichever body baked LAST; three of them then played hip rotation into finger bones.
# The variant that baked last looked perfect, which is what made it read as a retarget bug.
# check_layout.py asserts the invariant after every bake, so this cannot ship unnoticed again.
set -u
B=/c/Users/Douglas/Pixel-Realm-Combat-Heroes-Boss
PY="$B/tools/boss_sprite_pipeline/.venv-bpy/Scripts/python.exe"
R="$B/tools/boss_sprite_pipeline/retarget_bvh.py"
X="$B/tools/boss_sprite_pipeline/viewer/export_split.py"
C="$B/tools/boss_sprite_pipeline/viewer/check_layout.py"

split_and_check () {            # <out_dir>
  "$PY" "$X" "$1/animated.blend" "$1" 2>&1 | grep -aE "^BASE|^NO ARMATURE|SPLIT_DONE"
  python -I "$C" "$1" --write-clips-json 2>&1 | grep -aE "^base|^LAYOUT|MISSING"
}

if [ "${1:-}" = "--rebase" ]; then
  shift
  for out in "$@"; do
    echo "##### rebase $out"
    rm -f "$out/base.glb"
    split_and_check "$out"
  done
  echo BAKE_ALL_DONE
  exit 0
fi

SRC="$1"; BVH="$2"; shift 2
for spec in "$@"; do
  tgt="${spec%%:*}"; out="${spec#*:}"
  echo "##### $SRC -> $tgt   $out"
  rm -rf "$out"; mkdir -p "$out/bvh"; cp "$BVH"/*.bvh "$out/bvh/"
  "$PY" "$R" --source "$SRC" --target "$tgt" "$out/bvh" "$out" 2>&1 \
    | grep -aE "driving|WARN|expect|Traceback|Error" | tail -3
  split_and_check "$out"
done
echo BAKE_ALL_DONE
