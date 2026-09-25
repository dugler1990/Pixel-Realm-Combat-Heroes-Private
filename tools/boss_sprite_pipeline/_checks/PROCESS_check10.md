# CHECK 10 of 10 — incident reports (each yesterday failure, closed)

Independent reconstruction. Spine: one **incident** per failure. Root cause, exact fix, the gate that would have caught it, the command that is now allowed. Document only. Do not start pods.

Legal overlay on every incident: **no Hunyuan-Paint, no Hunyuan3D mesh** (2 / 2.1 / 2mini / 2mv). Paint = MV-Painter Apache-2.0. Mesh = TRELLIS.2 + isolated CuMesh `--skip-texture`. SSH `-tt -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp`. Do not commit `ppp`. Do not switch dirty `dev_tmxlevels`.

Checkpoint: six remesh GLBs already on this PC (bytes): paint 47,518,728; ink 47,387,500; sculpt 45,702,676; concept_art 47,201,284; illustration 47,323,308; 3d_render 44,977,296. 40GB pod **already stopped by the user**.

---

## INC-01 — Agent used Hunyuan because PLAN.md / hunyuan3d_cli.py still exist

**Broke:** Licence in EU/UK/South Korea. Covers weights **and Output**. `--geo_rotation 0` is the Hunyuan value.  
**Fix:** MV-Painter only (`--geo_rotation -90`). Do not download Hunyuan “to look.” `LEGAL_LIABILITY.md` also rejected TRELLIS v1 for NVIDIA export flags; this round still uses TRELLIS.2 as mesh factory and skips TRELLIS retexture. Do not “correct” legal by running Hunyuan. SF3D is historical (USD 1M cap; pancake `raw_desert_sf3d.glb` 546,156 B; outputs not grandfathered).  
**Gate:** If the command mentions Hunyuan, 2mv, or Hunyuan-Paint → stop.

## INC-02 — This PC / Linode treated as the GPU box

**Broke:** GTX 1050 4096 MiB. `nvidia-smi` “missing” because it is not on PATH (`...\NVSMI\nvidia-smi.exe`).  
**Fix:** 24GB-class mesh (A5000/3090). 40GB+ paint UNet. This PC: concept, transfer, UV, bake. Linode: Blender/unwrap only.  
**Gate:** `memory.total >= 20000` mesh; `>= 40000` paint.

## INC-03 — RunPod `container create: exit status 1`

**Broke:** Custom image / start command / volume on Community. $0 billed.  
**Fix:** Official PyTorch **devel** template. No custom start. No paint volume on a mesh pod. Third fail → Secure Cloud ~$0.25–$0.50/hr. A5000 Community ~$0.16/hr, 3090 ~$0.22/hr. Do not rent 16 GB Ada, A4000 16 GB, or a 12 GB 4070 Ti at ~$0.50.

## INC-04 — `pip install xformers` filled a 30GB overlay

**Broke:** Second torch. Disk full. Old fallback `flash-attn==2.7.3 || xformers` is the same trap.  
**Fix:** `ATTN_BACKEND=sdpa` `SPARSE_ATTN_BACKEND=flash_attn`. Prebuilt flash-attn **2.8.3.post1** wheel `--no-deps`. `trellis2_setup.sh` only. `_pod_install_trellis2.sh` is stale.

## INC-05 — Eigen / o_voxel compile, then reinstall after every death

**Broke:** Hours re-apt’ing a solved header. Dead NIC blamed as Eigen. Job `Killed` guessed as OOM.  
**Fix:** `libeigen3-dev` + `CPATH=/usr/include/eigen3` once. If `import cumesh, o_voxel, nvdiffrast, flash_attn` works, do not reinstall. On death: `free -h`, `dmesg`, full log. Measured remesh abort: RSS ~24 GB / 256 GB, ~170 GB free, dmesg empty — CuMesh native, **not** OOM. `_mesh_fix_eigen.py` re-apts even if the header exists — only if GATE-MESH-INSTALL fails on Eigen. `nvcc` on PATH via `CUDA_HOME=/usr/local/cuda`. Skip `_check_cuda_version` if Torch/nvcc disagree. `MAX_JOBS=2`. o-voxel from TRELLIS.2 tree, not PyPI. nvdiffrast v0.4.0, nvdiffrec `renderutils`, utils3d `9a4eb15e…`, FlexGEMM. `cd /tmp` before pip after `mv`. CRLF: `sed -i 's/\r$//'`. GitHub: wait, don’t double clone (zip/codeload OK).

## INC-06 — RMBG gated + DINOv3 AttributeError + token paste

**Broke:** `briaai/RMBG-2.0` gated; `rembg_model is None` then `.to(device)`; Transformers 5 `self.model.layer`; agent waited on a browser-less pod.  
**Fix:** `trellis2_patch.py` sets rembg None **and** guards `.to`. Skip BRIA. Dino `layer_root`. User accepts DINOv3 in a **PC browser**. Token on 24GB only. Agent does not paste token. No HF login on 40GB.

## INC-07 — Generate+remesh same process died; “needs 40GB”; manual remesh shipped

**Broke:** 3.4M-face soup (1,617,464 → 1,617,482 verts, 3,398,970 faces) died in BVH/finalize. Agent jumped toward 40GB. `trellis2_manual_remesh.py` wrote verts/faces, no UVs. `remesh=False` left holes (27 MB, ~391k). Res=256 crash-test blobbed the snout.  
**Fix:** Isolated `export_isolated_remesh` in `trellis2_run.py`: band=1, project=0, fill_holes 3e-2, simplify 1M (not 30k), `to_glb remesh=False`, `extension_webp=False`. UV still ~2 min. Success ~465k / 940k. Stay 24GB-class. 1024 OOM → retry 512 **on that card**, not “try 512 on 16 GB” as a SKU. `--skip-texture`. Save extract `.pt`, remesh new process. Manual remesh is crash-recovery only.

## INC-08 — `scp subsystem request failed` / 0-byte uploads / `_from_front` left in the name

**Broke:** Paint matcher is stem-exact string `replace("glb","png")`. Silent skip if PNG missing. 0-byte geesefs uploads.  
**Fix:** gzip+hex `_paint_put.py` after rewriting HOST (checked-in host is dead). `test -s`. Strip `_from_front`. SSH `-tt`, 6 s banner, key `ppp`, no `id_ed25519`. `groups: cannot find name for group ID 109` ignore. `nohup` + `pgrep` after disconnect.

## INC-09 — “Enough disk for ~15GB” → overlay ENOSPC

**Broke:** Wrong file. Infer loads `v29_25000.ckpt` **25.3 GB**. Overlay 30G, 14.5G free, expected 25327.64 MB, `os error 28`. One-sentence disk answers caused this.  
**Fix:** Never collapse overlay / volume / blob / VRAM into one sentence. 50 GB volume for blobs (not 40, not 80). Overlay for Blender/venv/`/opt/hf` pointers. `du -sh` blobs first (~36 GB; volume 38G used). Skip extra ~15 GB safetensors. 50 GB cannot also hold TRELLIS. One volume, one pod. geesefs `df` 1.0P is a lie. Mesh without volume: 60 GB **container** disk. A5000+30GB overlay no volume is the wrong disk.

## INC-10 — JSONDecodeError / 0-byte HF snapshots / re-download 36GB

**Broke:** geesefs materializes HF snapshot symlinks as 0-byte. Blobs were intact. `HF_TRANSFER=1` broke tiny README/config.  
**Fix:** Overlay `/opt/hf` pointers to volume blobs. Snapshot `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`. Write `refs/main`. `HF_HUB_ENABLE_HF_TRANSFER=0`. `json.loads(model_index.json)` + zero-byte walk. `_paint_rebuild_cache.py` is the pointer fix **then starts infer** — gates first. `huggingface_hub==0.25.2` with `diffusers==0.20.2`.

## INC-11 — Volume venv OSError / pip torch / numpy 2 / rembg import / wrong cwd

**Broke:** geesefs venv executables. Second torch. rembg wants numpy 2. `--no_rembg` still `import rembg` at module top. `FileNotFoundError` after `mv` cwd.  
**Fix:** `/opt/mvpaint-venv --system-site-packages`. Do not pip torch. numpy **1.26.3** scipy 1.13.0. Install rembg for import only. `cd /tmp`. Compile rasterizers if missing import. No xatlas on 40GB.

## INC-12 — Blender `--version` green, zero EXRs (40GB death #1)

**Broke:** geesefs blender path `../blender-4.2.9-linux-x64`; `chmod +x` fails; symlink 0-byte; binary-only copy 139 MB; OpenCV not in Blender’s Python; `render_temp` on volume; HDRI 0-byte; `shutil.copy` fails; Blender exits 0 after traceback. UNet already loaded (20–30 min).  
**Fix:** Extract **full** 4.2.4 LTS tree to `/opt/blender`. Name 4.2.9 is a lie. Persist `.tar.xz` on volume. pip OpenCV into `/opt/blender/4.2/python/bin/python3.11`. `OPENCV_IO_ENABLE_OPENEXR=1`. `/opt/render_temp`. `copyfile`. HDRI ~66 MB. cwd `.../MVPainter`. Infer `blender_path='/opt/blender/blender'`, require `depth/000.exr`, print `BLENDER_RC`. Never `_paint_fix_blender.py` / `_paint_blender_libs.py`. Never `rm -rf /opt/blender` mid-job. Overlay rebuild 5–10 min every new pod.

**False success:** empty `camera/` (created before glTF), empty `depth_png/` (created after Blender returns). Compositor `0000001.exr` → rename `000.exr`–`005.exr`.

## INC-13 — `debug_value=256` → loglevel None (40GB death #2)

**Broke:** Second full UNet load. `IMPORT_SCENE_OT_gltf.loglevel expected an int, not NoneType`. Operator `loglevel=0` overwritten by `set_debug_log()`. Patch script `CMDS_BLOCK_NOT_FOUND` / subset restart. Later restarts forgot **more**.  
**Fix:** ortho `debug_value=0`; **both** glTF calls `loglevel=0`; addon fallback `return logging.INFO`; grep live files. Replay **full** GATE-PAINT-BLENDER (`BLEND_CV2` + `GLTF_OK`) every time. `_patch_debug.py` and `_paint_fix_exr_restart.py` start infer — do not trust the restart. Keep one live `infer_multiview` once weights are in VRAM.

## INC-14 — OpenCV EXR None → UnboundLocalError after view 0

**Broke:** `depth/001.exr` never exists.  
**Fix:** env var + `if normal is None` must skip the uint16 line entirely; bpy fallback.

## INC-15 — Infer “succeeds” in 0s / watcher HAVE_6VIEW immediately / tqdm frozen / 15 min ETA

**Broke:** Leftover `*_6view.png` (even 0-byte) short-circuits. Watcher grepped script text. tqdm `\r` looks stuck at 1/7. Agent said GPU paint is 15 min.  
**Fix:** `rm` empty 6-views. Count `Path.rglob('*6view.png')` only (`SIXVIEW_COUNT`). GPU steps **~38 s**. VRAM load **20–30 min**. Pipeline warm ~5 min. Do not kill if RSS/VRAM climbing. `tail -5` can miss traceback (`TSTAT` on full log).

## INC-16 — Silent skip of a stem

**Broke:** JPG on disk, PNG missing; `replace("glb","png")` skips with no error.  
**Fix:** PNG copies same stem. `GATE_PAINT_PAIR`: GLB tens of MB, PNG >1 KB, six stems. Old demo in `_old/`.

## INC-17 — xatlas hour on A6000 / blender_low bake / infer_paint on 40GB

**Broke:** 1 h 10 min CPU, GPU idle, 1.3 GB RSS. Crushed mesh ~85k vs ~754k (later 53k vs 930k). Unwrap without 6-view is empty work.  
**Fix:** 40GB shuts after 6-views. Skip xatlas if UVs exist. Full `mesh.glb` / `blender.obj`. Bake local NVIDIA or small CUDA. After unwrap, bake ~1.4 GB VRAM / ~3 GB RAM.

## INC-18 — Agent told user to kill a pod they already stopped; invented runpodctl; waited to start paint; re-generated meshes

**Broke:** Process trust. Meshes were already local. Paint could have started per-stem.  
**Fix:** Confirm dashboard. No API key. First local remesh → start paint **after gates**. This round: skip mesh rental. Tell user at first real 6-view. Do not invent ETAs off the timing table.

## INC-19 — Stale helpers re-ran the bug

| Do not run | Why |
|------------|-----|
| `_paint_start_infer.py` | Volume HF_HOME; `test -x` geesefs 4.2.9 blender; no gates |
| `_paint_rebuild_cache.py` (whole) | Pointers OK then **starts infer** |
| `_patch_debug.py` | Addon patch then infer via `_pod_exec` |
| `_paint_fix_exr_restart.py` | Patch then infer; fragile CMDS_BLOCK |
| `_paint_fix_blender.py` | Binary-only 139 MB fake |
| `_paint_blender_libs.py` | 0-byte `.so` symlinks |
| `_mesh_keep_going.py` | Dead host; meshes local |
| `_paint_kick*.py` `_paint_now.py` `_paint_go.py` | Debris |
| `_pod_mvpaint_infer.py` | 24GB-safe paint dead end |
| `_bake_full.py` on 40GB | Wrong machine |

Durable: `trellis2_setup.sh` / `trellis2_run.py` / `trellis2_patch.py`, `_paint_gltf_fix.py` (smoke, no infer if you stop after print), `_paint_watch.py` file count, `_paint_put.py` after HOST rewrite, `_paint_cache_sense.py`, `_pod_mem_monitor.sh`. Still grep-proof. Still full gates. `_paint_pod.py` / `_mesh_pod.py` HOST is stale; flags/key are not.

## INC-20 — Volume on two pods / overlay died / clone was a symlink to /opt

**Fix:** One pod per volume. Overlay dies with pod — rebuild pointers/Blender/venv. Real MV-Painter tarball on volume. Parallel 24GB+40GB only on **separate** disks.

---

## Happy path after all incidents (this round)

1. GATE_LOCAL_MESH_OK (bytes in the header). Skip 24GB.  
2. User rents 40GB + existing 50 GB volume (not attached elsewhere).  
3. Overlay Blender + venv + `/opt/hf` pointers.  
4. Patch ortho/addon/infer. Grep proof. HDRI 66 MB. OpenCV in Blender Python.  
5. Upload six GLB+PNG. GATE_PAINT_PAIR. `rm` leftover 6-views.  
6. GATE_PAINT_BLENDER + GATE_PAINT_GLTF + EXR file + GATE_PAINT_HF. **Stop if any fail.**  
7. One `infer_multiview` `--geo_rotation -90 --no_rembg` `HF_HOME=/opt/hf`.  
8. First real `*_6view.png` → tell user bake can start locally. Same process finishes the rest.  
9. Pull 6-views. User stops 40GB. Local skip-xatlas full-mesh bake.

Seed 0 generate / seed 12 paint. Depth channel V. 6-view order 000,005,001,004,002,003.

---

## Check 10 contrast intent

Checks 2–9 organized by machine, gates, commands, helpers, or FAQ. This copy indexes **incidents** so a matching log line maps to a closed ticket, not a rediscovery.
