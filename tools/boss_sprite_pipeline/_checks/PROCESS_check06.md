# CHECK 6 of 10 — helper scripts: which encode the fix, which will lie

Independent reconstruction. Spine: every `_*.py` / installer is a chapter. First-try sequence does **not** call stale helpers. Document only. Do not start pods.

Legal: no Hunyuan-Paint, no Hunyuan3D mesh (2 / 2.1 / 2mini / 2mv). Paint=MV-Painter Apache-2.0. Mesh=TRELLIS.2 + isolated CuMesh. SSH `-tt -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp`. Do not commit `ppp`. Do not switch dirty `dev_tmxlevels`. Meshes already local (exact bytes in §checkpoint). 40GB already stopped.

---

## Checkpoint (do not call mesh helpers)

| Stem | mesh.glb bytes |
|------|----------------|
| gpt2_front_paint | 47,518,728 |
| gpt2_front_ink | 47,387,500 |
| gpt2_front_sculpt | 45,702,676 |
| nano2_concept_art | 47,201,284 |
| nano2_2d_illustration | 47,323,308 |
| nano2_3d_render | 44,977,296 |

`_mesh_keep_going.py` restarts a dead host. **Do not run.**

---

## Canonical code (keep)

| File | What it encodes | Trap if misused |
|------|-----------------|-----------------|
| `gpu_box/trellis2_setup.sh` | Eigen+CPATH, no xformers, flash-attn **wheel** 2.8.3.post1 `--no-deps`, nvdiffrast v0.4.0, nvdiffrec `renderutils`, FlexGEMM, CuMesh, o-voxel copy from tree, utils3d `9a4eb15e…`, `MAX_JOBS=2`, `ARCH=8.6`, `hf_transfer=0`, `--system-site-packages` | Do not re-run if `import cumesh, o_voxel, nvdiffrast, flash_attn` already works |
| `gpu_box/trellis2_patch.py` | RMBG None + `.to` guard; DINOv3 `layer_root` | Pattern-not-found if upstream moved; do not download BRIA |
| `gpu_box/trellis2_run.py` | `--skip-texture`, isolated remesh band=1 project=0 simplify 1M `to_glb remesh=False` webp=False, 1024→512 OOM retry, faulthandler, expandable_segments, seed 0 RGBA | Combined generate+remesh used to die; isolation is inside this file |
| `gpu_box/trellis2_manual_remesh.py` | Geometry crash-recovery | **No UVs.** Not paint-ready. `CUDA_LAUNCH_BLOCKING=1` only here |
| `gpu_box/_pod_mem_monitor.sh` | RSS/GPU samples so OOM is measured | Needs `/workspace/trellis2.pid` |
| `LEGAL_LIABILITY.md` | Hunyuan EU/UK/KR ban; SF3D $1M; TRELLIS v1 NVIDIA export | **Not** the current mesh picker. Live mesh is TRELLIS.2. Do not “fix” by running Hunyuan |

---

## SSH / transfer

| File | Encodes | Lies |
|------|---------|------|
| `_mesh_pod.py` | `-tt` + `ppp` + 6 s wait | **HOST is dead** after stop |
| `_paint_pod.py` | same | HOST `luc0g32c1tmgou-…` is dead. Do not SSH “to check.” |
| `_paint_put.py` | gzip+hex, `stty -echo`, sha256 | Imports `_paint_pod.SSH` — rewrite HOST first. 0-byte uploads still possible → `test -s` |
| `_mesh_pull_glb.py` | gzip+hex download | Same dead HOST |

`scp` `subsystem request failed` is expected. `groups: cannot find name for group ID 109` ignore.

---

## Paint helpers that will recreate yesterday

| File | What it thinks it does | Why it lies |
|------|------------------------|-------------|
| `_paint_start_infer.py` | Kick infer | `HF_HOME=/workspace/.cache/huggingface` (0-byte snapshots). `test -x` geesefs `blender-4.2.9`. **No** debug_value / OpenCV-in-Blender / `/opt/render_temp` / EXR gate |
| `_paint_rebuild_cache.py` | Rebuild `/opt/hf` pointers (correct: snapshot `85a9cb12…`, skip extra 15GB safetensors, `HF_TRANSFER=0`) | **Then pkill + starts infer** |
| `_paint_fix_exr_restart.py` | OpenCV in Blender Python + CMDS_BLOCK `/opt/render_temp` (correct pieces) | Then starts infer. `CMDS_BLOCK_NOT_FOUND` if whitespace drifted |
| `_patch_debug.py` | `set_debug_log` fallback (required) | Then nohup infer via `_pod_exec` (possibly another dead host) |
| `_paint_gltf_fix.py` | `debug_value=0` + addon fallback + GLTF smoke | Smoke hard-codes `gpt2_front_ink.glb`. Prefer this over operator-only. Stop after `GLTF_OK` — do not chain a kick script |
| `_paint_fix_blender.py` | “Install blender” | Copies **binaries only** + `ln -sfn` → 139 MB fake / geesefs 0-byte. **Do not run** |
| `_paint_blender_libs.py` | Link `.so` next to overlay binary | geesefs 0-byte `.so`. **Do not run** |
| `_paint_pip_overlay.py` | venv on `/opt`, `cd /tmp`, numpy 1.26.3 | Does **not** install OpenCV into Blender’s Python. Hub must be `0.25.2` with diffusers 0.20.2. rembg still imported at module top |
| `_paint_cache_sense.py` | `du` blobs before download | Safe. Run this instead of `hf download` |
| `_paint_watch.py` | `SIXVIEW_COUNT` via `rglob('*6view.png')`, TSTAT, DSTAT | Safe watcher. 90 min deadline. GPU paint is **38 s**; VRAM load 20–30 min |
| `_paint_st.py` / grep-`6view` watchers | “HAVE_6VIEW” | Matches the **script text**. Lie |
| `_paint_kick*.py` `_paint_now.py` `_paint_go.py` `_paint_live.py` `_paint_pip2.py` | Session debris | Hosts, paths, half-fixes. Do not chain |
| `_pod_mvpaint_infer.py` | 24GB-safe paint | Dead end. UNet is 25.3 GB in VRAM. GATE_PAINT_GPU `>= 40000` |
| `_bake_full.py` `_unwrap_est.py` | xatlas / bake | **Wrong machine** on 40GB. 1 h 10 min CPU, GPU idle. Skip xatlas if UVs exist. Full mesh not `blender_low` |

---

## Mesh helpers

| File | Encodes | Lies |
|------|---------|------|
| `_mesh_fix_eigen.py` | `libeigen3-dev` + CPATH | Re-apts even if header exists. Eigen is already solved |
| `_mesh_fix_rembg_run.py` `_mesh_skip_rembg_restart.py` | RMBG None + `.to` guard | Prefer `trellis2_patch.py` once |
| `_mesh_token_check.py` | Token present | User logs in on 24GB. Agent does not paste token. Skip BRIA. No token on 40GB |
| `_mesh_zip_clone.py` `_mesh_retry_clone.py` | Clone without a second git | Do not double clone |
| `_mesh_keep_going.py` | Continue queue | Dead host. Meshes local |
| `_pod_install_trellis2.sh` | Old installer | `flash-attn \|\| xformers` disk killer. Use `trellis2_setup.sh` only |

---

## Facts every helper forgets (must still be in the agent’s head)

- geesefs: no chmod +x; ln -s → 0-byte; HF snapshot pointers 0-byte; `df` 1.0P; volume venv OSError; overlay dies with pod.
- Overlay ENOSPC numbers: expected **25327.64 MB**, free **14480.68 MB**. File is `v29_25000.ckpt` 25.3 GB, not “15 GB weights.” 50 GB volume. Not 40. Not 80.
- Two 40GB deaths: (1) geesefs blender / no cv2 in Blender Python (2) `debug_value=256` → loglevel None. Blender exit 0. Success = `depth/000.exr`. Empty `camera/` / `depth_png/` are not success. Both glTF call sites. UnboundLocalError if None-guard leaves `normal_unit16` unset.
- Silent PNG skip. 0-byte 6view skip. cwd `.../MVPainter`. `--geo_rotation -90 --no_rembg`. Seed 12 / 75 steps / depth V / order 000,005,001,004,002,003.
- Guessed remesh OOM was false. Isolated remesh is the deliverable. `--skip-texture`. WebP off.
- Community `container create: exit status 1`. 16 GB Ada wrong. Devel image. `CUDA_HOME`.
- This PC GTX 1050. Windows nvidia-smi path. No runpodctl.
- `CMDS_BLOCK_NOT_FOUND` → grep live file.
- HDRI ~66 MB. Snapshot `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`.

---

## First-try this round (no stale helpers)

1. Stat the six GLBs. Skip 24GB. Skip `_mesh_*`.  
2. User rents 40GB + existing volume (one pod). Update `_paint_pod.py` HOST or raw `ssh -tt`.  
3. Extract Blender tarball to `/opt/blender`. `_paint_pip_overlay.py` **install half only**. OpenCV into Blender Python by hand.  
4. Rebuild `/opt/hf` from `_paint_rebuild_cache.py` **without** the infer tail (or stop after `REBUILT` pointers). `du` first (`_paint_cache_sense.py`).  
5. `_paint_gltf_fix.py` smoke on `gpt2_front_ink.glb` **after** that GLB is uploaded. Grep `debug_value=256` gone.  
6. Patch infer path/`render_temp`/EXR required; grep live. Do not run `_paint_start_infer.py`.  
7. Upload six GLB+PNG via `_paint_put.py` (HOST rewritten). `test -s`. `rm` leftover 6-views.  
8. `BLEND_CV2` + `GLTF_OK` + `depth/000.exr` + JSON index. **Stop if fail.**  
9. Hand-start `infer_multiview` `HF_HOME=/opt/hf --geo_rotation -90 --no_rembg`.  
10. `_paint_watch.py` for file count. First real 6-view → tell user. User stops 40GB. Local bake, skip xatlas if UVs, full mesh.

40GB = UNet in VRAM.
