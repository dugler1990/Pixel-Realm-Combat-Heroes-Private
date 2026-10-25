#!/bin/bash
# Put BVH clips saved from the Kimodo demo UI onto the demon and into the browser viewer.
#
#   tools/boss_sprite_pipeline/viewer/wire_picks.sh [src] [label]
#
# In the demo UI (localhost:7870), Save Motion with format SOMA .bvh. **It downloads through the
# browser**, not to the pod - the Save Path box names the file, it does not write pod-side. So the
# clips land in your Downloads folder, which is the default src here.
#
#   src   a local directory (default: C:/Users/Douglas/Downloads), or "pod:/some/dir" to scp
#         them off the pod instead. Only .bvh files are taken.
#   label names the output folder and the glb.
#
# Nothing is rendered. retarget_bvh.py writes the actions into a .blend (~12 s/clip, the cost is
# Blender's per-frame mesh evaluation) and blend_to_glb.py converts them to one glb the viewer
# plays in real time. The EEVEE render is only ever needed for clips you are shipping as sprites.
#
# The retarget knobs are copied verbatim from animate_best40/run.json - the first demon bake
# without the 59 degree rest-pose error. Do not change them casually; four bad bakes came from
# settings carried over from a different character.
set -uo pipefail

SRC="${1:-/c/Users/Douglas/Downloads}"
LABEL="${2:-picks}"

B="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
KEY="/c/Users/Douglas/Pixel-Realm-Combat-Heroes-Private/ppp"
# ssh.runpod.io cannot forward ports or scp reliably; the direct TCP endpoint can.
POD_HOST="root@69.30.85.177"
POD_PORT=22152

PY="$B/tools/boss_sprite_pipeline/.venv-bpy/Scripts/python.exe"
RIG="$B/generated/bosses/demon/rig/jaw/rigged_jaw_hinge.glb"
ROLES="$B/generated/bosses/demon/rig/jaw/bone_roles.json"
IDLE="$B/generated/bosses/demon/idle/idle_pose.json"
STAGE="$B/generated/bosses/demon/picks/$LABEL/bvh"
OUT="$B/generated/bosses/demon/picks/$LABEL"

for f in "$PY" "$RIG" "$ROLES" "$IDLE"; do
    [ -e "$f" ] || { echo "MISSING: $f"; exit 1; }
done
mkdir -p "$STAGE"

if [ "${SRC#pod:}" != "$SRC" ]; then
    echo "=== pulling ${SRC#pod:} off the pod"
    scp -P $POD_PORT -i "$KEY" -o StrictHostKeyChecking=accept-new \
        "$POD_HOST:${SRC#pod:}/*.bvh" "$STAGE/" || { echo "no .bvh in ${SRC#pod:}"; exit 1; }
else
    echo "=== taking .bvh from $SRC"
    # Browser downloads collide as "name (1).bvh"; spaces and parens break action names in
    # Blender, so each file is renamed to a plain slug as it is staged.
    i=0
    find "$SRC" -maxdepth 1 -name '*.bvh' -print | while IFS= read -r f; do
        i=$((i + 1))
        slug=$(basename "$f" .bvh | tr -cd '[:alnum:]_-')
        [ -n "$slug" ] || slug="clip"
        cp "$f" "$STAGE/${slug}_${i}.bvh"
        echo "    $(basename "$f")  ->  ${slug}_${i}.bvh"
    done
fi
N=$(find "$STAGE" -name '*.bvh' | wc -l)
echo "    $N clips staged in $STAGE"
[ "$N" -gt 0 ] || { echo "nothing to do"; exit 1; }

echo "=== retargeting onto the demon  (~12 s/clip, no rendering)"
BIND_MATCH=1 ROOT_LOC=1 IDLE_POSE="$IDLE" CLAVICLE_DAMP=1.0 JAW_CLOSED=14.0 \
BIND_SKIP=bone_13 ARM_ELEV_CAP=35 SOURCE=soma RETARGET_MODE=rot \
"$PY" "$B/tools/boss_sprite_pipeline/retarget_bvh.py" "$RIG" "$ROLES" "$STAGE" "$OUT"
rc=$?
BLEND="$OUT/animated.blend"
if [ $rc -ne 0 ] || [ ! -f "$BLEND" ]; then
    echo "RETARGET_FAILED rc=$rc  (no $BLEND)"
    exit 1
fi

echo "=== exporting  (mesh once as base.glb, then one small glb per clip)"
"$PY" "$B/tools/boss_sprite_pipeline/viewer/export_split.py" "$BLEND" "$OUT" || {
    echo "EXPORT_FAILED"; exit 1; }

# The viewer reads this to know what clips exist; it is regenerated every run so a re-run with
# more clips just adds rows (hit "reload" in the panel rather than reloading the page).
python - "$OUT" <<'PY'
import glob, json, os, sys
o = sys.argv[1]
names = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(o, "clips", "*.glb")))
json.dump(names, open(os.path.join(o, "clips.json"), "w"))
print("clips.json ->", names)
PY

echo
echo "DONE - open:"
echo "  http://localhost:8777/tools/boss_sprite_pipeline/viewer/?base=/generated/bosses/demon/picks/$LABEL"
