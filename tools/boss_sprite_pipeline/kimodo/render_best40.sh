#!/bin/bash
# Render every clip in the best-40 demon blend to frames, then to mp4s. Unattended.
#
#   render_best40.sh
#
# anim_video.py loops over every action in one scene load, so the 55 MB rig is loaded once for
# all 40 clips. Local measured rate is ~16.6 s per output frame (two views per frame), 20 frames
# per clip at STEP 6 - so roughly 3.5-4 hours for the set. Nothing here needs a pod.
#
# The blend is generated/bosses/demon/animate_best40/animated.blend: 40 Kimodo clips retargeted
# onto rigged_jaw_hinge.glb with BIND_MATCH=1, ROOT_LOC=1 and IDLE_POSE set - the first demon
# bake without the 59 degree rest-pose error.
set -u
B="C:/Users/Douglas/Pixel-Realm-Combat-Heroes-Boss"
PY="$B/tools/boss_sprite_pipeline/.venv-bpy/Scripts/python.exe"
D="$B/generated/bosses/demon/animate_best40"
LOG="$D/render.log"

echo "=== render start $(date +%H:%M:%S)" > "$LOG"
"$PY" "$B/tools/boss_sprite_pipeline/rigfix/anim_video.py" \
    "$D/animated.blend" "$D/video" 720 6 >> "$LOG" 2>&1
echo "=== frames done $(date +%H:%M:%S)  $(find "$D/video" -name '*.png' | wc -l) png" >> "$LOG"

# mp4s: the system python has cv2, the bpy venv does not
python - "$D/video" <<'PY' >> "$LOG" 2>&1
import glob, os, sys
import cv2
root = os.path.abspath(sys.argv[1])
for d in sorted(p for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p)):
    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    if not pngs:
        continue
    imgs = [cv2.imread(p) for p in pngs]
    h, w = imgs[0].shape[:2]
    out = os.path.join(root, os.path.basename(d) + ".mp4")
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), 16.0, (w, h))
    for _ in range(2):                    # two loops, the clips are short
        for im in imgs:
            vw.write(im)
    vw.release()
    print("wrote", os.path.basename(out), len(imgs), "frames", flush=True)
print("MP4_OK")
PY
echo "=== ALL DONE $(date +%H:%M:%S)" >> "$LOG"
