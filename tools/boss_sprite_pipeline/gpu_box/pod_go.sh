#!/usr/bin/env bash
# Start a pod session and keep its outputs safe here (POD_SESSION.md). Git Bash, repo root of this worktree:
#     bash tools/boss_sprite_pipeline/gpu_box/pod_go.sh "<RunPod ssh line>"
# The HF token must be in the clipboard at the start. Uploads what pod_session.sh needs, starts it detached, then
# every 2 minutes pulls new outputs into <Boss>/generated/pod_sync/<date>/ until SESSION_DONE.
set -u
LINE="$1"
REPO=$(pwd); T=$REPO/tools/boss_sprite_pipeline; G=$T/gpu_box; PY=$REPO/Code/sprite_venv/Scripts/python.exe
BOSS=/c/Users/Douglas/Pixel-Realm-Combat-Heroes-Boss; BG=$BOSS/generated/bosses
K="C:/Users/Douglas/Pixel-Realm-Combat-Heroes-Private/ppp"
read H P < <($PY $G/pod.py address "$LINE" | awk '/^POD/{print $2, $3}')
[ -n "${H:-}" ] || { echo "no pod address"; exit 1; }
O="-i $K -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=30"
sshp() { timeout 300 ssh $O -p $P root@$H "$@"; }
put() { timeout 1800 scp $O -P $P -r "$@"; }
echo "pod $H:$P"

# HF token from the clipboard, BOM and CR/LF stripped, never printed
powershell -NoProfile -Command "(Get-Clipboard | Out-String).Trim()" | tr -d '\r\n\357\273\277' | \
  sshp "mkdir -p /workspace/hf && cat > /workspace/hf/token && chmod 600 /workspace/hf/token && grep -q '^hf_' /workspace/hf/token && echo TOKEN_OK"

sshp "mkdir -p /workspace/gpu_box /workspace/kimodo_tools /workspace/unirig_in /workspace/trellis_jobs \
  /workspace/barbrt/tools/boss_sprite_pipeline/rigfix /workspace/barbrt/generated/bosses/barb/rigfix \
  /workspace/barbrt/generated/bosses/barb/gear_test /workspace/barbrt/bvh"
put $G/trellis2_setup.sh $G/trellis2_patch.py $G/trellis2_run.py $G/trellis2_multiview.py $G/trellis2_mv_run.py \
  $G/trellis_outfit.sh $G/unirig_pod.sh $G/pod_session.sh root@$H:/workspace/gpu_box/
put $T/kimodo/install_kimodo.sh $T/kimodo/driver.py $T/kimodo/hand_gap_npz.py root@$H:/workspace/kimodo_tools/
for c in ${KIMODO_CELLS:-$T/kimodo/cells_barb_moves2.json}; do put $c root@$H:/workspace/kimodo_tools/; done
put $BOSS/tools/boss_sprite_pipeline/retarget_bvh.py root@$H:/workspace/barbrt/tools/boss_sprite_pipeline/
put $T/rigfix/anim_video.py $T/rigfix/make_mp4.py root@$H:/workspace/barbrt/tools/boss_sprite_pipeline/rigfix/
put $G/par_retarget.sh root@$H:/workspace/barbrt/
put $BG/barb/rigfix/barb_final_nb.glb root@$H:/workspace/barbrt/generated/bosses/barb/rigfix/
put $BG/barb/gear_test/barb_roles.json root@$H:/workspace/barbrt/generated/bosses/barb/gear_test/
for s in ${CLIP_SETS:-weapons moves1}; do put $BG/barb/anim_test/bvh_$s root@$H:/workspace/barbrt/bvh/$s; done

# TRELLIS jobs: <name> <outfit run folder> <models> [<model to rig with UniRig>]
while read name run models rig; do
  [ -z "$name" ] && continue
  sshp -n "mkdir -p /workspace/trellis_jobs/$name && echo '$models' | tr ',' ' ' > /workspace/trellis_jobs/$name/models.txt"
  [ -n "${rig:-}" ] && sshp -n "echo $rig > /workspace/trellis_jobs/$name/unirig_model.txt"
  put $run/gate/front.png $run/gate/back.png root@$H:/workspace/trellis_jobs/$name/
  ls $run/gate/side_*.png >/dev/null 2>&1 && put $run/gate/side_*.png root@$H:/workspace/trellis_jobs/$name/
done <<EOF
${TRELLIS_JOBS:-icewiz $BG/icewiz/outfits/base front_only,front_back,front_back_sides,eight_views eight_views
sword $BG/barb/outfits/sword_a front_back}
EOF

sshp "sed -i 's/\r\$//' /workspace/gpu_box/*.sh /workspace/kimodo_tools/*.sh /workspace/barbrt/*.sh; \
  nohup bash /workspace/gpu_box/pod_session.sh > /workspace/logs/session.log 2>&1 < /dev/null & echo STARTED"

# sync: pull every new output, every 2 minutes, until SESSION_DONE
D=$BOSS/generated/pod_sync/$(date +%Y%m%d); mkdir -p $D
while true; do
  list=$(sshp "cd /workspace && find out runs barbrt/video -type f \( -name '*.glb' -o -name '*.bvh' -o -name '*.npz' \
    -o -name '*.mp4' -o -name 'DONE_*' -o -name SESSION_DONE \) 2>/dev/null")
  new=$(for f in $list; do [ -f "$D/$f" ] || echo "$f"; done)
  if [ -n "$new" ]; then
    sshp "cd /workspace && tar -cf /workspace/sync.tar $(echo $new)" && \
      timeout 1800 scp $O -P $P root@$H:/workspace/sync.tar $D/ && tar -xf $D/sync.tar -C $D && rm $D/sync.tar
    echo "$(date +%T) pulled $(echo "$new" | wc -l) files: $(echo "$new" | grep -c DONE_) jobs done"
  fi
  [ -f $D/out/SESSION_DONE ] && { echo "SESSION_DONE: everything is in $D; stop the pod"; break; }
  sleep 120
done
