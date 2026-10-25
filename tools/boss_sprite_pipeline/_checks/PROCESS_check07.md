# CHECK 7 of 10 — STOP IF / THEN ONLY

Independent reconstruction. Every rule is fail-closed. Document only. Do not start pods.

Legal overlay: STOP IF the command or model is Hunyuan-Paint or Hunyuan3D (2 / 2.1 / 2mini / 2mv). THEN ONLY MV-Painter Apache-2.0 for paint, TRELLIS.2 + isolated CuMesh for mesh. `--geo_rotation -90`. Never 0 (that is Hunyuan).

STOP IF about to `git switch` dirty `dev_tmxlevels` or `git add ppp`. THEN ONLY work in `Pixel-Realm-Combat-Heroes-Boss`. Key `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp` with `ssh -tt`.

---

## This PC

STOP IF treating this box as Phase 1 GPU. THEN ONLY: GTX 1050 4096 MiB is local. nvidia-smi is `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe`. Linode = Blender/unwrap only.

STOP IF a `mesh.glb` is 0 bytes or kilobytes. THEN ONLY accept these bytes: paint 47518728, ink 47387500, sculpt 45702676, concept_art 47201284, illustration 47323308, 3d_render 44977296.

STOP IF about to re-run TRELLIS for these six. THEN ONLY skip 24GB this round.

STOP IF telling the user to kill the 40GB pod. THEN ONLY: they already stopped it. No RunPod API key. No `runpodctl`.

STOP IF collapsing disk/VRAM/RAM into one sentence. THEN ONLY name overlay size, volume size, blob `du`, and the file infer loads (`v29_25000.ckpt` **25.3 GB**, not the extra ~15 GB safetensors).

STOP IF inventing a 15 min GPU paint ETA. THEN ONLY: VRAM load 20–30 min; GPU steps **~38 s**; warm pipeline ~5 min; xatlas on A6000 **1 h 10 min**.

STOP IF `scp` loops. THEN ONLY gzip+hex after rewriting helper HOST. `test -s`. Strip `_from_front`.

---

## 24GB (future character only)

STOP IF GPU memory.total < 20000 MiB (16 GB Ada, A4000, 4070 Ti 12 GB, GTX 1050). THEN ONLY A5000/3090 24GB-class. Do not “try 512 on 16 GB” as the plan.

STOP IF deploy uses custom image, start command, or the paint volume. THEN ONLY official PyTorch **devel** template, 60 GB container disk. `container create: exit status 1` → other region; third fail Secure Cloud. Failed creates $0.

STOP IF `df -h /workspace` shows 1.0P and you trust it. THEN ONLY bought size + `du`.

STOP IF `import cumesh, o_voxel, nvdiffrast, flash_attn` already works and you reinstall. THEN ONLY generate. Eigen is solved — do not re-apt. Dead NIC is not Eigen. `_mesh_fix_eigen.py` re-apts anyway.

STOP IF `pip install xformers` or `flash-attn==2.7.3 || xformers`. THEN ONLY `trellis2_setup.sh`: prebuilt flash-attn 2.8.3.post1 `--no-deps`, nvdiffrast v0.4.0, nvdiffrec `renderutils`, o-voxel from TRELLIS.2 tree, utils3d `9a4eb15e…`, FlexGEMM, `MAX_JOBS=2`, `ARCH=8.6`, `hf_transfer=0`, `--system-site-packages`, no pip torch. `CUDA_HOME=/usr/local/cuda`. Skip CUDA version check if needed. `cd /tmp` after `mv`. CRLF `sed -i 's/\r$//'`. Do not double clone.

STOP IF job `Killed` and you guess OOM. THEN ONLY `free -h`, `dmesg`, full log. Remesh death: RSS ~24 GB / 256 GB, dmesg empty — CuMesh native abort. Isolate remesh. `_pod_mem_monitor.sh`.

STOP IF downloading BRIA/RMBG or pasting HF token in chat. THEN ONLY `trellis2_patch.py` (None + `.to` guard + dino `layer_root`). User accepts DINOv3 in a PC browser. Token on 24GB only. No HF login on 40GB.

STOP IF `--skip-texture` omitted, WebP on, simplify 30k, or `trellis2_manual_remesh.py` as the deliverable. THEN ONLY `export_isolated_remesh`: band=1 project=0 fill_holes 3e-2 simplify 1M `to_glb remesh=False` `extension_webp=False`. UV ~2 min. Success ~465k/940k. `remesh=False` without isolate = holes. res=256 = crash test. seed 0 RGBA.

STOP IF attaching the 50 GB paint volume to this pod or to two pods. THEN ONLY separate disks. 50 GB (~36 GB blobs) cannot hold TRELLIS too.

---

## 40GB paint

STOP IF memory.total < 40000 MiB or CPU-offload is the plan. THEN ONLY 40GB+ for UNet in VRAM. 24GB-safe infer is a dead end.

STOP IF blobs `du` is already tens of GB and you `huggingface-cli download`. THEN ONLY rebuild `/opt/hf` pointers. Snapshot `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`. Skip extra 15 GB safetensors. `HF_HUB_ENABLE_HF_TRANSFER=0`. `json.loads(model_index.json)` + zero-byte walk. Overlay ENOSPC was 25327.64 vs 14480.68 free. Buy 50 GB volume, not 40, not 80.

STOP IF Blender/venv/HF snapshots live on geesefs volume. THEN ONLY overlay `/opt/blender` (full 4.2.4 tree; 4.2.9 name is a lie), `/opt/mvpaint-venv`, `/opt/hf`, `/opt/render_temp`. geesefs: no chmod +x; ln -s → 0-byte or 139 MB binary-only; volume venv OSError. Never `_paint_fix_blender.py` / `_paint_blender_libs.py`. Overlay dies with pod — rebuild 5–10 min. Never `rm -rf /opt/blender` mid-job.

STOP IF pip torch, numpy 2, or skipping rembg package because of `--no_rembg`. THEN ONLY pins: diffusers 0.20.2, transformers 4.40.1, huggingface_hub **0.25.2**, numpy **1.26.3**, scipy 1.13.0, rembg installed for import. `cd /tmp`. No xatlas.

STOP IF `blender --version` / `test -x` is the render gate. THEN ONLY `BLEND_CV2` + `GLTF_OK` on a real remesh + `test -s depth/000.exr`. Blender exits 0 after traceback. Empty `camera/` / `depth_png/` are not success. HDRI ~66 MB.

STOP IF `debug_value=256` still in ortho, or only operator `loglevel=0`. THEN ONLY debug_value=0 + addon `return logging.INFO` + **both** glTF calls. execute() overwrites the operator. Grep live files. `CMDS_BLOCK_NOT_FOUND` → dump live file. None-guard must not use unset `normal_unit16`.

STOP IF infer path is `../blender-4.2.9-linux-x64` or `render_temp` on volume or `shutil.copy`. THEN ONLY `/opt/blender/blender`, `/opt/render_temp`, `copyfile`, require EXR, print `BLENDER_RC`. cwd `.../MVPainter`.

STOP IF loading UNet before those gates. THEN ONLY: two UNet loads + zero 6-views is yesterday. Full gate every restart, not a subset. Keep one live infer once weights are in VRAM.

STOP IF PNG missing, 0-byte upload, leftover `*_6view.png`, or grepping script text for `6view`. THEN ONLY `test -s` six pairs same stem; `rm` empty 6-views; count `rglob('*6view.png')`. Silent skip is `replace("glb","png")`.

STOP IF running `_paint_start_infer.py`, `_paint_kick*.py`, `_patch_debug.py` restart, or whole `_paint_rebuild_cache.py` including infer. THEN ONLY hand-start after gates: `HF_HOME=/opt/hf --geo_rotation -90 --no_rembg`. Watcher `_paint_watch.py` file count. HOST in `_paint_pod.py` is dead — rewrite. `_paint_put.py` uses that HOST.

STOP IF `infer_paint` / xatlas / bake / `blender_low` / 30k on this box. THEN ONLY shut after 6-views. Skip xatlas if UVs exist. Full `mesh.glb`. Local NVIDIA or small CUDA.

STOP IF killing infer to “fix Blender.” THEN ONLY another 20–30 min geesefs UNet read.

---

## Bake (local)

STOP IF unwrapping without a real `*_6view.png`. THEN ONLY wait for the file, then skip xatlas if UVs, full mesh, local.

STOP IF using SF3D `raw_desert_sf3d.glb`, `demon_from_front_manual_remesh.glb`, noremesh-with-holes, or TRELLIS textured GLB as the round2 checkpoint. THEN ONLY the six variant `mesh.glb` bytes above.

---

## First-try this round

STOP IF any gate token is missing. THEN ONLY: confirm six GLBs → overlay rebuild → grep patches → upload pairs → BLEND_CV2+GLTF_OK+EXR+HF JSON → one infer → tell user at first 6-view → user stops 40GB → local bake.

40GB = UNet in VRAM.
