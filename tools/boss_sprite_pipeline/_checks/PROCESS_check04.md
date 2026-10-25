# CHECK 4 of 10 — chronological failure order

Independent reconstruction. Spine: what we did → what broke → the precise fix → the command next time. Happy-path last. Document only. Do not start pods.

SSH always: `ssh -tt -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp`. No `id_ed25519`. Do not commit `ppp`. Do not `git switch` dirty `dev_tmxlevels`. Pipeline: `Pixel-Realm-Combat-Heroes-Boss`. Hosts in `_mesh_pod.py` / `_paint_pod.py` die with the pod. Helpers sleep ~6 s for the RunPod banner. `scp` → gzip+hex after rewriting HOST.

Legal, unchanged through the whole chronology: **no Hunyuan-Paint and no Hunyuan3D mesh** (2 / 2.1 / 2mini / 2mv). Paint = MV-Painter Apache-2.0. Mesh = TRELLIS.2 + isolated CuMesh. `--geo_rotation -90` is TRELLIS; Hunyuan would have been 0 — we never run it.

This PC: GTX 1050 4096 MiB. `nvidia-smi` at `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe`. Linode is not a GPU substitute.

---

## 1. Concept stills (local, already done)

**Did:** Front-on round2 JPGs in `generated/bosses/demon/concept/round2/`.  
**Broke:** Dramatic 3/4 paintings pancake; SF3D only reads `front.png`; Hunyuan-2mv is licence-banned.  
**Fix:** Keyed front still, black/alpha. Copy JPG→PNG **same stem** (`round2_png/`) because paint matches `replace("glb","png")`. MV-Painter has no text prompt — punchier image to change look.  
**Next time:** PNG copies named exactly like the GLB stems. No rembg (inputs already have alpha).

Stems: `gpt2_front_paint` `gpt2_front_ink` `gpt2_front_sculpt` `nano2_concept_art` `nano2_2d_illustration` `nano2_3d_render`.

---

## 2. First cloud boxes (wrong SKU / wrong deploy)

**Did:** Tried custom images, start commands, volumes, a 16 GB Ada, Community hosts.  
**Broke:** `container create: exit status 1` ($0). 16 GB Ada / A4000 16 GB too small for official TRELLIS.2 1024. 12 GB 4070 Ti at ~$0.50 is the wrong price and SKU.  
**Fix:** Official RunPod **PyTorch devel** template. No custom start. Mesh: A5000/3090 24GB, **60 GB container** disk, **no** paint volume. Paint: 40GB+ and a **50 GB** volume (not 40, not 80). Secure Cloud on third Community fail (~$0.25–$0.50/hr). A5000 ~$0.16/hr, 3090 ~$0.22/hr.  
**Next time:** `memory.total >= 20000` mesh, `>= 40000` paint. `CUDA_HOME=/usr/local/cuda` on PATH.

---

## 3. TRELLIS install (solved, then re-solved)

**Did:** `trellis2_setup.sh`. Hit missing Eigen, xformers filling overlay, flash-attn source compile, CUDA version check, PyPI o-voxel, slow GitHub, CRLF bash, `FileNotFoundError` after `mv`, dead NIC.  
**Broke:** Hours. Agent re-apt’d Eigen after it was solved.  
**Fix (once):** `libeigen3-dev` + CPATH. **Never** unconstrained xformers. **Never** `flash-attn==2.7.3 || xformers`. Prebuilt wheel `flash_attn-2.8.3.post1+…` `--no-deps`. nvdiffrast **v0.4.0**, nvdiffrec `renderutils`, FlexGEMM, CuMesh, `cp -a $ROOT/o-voxel`, utils3d `9a4eb15e4021b67b12c460c7057d642626897ec8`. `MAX_JOBS=2`. `TORCH_CUDA_ARCH_LIST=8.6`. `HF_HUB_ENABLE_HF_TRANSFER=0`. `--system-site-packages`, do not pip torch. Skip `_check_cuda_version` if needed. `cd /tmp` before pip. `sed -i 's/\r$//'`. Wait on clone; zip/codeload OK.  
**Next time:** if `import cumesh, o_voxel, nvdiffrast, flash_attn` works, **do not reinstall**. `_pod_install_trellis2.sh` is stale. `_mesh_fix_eigen.py` re-apts even if the header exists.

---

## 4. RMBG + DINOv3 + token

**Did:** Generate hit gated `briaai/RMBG-2.0`, then `rembg_model is None` `.to(device)`, then Transformers 5 `self.model.layer`.  
**Fix:** `trellis2_patch.py` — rembg None **and** `.to` guard; dino `layer_root`. Skip BRIA. User accepts DINOv3 in a **PC browser**. Token on 24GB only. Agent does not paste token. `shaomq/MVPainter` is public — no HF login on 40GB.  
**Next time:** prove patch strings in i23d, texturing, and dino extractor before generate.

---

## 5. Generate 1024, remesh death, wrong OOM story

**Did:** `trellis2_run.py --skip-texture`, `1024_cascade`, seed 0, RGBA. Combined generate+remesh in one process.  
**Broke:** After hole-fill 1,617,464 → 1,617,482 verts, 3,398,970 faces, died in BVH/`Finalizing mesh`. Agent guessed OOM. Measure: RSS ~24 GB of **256 GB**, ~170 GB free, dmesg empty, GPU ~200 MB at remesh start — **not** OOM. `remesh=False` “worked” with holes (~391k, 27 MB). Manual remesh res=256: 235,695 verts, **no UVs**. “Remesh needs 40GB” was false. WebP GLBs unreadable on Windows.  
**Fix:** Isolated `export_isolated_remesh`: band=1, project=0, fill_holes 3e-2, simplify **1M not 30k**, `to_glb remesh=False texture_size=2048`, `extension_webp=False`. UV still ~2 min. Success ~465k / 940k. OOM on 1024 → retry 512 **on 24GB-class**, not “try 512 on 16 GB” as the plan. `faulthandler` on. `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. Monitor `_pod_mem_monitor.sh` / `trellis2.pid`. Extract `.pt`, remesh new process. **Do not ship `trellis2_manual_remesh.py` GLBs.**  
**Next time:** `--skip-texture` always. Hex-pull `<stem>_from_front.glb` → `variants/<stem>/mesh.glb`.

---

## 6. Meshes landed — this is the checkpoint

Bytes on disk (do not regenerate):

| Stem | mesh.glb bytes |
|------|----------------|
| gpt2_front_paint | 47,518,728 |
| gpt2_front_ink | 47,387,500 |
| gpt2_front_sculpt | 45,702,676 |
| nano2_concept_art | 47,201,284 |
| nano2_2d_illustration | 47,323,308 |
| nano2_3d_render | 44,977,296 |

Do not confuse with SF3D `raw_desert_sf3d.glb` (546,156), manual remesh 8,510,464 (no UVs), noremesh 27 MB (holes), TRELLIS textured GLBs.

Shut 24GB. Do not wait for all six to start paint **setup** (all six are already here).

---

## 7. First paint overlay ENOSPC + one-sentence disk lie

**Did:** “Enough for ~15 GB weights” on a 30 GB overlay.  
**Broke:** Infer loads `unet_w_controlnet/v29_25000.ckpt` **25.3 GB**. Expected 25327.64 MB, free 14480.68 MB, `ENOSPC`. Extra `unet_w_controlnet/*.safetensors` ~15 GB are **skipped**.  
**Fix:** Never one-sentence disk/VRAM/RAM. 50 GB volume for blobs (~36 GB; volume 38G used). Overlay for Blender/venv/`/opt/hf`. 50 GB cannot also hold TRELLIS (~20 GB). One volume, one pod. `df` 1.0P on geesefs is a lie. `du -sh` blobs **before** any HF download.

---

## 8. geesefs Blender / HF snapshots / venv

**Did:** chmod +x on volume blender; ln -s blender; venv on `/workspace`; HF snapshots on volume; `_paint_fix_blender.py` binary copy; `_paint_blender_libs.py` `.so` links.  
**Broke:** chmod does not stick. Symlinks → 0-byte or 139 MB blender without `4.2/` libs. HF snapshots 0-byte → `JSONDecodeError` while blobs OK. Volume venv `OSError`. Clone symlink to `/opt` died with old pod. `HF_TRANSFER=1` broke tiny files.  
**Fix:** Overlay full Blender **4.2.4** tree (`/opt/blender/blender`; 4.2.9 name is a lie). Tarball on volume `/workspace/pkgs/blender-*.tar.xz`. Overlay venv `/opt/mvpaint-venv`. Overlay `/opt/hf` pointers, snapshot `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`, `refs/main`. `HF_HOME=/opt/hf` `HF_HUB_ENABLE_HF_TRANSFER=0`. Real MV-Painter tarball on volume. Rebuild overlay 5–10 min every new pod. Never `rm -rf /opt/blender` mid-job. `_paint_rebuild_cache.py` then **starts infer** — rebuild half only until gates.

---

## 9. Paint venv pins

**Did:** New huggingface_hub vs diffusers 0.20.2; numpy 2 for rembg; `--no_rembg` still `import rembg`; pip torch; pip from deleted cwd.  
**Fix:** `diffusers==0.20.2` `transformers==4.40.1` `huggingface_hub==0.25.2` `pytorch-lightning==2.2.4` `OpenEXR==3.2.4` `numpy==1.26.3` `scipy==1.13.0` rembg installed not called. `--system-site-packages`, no torch pip. `cd /tmp`. Rasterizers compile if missing. No xatlas on this pod.

---

## 10. 40GB death #1 — Blender `--version` is not a render

**Did:** `test -x blender`, `--version`, then loaded 25.3 GB UNet, then ortho.  
**Broke:** Missing OpenCV in Blender Python (`import cv2` at module load). geesefs blender path. `render_temp` on volume. HDRI 0-byte. `shutil.copy` fail. Blender **exits 0** after Python traceback. Infer dies on missing `000.exr` **after** 20–30 min load. Empty `camera/` / `depth_png/` look like progress (`camera/` created **before** glTF).  
**Fix:** OpenCV into `$BPY=/opt/blender/4.2/python/bin/python3.11`. Infer `blender_path='/opt/blender/blender'` `--output_dir /opt/render_temp` require EXR print `BLENDER_RC`. `copyfile`. HDRI ~66 MB. cwd `/workspace/MV-Painter/MVPainter`. `OPENCV_IO_ENABLE_OPENEXR=1`. Success = `test -s .../depth/000.exr`. Compositor `0000001.exr` → `000.exr`. None-guard must not leave `normal_unit16` unset (`UnboundLocalError`, no `depth/001.exr`).

---

## 11. 40GB death #2 — debug_value=256 after path was “fixed”

**Did:** Patched blender path/OpenCV/`/opt/render_temp`, **dropped** `debug_value=256` / `set_debug_log`. Fragile replace printed `CMDS_BLOCK_NOT_FOUND`. Loaded UNet a second time. Later restarts forgot **more**.  
**Broke:** `set_debug_log()` returns None; execute() overwrites operator `loglevel=0`; `IMPORT_SCENE_OT_gltf.loglevel expected an int, not NoneType`; Blender exit 0; missing EXR.  
**Fix:** ortho `debug_value=0`; **both** glTF calls (`object_path` and `glb_path`) `loglevel=0`; addon fallback `return logging.INFO`. Grep live files. Replay **full** GATE-PAINT-BLENDER (`BLEND_CV2` + `GLTF_OK` on a real remesh) **every** restart. `_patch_debug.py` / `_paint_fix_exr_restart.py` start infer — do not. Keep one live `infer_multiview` once weights are in VRAM (killing it costs another 20–30 min).

---

## 12. Inputs silently skipped / watcher lied / ETA lied

**Did:** JPG next to GLB; leftover empty `*_6view.png`; watcher grepped the word `6view` out of a shell script; told user GPU paint is ~15 min; tqdm `\r` looked frozen at 1/7.  
**Fix:** PNG same stem; `test -s` both (GLB tens of MB, PNG >1 KB); `rm` leftover 6-views (`exists` short-circuits even 0-byte). Count `Path.rglob('*6view.png')` only. GPU 75-step **~38 s**. Volume→VRAM **20–30 min**. Warm pipeline ~5 min. Mid-load 6.5 GB RAM / 2 GB VRAM. Target ~27 GB. `tail -5` can miss traceback. GPU 0% + climbing RSS is not death.

Flags: `--geo_rotation -90 --no_rembg`. Seed 12, 75 steps, depth V, order `000,005,001,004,002,003`. `HF_HOME=/opt/hf`.

---

## 13. xatlas on A6000 / blender_low / infer_paint on 40GB

**Did:** Unwrap full remesh on the expensive box.  
**Broke:** **1 h 10 min** CPU, GPU idle, 1.3 GB RSS. `blender_low` / 30k crush (~85k vs ~754k; later ~53k vs ~930k). Unwrap without 6-view is empty.  
**Fix:** Shut 40GB after 6-views. Skip xatlas if UVs exist (`to_glb` already ~2 min UV). Full `mesh.glb`. Bake local NVIDIA or small CUDA (~1.4 GB VRAM). User stops the pod (no API key). Do not tell them to kill a pod they already stopped.

The 40GB box **was already stopped**. Overlay died. Volume blobs persist.

---

## Happy path (this round)

1. Confirm six GLB byte sizes above. Skip 24GB.  
2. User rents 40GB + existing 50 GB volume (not attached elsewhere).  
3. Overlay Blender + venv + `/opt/hf`. Pins in §9.  
4. Patch ortho/addon/infer. Grep: no `debug_value=256`; infer has `/opt/blender/blender` and `/opt/render_temp` and `BLENDER_RC`.  
5. Upload six GLB+PNG. `test -s`. `rm` leftover 6-views.  
6. `BLEND_CV2` + `GLTF_OK` + `depth/000.exr` + JSON `model_index.json`. **Stop if any fail.**  
7. One `infer_multiview`. First real `*_6view.png` → tell user local bake can start.  
8. Pull. User stops 40GB. Local skip-xatlas full-mesh bake.

40GB = UNet in VRAM. Not remesh. Not xatlas. Not “Blender is slow.” Not “weights on volume so 15 minutes.”
