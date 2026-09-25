# CHECK 9 of 10 — three isolated machine manuals

Independent reconstruction. Spine: **this PC**, **24GB mesh pod**, **40GB paint pod** as three complete manuals that must not leak work onto the wrong box. Document only. Do not start pods.

Legal (all three manuals): **no Hunyuan-Paint and no Hunyuan3D mesh** (2 / 2.1 / 2mini / 2mv). Paint = MV-Painter Apache-2.0. Mesh = TRELLIS.2 + isolated CuMesh. Do not commit `ppp`. Do not `git switch` dirty `dev_tmxlevels`. Pipeline repo is `Pixel-Realm-Combat-Heroes-Boss`.

SSH for both pods: `-tt -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp`, ConnectTimeout 25, ServerAliveInterval 30, sleep ~6 s for banner. Host strings in helpers are dead after a stop. `scp` fails → gzip+hex (`_paint_put.py` after rewriting HOST).

---

# Manual 1 — this Windows PC

## What this machine is

GTX 1050 **4096 MiB**. `nvidia-smi` is `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe` (not on PATH). This PC does concept stills, gzip+hex, watching SSH, UV, bake. It does **not** run TRELLIS, Hunyuan, or the MV-Painter UNet.

Linode is the same class of mistake: CPU unwrap/Blender only.

## Already done — do not regenerate

| Stem | `variants/<stem>/mesh.glb` bytes |
|------|----------------------------------|
| gpt2_front_paint | 47,518,728 |
| gpt2_front_ink | 47,387,500 |
| gpt2_front_sculpt | 45,702,676 |
| nano2_concept_art | 47,201,284 |
| nano2_2d_illustration | 47,323,308 |
| nano2_3d_render | 44,977,296 |

Kilobyte files = failed hex download. PNG copies live in `concept/round2_png/` (same stem as GLB). JPGs in `concept/round2/`.

Do not use: `mesh/raw_desert_sf3d.glb` (SF3D pancake), `mesh/demon_from_front_manual_remesh.glb` (no UVs), `mesh/demon_from_front_noremesh.glb` (holes), TRELLIS textured GLBs.

The 40GB paint pod was **already stopped by the user**. There is no RunPod API key. Do not invent `runpodctl`. Do not tell them to kill it.

## Local laws

- Never collapse disk/VRAM/RAM into one sentence. Infer loads `v29_25000.ckpt` (**25.3 GB**), not the extra ~15 GB safetensors.
- First real `*_6view.png` → tell the user local bake can start.
- Bake: skip xatlas if UVs exist (`to_glb` already unwrapped ~2 min). xatlas on full remesh on A6000 was **1 h 10 min**, GPU idle. Full mesh, not `blender_low` / 30k.
- MV-Painter has no text prompt. Punchier reference image to change look. New mesh only if the shape is wrong.
- Windows bash scripts: CRLF. `sed -i 's/\r$//'` on the pod if a `.sh` was edited here.

## Local bake (only after a real 6-view file exists)

1. `mesh.glb` (table above) + `*_6view.png`
2. Skip xatlas if UVs present
3. Full remesh / `blender.obj`, never `blender_low.obj`
4. Local NVIDIA or **small** CUDA — never the 40GB box

---

# Manual 2 — 24GB mesh pod (future character; skip this round)

## Rent

- A5000/3090 **24GB-class**. Fail 16 GB Ada, A4000 16 GB, 12 GB 4070 Ti, GTX 1050.
- Official RunPod **PyTorch devel** template (`nvcc` + `g++`). No custom image, no start command. Community `container create: exit status 1` → different region; Secure Cloud on third fail. Failed creates billed $0.
- **60 GB container disk**. Do not attach the 50 GB paint volume (~36 GB blobs already). One volume, one pod.
- `memory.total >= 20000` MiB. `export CUDA_HOME=/usr/local/cuda; PATH="$CUDA_HOME/bin:$PATH"`.
- Do not “try 512 on 16 GB” as the plan. Script may retry 512 after 1024 OOM on a **24GB** card only.

`df -h /workspace` may show **1.0P**. Ignore. Use bought size + `du`.

## Install once

`trellis2_setup.sh` only. Eigen `libeigen3-dev` + CPATH. **No unconstrained xformers.** No `flash-attn==2.7.3 || xformers`. Prebuilt flash-attn **2.8.3.post1** wheel `--no-deps`. nvdiffrast v0.4.0, nvdiffrec `renderutils`, FlexGEMM, CuMesh, o-voxel **copied from TRELLIS.2 tree**, utils3d `9a4eb15e4021b67b12c460c7057d642626897ec8`. `MAX_JOBS=2`. `TORCH_CUDA_ARCH_LIST=8.6`. `HF_HUB_ENABLE_HF_TRANSFER=0`. `--system-site-packages` venv — do not pip torch. Skip CUDA version check if Torch/nvcc disagree. `cd /tmp` before pip if you `mv` directories.

If `import cumesh, o_voxel, nvdiffrast, flash_attn` works: **do not reinstall.** Eigen is already solved — do not re-apt because a job died. Dead NIC is not Eigen. `Killed` → `free -h`, `dmesg`, full log. Remesh death was RSS ~24 GB of **256 GB**, empty dmesg — CuMesh native abort, **not** OOM.

Patch: `trellis2_patch.py` (RMBG None + `.to` guard; DINOv3 Transformers 5 `layer_root`). Do not download BRIA. DINOv3: user accepts in a **PC browser**; token on 24GB only. Agent does not paste the token. No HF login on 40GB (`shaomq/MVPainter` is public).

Prove patch: `pipeline.rembg_model = None` in i23d **and** texturing; `if self.rembg_model is not None:` in i23d; `layer_root = self.model if hasattr` in dino.

## Generate + isolated remesh

```bash
export HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
/workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_run.py \
  --image /workspace/in/<stem>.png --out-dir /workspace/out --name <stem> --skip-texture
```

`--skip-texture` mandatory (brown TRELLIS PBR). `Image.convert("RGBA")`, `seed=0`. `faulthandler` on. Isolated remesh is `export_isolated_remesh`: `band=1` `project_back=0` `fill_holes(3e-2)` `simplify(1_000_000)` `to_glb remesh=False texture_size=2048` `extension_webp=False`. Official `to_glb` still runs **xatlas UV ~2 min**. Successful remesh ~465k verts / 940k faces.

**Do not use `trellis2_manual_remesh.py` for paint GLB** (trimesh verts/faces, no UVs). Crash-test res=256 is not quality. `remesh=False` without isolated repair leaves holes (~391k verts, 27 MB). Combined generate+remesh died on 3.4M-face soup (1,617,464 → 1,617,482 verts hole-fill). Extract `.pt` then remesh in a **new process**. Monitor: `_pod_mem_monitor.sh` / `/workspace/trellis2.pid`.

Hex-pull `/workspace/out/<stem>_from_front.glb` → `variants/<stem>/mesh.glb` (strip `_from_front`). Shut 24GB. Start paint **setup** on 40GB without waiting for all six (this round all six are local).

---

# Manual 3 — 40GB paint pod (the next rental)

## Why 40GB exists

The UNet ckpt `unet_w_controlnet/v29_25000.ckpt` (**25.3 GB**) must sit in **VRAM**. A 24GB card OOMs. CPU-offload is a dead end. 40GB is **not** for remesh, xatlas, bake, or “Blender is slow.”

GPU 75-step paint is **~38 s**, not 15 min. Volume → VRAM is **20–30 min** (geesefs). Mid-load: 6.5 GB RAM / 2 GB VRAM. Target ~27 GB VRAM. Log line `Loading custom unet ...` has no tqdm. Pipeline 7/7 from warm `/opt/hf` ~5 min (tqdm `\r` looks stuck).

Buy **50 GB** volume (not 40, not 80). ~36 GB blobs, volume was 38G used. Overlay ~30 GB for Blender/venv/pointers. First overlay: expected **25327.64 MB**, free **14480.68 MB**, `ENOSPC`. 50 GB cannot also hold TRELLIS (~20 GB). Do not attach this volume to two pods.

A5000 24 GB **fails** GATE_PAINT_GPU (`memory >= 40000` MiB).

## Overlay vs volume (geesefs)

Volume: HF **blobs**, real `/workspace/MV-Painter` clone (codeload tarball; not a symlink to dead `/opt`), inputs, logs, blender `.tar.xz`.

Overlay `/opt`: full Blender tree **4.2.4 LTS** (`/opt/blender/blender` — the name `blender-4.2.9` is a lie), venv `/opt/mvpaint-venv`, HF pointers `/opt/hf` + `refs/main` snapshot `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`, `/opt/render_temp`.

geesefs: `chmod +x` does not stick; `ln -s` → 0-byte or blender-binary-only (**139 MB** fake success); HF snapshots 0-byte while blobs OK → `JSONDecodeError`; volume venv `OSError`. Never `_paint_fix_blender.py` (binary copy) or `_paint_blender_libs.py` (`.so` symlinks). Rebuild overlay 5–10 min every new pod. Never `rm -rf /opt/blender` / `pkill blender` while infer is why you rented.

`HF_HUB_ENABLE_HF_TRANSFER=0` (tiny files fail if 1). Skip linking `unet_w_controlnet/*.safetensors` (~15 GB). `du -sh` blobs **before** any Hugging Face download. `_paint_rebuild_cache.py` rebuilds pointers then **starts infer** — rebuild half only until gates are green.

## Venv

```bash
cd /tmp
python3 -m venv --system-site-packages /opt/mvpaint-venv
# pins: diffusers==0.20.2 transformers==4.40.1 huggingface_hub==0.25.2
# pytorch-lightning==2.2.4 OpenEXR==3.2.4 numpy==1.26.3 scipy==1.13.0 rembg
```

New hub breaks old diffusers → hub **0.25.2**. numpy 1.26.3, not 2. `import rembg` at module top even with `--no_rembg` — install rembg, do not call it. Compile `custom_rasterizer` + `differentiable_renderer` if they do not import. Do not pip torch. Do not install xatlas.

## Blender gate BEFORE UNet (the two 40GB deaths)

Death 1: geesefs blender / no OpenCV in Blender Python → zero EXRs after UNet load.  
Death 2: `/opt/blender` but `debug_value=256` → glTF `loglevel=None` → Blender exit 0 → missing `000.exr` after a **second** UNet load.

`blender --version` / `test -x` are not a render test. Official Blender **exits 0** after a Python traceback. Success = `depth/000.exr` non-zero. Empty `camera/` (created before glTF) and empty `depth_png/` (created after Blender returns) are **failure**.

Patches:

- ortho: `debug_value=256` → `0`; both glTF calls (`object_path` and `glb_path`) `loglevel=0`; `OPENCV_IO_ENABLE_OPENEXR=1` before `import cv2`; `if normal is None` must **not** still use unset `normal_unit16` (`UnboundLocalError` after view 0 → no `depth/001.exr`).
- addon `set_debug_log`: fallback `return logging.INFO` after 0–4. Operator `loglevel=0` is overwritten by `execute()`.
- infer: `blender_path='/opt/blender/blender'`; `--output_dir /opt/render_temp`; require EXR; print `BLENDER_RC`; `shutil.copyfile` not `copy`.
- OpenCV into `$BPY=/opt/blender/4.2/python/bin/python3.11` (`ensurepip` + `opencv-python-headless`).
- HDRI `scripts/overcast_soil_puresky_4k.exr` ~**66 MB**, not 0-byte.
- cwd `/workspace/MV-Painter/MVPainter`.
- Grep live files. `CMDS_BLOCK_NOT_FOUND` means the whitespace replace missed. Compositor `0000001.exr` → rename `000.exr`.

GATE: `BLEND_CV2` + `GLTF_OK` object count > 0 on a **real remesh GLB**. Then optional full ortho until `test -s .../depth/000.exr`. **No infer until both.** Replay the **full** gate every restart, not a subset.

## Inputs and infer

`infer_multiview` matches `replace("glb","png")` and **silently skips** missing PNG. 0-byte uploads happened. Leftover `*_6view.png` (even empty) → return immediately. `test -s` six pairs. Old demo in `_old/`. `rm` empty 6-views.

```bash
cd /workspace/MV-Painter/MVPainter
export HF_HOME=/opt/hf HF_HUB_ENABLE_HF_TRANSFER=0 PYTHONUNBUFFERED=1 OPENCV_IO_ENABLE_OPENEXR=1
nohup /opt/mvpaint-venv/bin/python -u infer_multiview.py \
  --input_glb_dir /workspace/mvpaint_in/glbs --input_img_dir /workspace/mvpaint_in/imgs \
  --output_dir /workspace/mvpaint_out --geo_rotation -90 --no_rembg \
  > /workspace/logs/infer.log 2>&1 &
```

`--geo_rotation -90` (TRELLIS). Hunyuan would be 0 — we do not run Hunyuan. Seed 12, 75 steps, depth channel V, 6-view order `000,005,001,004,002,003`. Load pipeline **once**. Killing infer to “fix Blender” costs another 20–30 min geesefs read.

Watch **files**: `Path.rglob('*6view.png')`. Grepping the shell script for `6view` is a false `HAVE_6VIEW`. `_paint_watch.py` uses `SIXVIEW_COUNT` / `TSTAT` / `DSTAT`. `tail -5` can miss a traceback. GPU 0% with RSS/VRAM climbing is not death. `groups: cannot find name for group ID 109` is noise. Confirm `pgrep` after SSH `Terminated`.

First real 6-view → tell the user. Pull files. **User** stops 40GB. Never `infer_paint` / bake here.

Stale: `_paint_start_infer.py` (volume `HF_HOME` + geesefs blender `test -x`). `_patch_debug.py` restarts infer. `_paint_kick*.py` debris. `_paint_pod.py` HOST dead.

---

# Cross-manual: never use 40GB for

CuMesh / TRELLIS 1024; Blender slowness on a 1M mesh (still gate Blender first); xatlas / bake / `infer_paint`; “weights on volume so 15 minutes.”

40GB = UNet fits in VRAM.

---

# Check 9 contrast intent

Previous copies mixed machines in one timeline. This copy **isolates** each box so an agent on 40GB cannot “helpfully” remesh, and an agent on this PC cannot “helpfully” load the UNet.
