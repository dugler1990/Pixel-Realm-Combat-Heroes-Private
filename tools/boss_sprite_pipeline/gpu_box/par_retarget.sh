#!/usr/bin/env bash
# Retarget + render many BVH clips onto the barb in parallel on a pod (CPU work: the pod's cores, not this PC).
#     bash par_retarget.sh <set name> [chunks]        BVHs in /workspace/barbrt/bvh/<set>/*.bvh
# Mirrors the repo layout retarget_bvh.py expects (REPO = two folders up from the script):
#   /workspace/barbrt/tools/boss_sprite_pipeline/{retarget_bvh.py, rigfix/anim_video.py, rigfix/make_mp4.py}
#   /workspace/barbrt/generated/bosses/barb/{rigfix/barb_final_nb.glb, gear_test/barb_roles.json}
# Splits the set into <chunks> folders, runs one retarget per chunk at once, then one render per chunk at once,
# then the mp4s. Out: /workspace/barbrt/video/<set>/<chunk>/<clip>.mp4 (+ frames). Prints PAR_DONE <set>.
set -uo pipefail
SET=$1; N=${2:-8}
R=/workspace/barbrt; PY=/workspace/bpy-venv/bin/python; T=$R/tools/boss_sprite_pipeline
W=$R/work/$SET; O=$R/out/$SET; V=$R/video/$SET
rm -rf "$W" "$O" "$V"; mkdir -p "$W" "$O" "$V" /workspace/logs
i=0
for f in "$R/bvh/$SET"/*.bvh; do d="$W/chunk_$((i % N))"; mkdir -p "$d"; ln -s "$f" "$d/"; i=$((i + 1)); done
echo "== $(date +%T) $SET: $i clips in $N chunks"
for d in "$W"/chunk_*; do
  c=$(basename "$d")
  (cd $R && $PY $T/retarget_bvh.py --source anunaki --target barb "$d" "$O/$c" > /workspace/logs/rt_${SET}_$c.log 2>&1) &
done
wait
echo "== $(date +%T) retargeted: $(ls "$O"/chunk_*/animated.blend 2>/dev/null | wc -l) chunks"
for d in "$O"/chunk_*; do
  c=$(basename "$d")
  (ANIM_ENGINE=${ANIM_ENGINE:-BLENDER_WORKBENCH} $PY $T/rigfix/anim_video.py "$d/animated.blend" "$V/$c" 240 3 > /workspace/logs/av_${SET}_$c.log 2>&1) &
done
wait
for d in "$V"/chunk_*; do $PY $T/rigfix/make_mp4.py "$d" 16 > /dev/null 2>&1; done
echo "== $(date +%T) videos: $(ls "$V"/chunk_*/*.mp4 2>/dev/null | wc -l)"
echo PAR_DONE $SET
