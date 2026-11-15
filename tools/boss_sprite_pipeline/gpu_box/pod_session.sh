#!/usr/bin/env bash
# The whole pod session, unattended (POD_SESSION.md). Started by pod_go.sh; inputs already uploaded.
# Installs in parallel (skipped when already on the /workspace volume), then the jobs; each job writes
# /workspace/out/DONE_<job>; the end writes /workspace/out/SESSION_DONE. Logs: /workspace/logs/session_*.log.
set -u
W=/workspace; L=$W/logs; OUT=$W/out; mkdir -p $L $OUT
export HF_HOME=$W/hf HF_HUB_ENABLE_HF_TRANSFER=0 CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH
clean() { rm -rf /root/.cache/uv /root/.cache/pip; }
command -v uv >/dev/null || pip install -q uv

# --- installs, in parallel -------------------------------------------------------------------------------------
( $W/kimodo-venv/bin/python -c "import kimodo" 2>/dev/null || bash $W/kimodo_tools/install_kimodo.sh; clean
  echo KIMODO_READY ) > $L/session_install_kimodo.log 2>&1 &
( grep -q -a INSTALL_OK $W/setup.log 2>/dev/null || {
    CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')
    export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3 TORCH_CUDA_ARCH_LIST=$CC MAX_JOBS=4 \
      HF_HOME=$W/.cache/huggingface
    rm -f /tmp/flash_attn-*cp311*.whl
    bash $W/gpu_box/trellis2_setup.sh > $W/setup.log 2>&1; clean; }
  echo TRELLIS_READY ) > $L/session_install_trellis.log 2>&1 &
( [ -f $W/unirig/.installed ] || UNIRIG_INSTALL_ONLY=1 bash $W/gpu_box/unirig_pod.sh; clean
  echo UNIRIG_READY ) > $L/session_install_unirig.log 2>&1 &
( $W/bpy-venv/bin/python -c "import bpy, cv2" 2>/dev/null || {
    uv venv -q --python 3.11 $W/bpy-venv
    uv pip install -q --python $W/bpy-venv/bin/python "bpy==4.2.*" numpy scipy pillow opencv-python-headless; clean; }
  echo BPY_READY ) > $L/session_install_bpy.log 2>&1 &
ready() { grep -q "$1" $L/session_install_$2.log 2>/dev/null; }
waitfor() { until ready "$1" "$2"; do sleep 20; done; }

# --- jobs ---------------------------------------------------------------------------------------------------------
( waitfor KIMODO_READY kimodo                                     # Kimodo batch 2 (and any other cells files sent)
  cd $W/kimodo_tools && . $W/kimodo-venv/bin/activate && export HF_TOKEN=$(cat $W/hf/token)
  for c in cells_*.json; do python driver.py $c Kimodo-SOMA-RP-v1; done
  touch $OUT/DONE_kimodo ) > $L/session_kimodo.log 2>&1 &

( waitfor TRELLIS_READY trellis                                    # TRELLIS: one input folder per item
  mkdir -p $W/.cache/huggingface && cp $W/hf/token $W/.cache/huggingface/token
  for d in $W/trellis_jobs/*/; do
    name=$(basename $d); models=$(cat $d/models.txt)
    rm -rf $W/in $W/out_trellis_tmp; mkdir -p $W/in; cp $d/*.png $W/in/
    rm -f $W/out/*_from_front.glb
    bash $W/gpu_box/trellis_outfit.sh $models
    mkdir -p $OUT/trellis_$name && mv $W/out/*_from_front.glb $OUT/trellis_$name/ 2>/dev/null
  done
  touch $OUT/DONE_trellis ) > $L/session_trellis.log 2>&1 &

( waitfor UNIRIG_READY unirig                                      # UniRig on each TRELLIS result marked for it
  until [ -f $OUT/DONE_trellis ]; do sleep 30; done
  for f in $W/trellis_jobs/*/unirig_model.txt; do
    name=$(basename $(dirname $f)); m=$(cat $f)
    src=$OUT/trellis_$name/${m}_from_front.glb; [ -f $src ] || continue
    cp $src $W/unirig_in/mesh.glb && bash $W/gpu_box/unirig_pod.sh && mkdir -p $OUT/unirig_$name && \
      cp $W/unirig_out/rigged.glb $OUT/unirig_$name/
  done
  touch $OUT/DONE_unirig ) > $L/session_unirig.log 2>&1 &

( waitfor BPY_READY bpy                                            # retarget + render every clip set sent
  for s in $(ls $W/barbrt/bvh); do bash $W/barbrt/par_retarget.sh $s 6 > $L/par_$s.log 2>&1; done
  until [ -f $OUT/DONE_kimodo ]; do sleep 30; done                 # then the new Kimodo clips
  mkdir -p $W/barbrt/bvh/kimodo_new && find $W/runs -name '*.bvh' -newer $L/session_install_bpy.log \
    -exec cp {} $W/barbrt/bvh/kimodo_new/ \;
  bash $W/barbrt/par_retarget.sh kimodo_new 6 > $L/par_kimodo_new.log 2>&1
  touch $OUT/DONE_renders ) > $L/session_renders.log 2>&1 &

wait
touch $OUT/SESSION_DONE
echo SESSION_DONE
