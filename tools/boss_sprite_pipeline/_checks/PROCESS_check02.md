# Boss 3D process — independent reconstruction (check 2)

**This file is a full rewrite from the session transcript + live scripts, not an edit of PROCESS.md.** After contrast, survivors merge into `PROCESS.md`.

**Point an agent at `PROCESS.md` (the merged canonical) before any RunPod command.** Do not improvise. Do not re-derive. If a failure looks new, search this encyclopedia first. Yesterday’s waste was repeating solved bugs in the same session.

---

## A. What is already finished — do not redo

Meshes for this round **exist on the PC**. Do not re-run TRELLIS. Do not remesh. Do not rent a 24GB box for these six.

| Stem | Local file | Size class |
|------|------------|------------|
| `gpt2_front_paint` | `generated/bosses/demon/variants/gpt2_front_paint/mesh.glb` | ~45–48 MB |
| `gpt2_front_ink` | `generated/bosses/demon/variants/gpt2_front_ink/mesh.glb` | ~45–48 MB |
| `gpt2_front_sculpt` | `generated/bosses/demon/variants/gpt2_front_sculpt/mesh.glb` | ~45–48 MB |
| `nano2_concept_art` | `generated/bosses/demon/variants/nano2_concept_art/mesh.glb` | ~45–48 MB |
| `nano2_2d_illustration` | `generated/bosses/demon/variants/nano2_2d_illustration/mesh.glb` | ~45–48 MB |
| `nano2_3d_render` | `generated/bosses/demon/variants/nano2_3d_render/mesh.glb` | ~45–48 MB |

Pod name before rename: `/workspace/out/<stem>_from_front.glb`. Paint matching is stem-exact — **strip `_from_front`**.

Concepts: `generated/bosses/demon/concept/round2/` (`*.jpg`). Paint wants PNG copies of the same stem.

**Paint produced zero `*_6view.png`.** The 40GB pod was **already stopped by the user**. Do not tell them to kill it. Next rental is paint-only after gates. Overlay died with that pod. Volume blobs (~36 GB) persist if that volume is reattached **to one pod only**.

---

## B. Legal (stop immediately)

| Tool | Status | Why |
|------|--------|-----|
| **Hunyuan-Paint** | **Forbidden** | Tencent Hunyuan 3D 2.1 Community License excludes EU / UK / South Korea. Covers weights and output. |
| **Hunyuan3D mesh** (2 / 2.1, including 2mv) | **Forbidden** | Same licence. `gpu_box/hunyuan3d_cli.py` is historical. `--geo_rotation 0` is the Hunyuan value — we never use it. |
| **MV-Painter** (`shaomq/MVPainter`) | **Use this** | Apache-2.0. Image + mesh only. No text prompt. |
| **TRELLIS.2** `microsoft/TRELLIS.2-4B` | **Mesh factory we used** | Microsoft weights MIT. Official export still pulls NVIDIA `nvdiffrast` / `nvdiffrec` (non-commercial flags exist). We skip TRELLIS retexture (`--skip-texture`) and paint with MV-Painter. Older `LEGAL_LIABILITY.md` rejected TRELLIS **v1** for ship; this round still used TRELLIS.2 for mesh. Do not “fix” that by switching to Hunyuan. |
| **Stable Fast 3D** | Historical | Stability Community License: free commercial under USD 1M revenue. Pancakes a single 3/4 still. Not this round. |

Do not switch dirty `dev_tmxlevels` (Private repo). Pipeline lives in `Pixel-Realm-Combat-Heroes-Boss`. Do not commit `ppp`.

---

## C. This Windows PC is not the GPU box

| Fact | Number / path |
|------|----------------|
| Local GPU | GTX 1050 **4096 MiB**. Too small for TRELLIS, Hunyuan, MV-Painter UNet. |
| `nvidia-smi` “not installed” | It is not on PATH. Call `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe`. |
| This PC is for | Concept stills, gzip+hex transfer, Blender/Fox, UV, bake, watching SSH. |
| Linode | CPU unwrap/Blender only. Useless for TRELLIS, MV-Painter generate, CUDA bake. Tiny 1–2 vCPU can be **slower** than the A6000 xatlas hour. |

---

## D. Session laws (process bugs, not software bugs)

1. **Do not re-solve a named issue in this file.** Log matches encyclopedia → apply that fix. Do not rediscover geesefs, Eigen, OpenCV-in-Blender, or glTF `loglevel`.
2. **Each restart replays the FULL gate, not a subset.** Yesterday: first infer used `test -x blender`; second patched path/OpenCV/`/opt/render_temp` and **dropped** `debug_value=256` / `set_debug_log`. Later restarts forgot **more**.
3. **`blender --version` and `test -x blender` are not a render test.** Official Blender **exits 0** after a Python traceback. Success = `depth/000.exr` exists and is non-zero.
4. **Never load the 24 GB UNet until GATE-PAINT-BLENDER prints `BLEND_CV2` and `GLTF_OK`.** Two UNet loads + zero 6-views emptied the 40GB rental.
5. **If compile/install already succeeded, resume the job.** Dead process → `free -h`, `dmesg`, full log. Do not clone TRELLIS again. Do not `pip install` CuMesh if `import cumesh` works. **Do not guess OOM.** Measured remesh death: RSS ~24 GB of **256 GB**, ~170 GB free, dmesg empty — CuMesh native abort, not the OOM killer.
6. **Do not wait for all six meshes to start paint.** First local `mesh.glb` → upload that pair (after paint gates). This round the six are already local — start paint, not mesh.
7. **Keep one `infer_multiview` process** once weights are in VRAM. Killing it to “fix Blender” costs another 20–30 min geesefs UNet read.
8. **Do not tell the user GPU paint is ~15 min.** Measured: **~38 seconds** for 75 steps once the UNet is in VRAM. Volume → VRAM is **20–30 min**. On disk ≠ in VRAM.
9. **Do not decimate to 30k / `blender_low.obj` for bake.** Full remesh `mesh.glb` / `blender.obj`. Measured: ~930k vs ~53k verts ≈ 8.5× verts, 17× faces.
10. **Do not run `infer_paint.py` or `bake_pipeline.py` on the 40GB pod.** xatlas on full remesh on A6000: **1 hour 10 minutes**, GPU idle, 1.3 GB RSS.
11. **Never collapse disk / VRAM / RAM into one sentence.** “Enough for ~15 GB weights” was the **wrong file**. Infer loads `unet_w_controlnet/v29_25000.ckpt` (**25.3 GB**). The extra `unet_w_controlnet/*.safetensors` are ~15 GB and we **skip** them. 30 GB overlay had 14.5 GB free → `ENOSPC`.
12. **Sense-check `du` on volume blobs before any Hugging Face download.** 0-byte snapshots ≠ missing blobs.
13. **Do not attach one network volume to two pods.** 24GB mesh and 40GB paint may run in parallel **only on separate disks**.
14. **50 GB volume with ~36–40 GB of MV-Painter blobs cannot also hold TRELLIS (~20 GB).**
15. **Tell the user the instant** a real `*_6view.png` exists (local bake can start) and the instant a **different** machine is needed. Do not invent ETAs that contradict the timing table.
16. **After any file patch, grep the live file.** Do not trust a Python `replace` that printed `CMDS_BLOCK_NOT_FOUND` or only patched a subset.
17. **Do not tell the user to stop/kill a pod they already stopped.** Confirm state. There is **no RunPod API key** on this PC — the agent cannot `runpodctl` stop. User uses the dashboard.
18. **Do not paste the Hugging Face token into chat.** User logs in on the 24GB box. `shaomq/MVPainter` is public — **no HF login on the 40GB box**.
19. **Do not blindly re-run old `_paint_kick*.py` / `_paint_start_infer.py`.** Several helpers are stale (wrong `HF_HOME`, still test geesefs blender, restart infer without gates). See §L.
20. **SSH key and flags do not change with the host.** Host strings in helpers are stale the moment the pod is destroyed.

---

## E. Cost split (never violate)

| Step | Work | Machine | Shut when |
|------|------|---------|-----------|
| 0 Concept | Front PNG/JPG, black/alpha | **Local** | — |
| 1a TRELLIS.2 `1024_cascade` | Image → mesh | **24GB-class** (A5000/3090). Toy 4/8/12 GB OOM. **16 GB Ada (RTX 2000) is the wrong first pod** for official 1024. | After GLB on PC |
| 1b Isolated CuMesh remesh | `band=1` `project=0` `simplify 1M` `to_glb remesh=False` `--skip-texture` | **Same 24GB pod** | After GLB on PC |
| 1c TRELLIS retexture | Skip | **Never** | — |
| 2a MV-Painter weights + 75-step generate | UNet must sit in VRAM | **40GB+** (24 GB card OOMs the ckpt). A6000 48 GB is fine. Do not CPU-offload as the plan. | After `*_6view.png` for the batch |
| 2b Blender 6-view ortho inside `infer_multiview` | Control depth/normal | Stuck on 40GB **only because the script calls it after weights load**. Smoke-test Blender **before** UNet. | — |
| 2c `infer_paint` / remesh_reduce / unwrap / bake | CPU + optional small CUDA | **Not the 40GB box** | — |
| 3 UV / xatlas / bake | CPU hour if xatlas reruns | **Local CPU**; bake on **local NVIDIA** or a **small** CUDA pod | — |

**40GB is for the MV-Painter UNet in VRAM.** Not remesh. Not xatlas. Not “Blender is slow on a 1M mesh.” Remesh problems were `1024_cascade` OOM on a **toy** GPU, or CuMesh abort in-process — stay 24GB-class.

**RunPod deploy:** Community host can refuse custom image / start command / volume with `container create: exit status 1` ($0 billed). Use the official **PyTorch devel** template (`runpod/pytorch:…-devel-…` so `nvcc`+`g++` exist). No custom start command. Do not attach the paint volume to a mesh pod. If Community fails three times, Secure Cloud (~$0.25–$0.50/hr). Mesh A5000 Community was ~$0.16/hr; 3090 ~$0.22/hr.

**Mesh disk if no volume:** 60 GB **container** disk. An A5000 with 30 GB overlay and no volume is the wrong **disk**, not the wrong GPU. TRELLIS+DINOv3 on 30 GB overlay scraped ~11 GB free **only if** xformers was never installed.

**Paint volume:** buy **50 GB** (not 40, not 80 as the “final” guess). Holds ~36 GB blobs. Overlay stays ~30 GB for Blender/venv/pointers.

---

## F. Timing truth (measured — quote these)

| Event | Time | Notes |
|-------|------|--------|
| TRELLIS `1024_cascade` | minutes–tens of minutes | 24GB; GPU ~3 GB during generate. OOM → retry `512`. Stay on 24GB-class. |
| Isolated CuMesh remesh + `to_glb remesh=False` | minutes | Official `to_glb` still runs **xatlas UV ~2 min** even with remesh=False. Successful remesh ~**465k verts / 940k faces**. |
| Hole-fill on raw extract then death | — | 1,617,464 → 1,617,482 verts (+18), 3,398,970 faces; died in BVH/`Finalizing mesh`. RSS ~24 GB / 256 GB; GPU ~200 MB at remesh start; 300+ threads → 1. **Not OOM.** |
| `remesh=False` without isolated repair | — | ~391k verts, 27 MB, **holes left**. Do not ship this. |
| Manual remesh crash-test res=256 | seconds | 235,695 verts, 26 open edges, **no UVs**. Not quality. Not paint-ready. |
| TRELLIS retexture | skip | Brown PBR |
| MV-Painter pipeline 7/7 from warm `/opt/hf` | ~5 min | First component looks stuck (tqdm `\r`) |
| Custom UNet ckpt volume → VRAM (geesefs) | **~20–30 min** | Local SSD: a couple of minutes. Mid-load snapshot: **6.5 GB RAM / 2 GB VRAM**. Target climb ~**27 GB** VRAM. Log line `Loading custom unet ...` has **no tqdm**. |
| GPU 75-step paint | **~38 s** | Not 15 min |
| Blender ortho, **small** mesh | **~30 s** | Previous successful demon |
| Blender ortho, **~1M remesh ~47 MB** | many minutes | Plus died on glTF until `debug_value` patched |
| Overlay Blender/venv/`/opt/hf` rebuild | 5–10 min | Every new 40GB pod |
| Bake `xatlas` on full remesh (A6000) | **1 h 10 min** CPU | GPU idle; then bake ~1.4 GB VRAM, ~3 GB RAM |
| Six meshes, one live process | 1× UNet load + 6× (Blender + ~38 s) | Do not reload UNet |
| Fox CPU render (old README) | ~10 min | Use GPU on a real NVIDIA if doing Fox |

Wrong story: “15 min on 40GB if weights on volume.” That mixed VRAM load with GPU steps and got the GPU number wrong.

---

## G. SSH / transfer (same every rental)

| Item | Value |
|------|--------|
| Key | `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp` |
| There is no | `~/.ssh/id_ed25519` on this Windows box. Do not change the login key. |
| Flags | `-tt` (RunPod PTY). `-o StrictHostKeyChecking=accept-new`. `ConnectTimeout=25`. `ServerAliveInterval=30`. |
| Banner | Helpers **sleep ~6 s** before sending commands. Do not “fix” by removing `-tt`. |
| Host | Changes every pod. Strings inside `_paint_pod.py` / `_mesh_pod.py` go stale. |
| `scp` | Often `subsystem request failed`. Use gzip+hex TTY (`_paint_put.py`, `_mesh_pull_glb.py`). After upload: `test -s` and size tens of MB, not 0. |
| Hex upload | `_paint_put.py` uses `stty -echo`, gzip compresslevel 6, sha256. 0-byte geesefs uploads happened. |
| `groups: cannot find name for group ID 109` | RunPod NSS noise. Ignore. |
| `nohup` then SSH `Terminated` | Confirm `pgrep` after disconnect. `nohup` + redirect. |
| Windows bash scripts | CRLF kills bash. `sed -i 's/\r$//'` after upload if a `.sh` was edited on Windows. |

Helpers: `_mesh_pod.py` (24GB), `_paint_pod.py` (40GB).

---

## H. Concept (local)

### Input

- Front-on still, subject looking at camera, black or already-cut alpha.
- This round: `generated/bosses/demon/concept/round2/*.jpg`
- Exact stems: `gpt2_front_paint.jpg` `gpt2_front_ink.jpg` `gpt2_front_sculpt.jpg` `nano2_concept_art.jpg` `nano2_2d_illustration.jpg` `nano2_3d_render.jpg`
- MV-Painter matches with **string** `base_name.replace("glb", "png")` — not a suffix replace. Copy JPGs to PNG **same stem** (`round2_png/` locally, pod `imgs/`).
- Dramatic 3/4 paintings pancake / hallucinate the back. That is a **mesh** problem, not paint. Keyed front still.
- MV-Painter has **no text prompt**. To change look: punchier **reference image** (eyes/teeth/light). Keep remesh. New mesh only if the **shape** is wrong.

### First try

Local files exist → PNG copies named exactly like the GLB stems → no rembg on either pod (TRELLIS rembg patched off; MV-Painter `--no_rembg`).

---

## I. Mesh — 24GB (already done this round; keep for the next character)

Code: `tools/boss_sprite_pipeline/gpu_box/trellis2_setup.sh`, `trellis2_run.py`, `trellis2_patch.py`, `trellis2_manual_remesh.py`.

### I.1 Rent / disk

- GPU: **24GB-class**. `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` → `memory.total >= 20000` MiB.
- Image: PyTorch **devel** so `nvcc` and `g++` exist. `export CUDA_HOME=/usr/local/cuda; export PATH="$CUDA_HOME/bin:$PATH"`. `nvcc` can be installed and still missing from PATH.
- Do **not** put TRELLIS on the 50 GB MV-Painter volume.
- Do not trust `df -h /workspace` on geesefs: it has shown **1.0P free**. Use `du` + bought size.

**GATE-MESH-BOX**

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
# memory.total must be >= 20000 MiB
which nvcc g++
df -h /
```

### I.2 Install once; resume if already done

```bash
test -f /usr/include/eigen3/Eigen/Dense || apt-get install -y libeigen3-dev
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3
export HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn
export TORCH_CUDA_ARCH_LIST=8.6
export MAX_JOBS=2
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
bash tools/boss_sprite_pipeline/gpu_box/trellis2_setup.sh
```

**If `import cumesh, o_voxel, nvdiffrast, flash_attn` already works: do not reinstall.**

Pins that already bit us:

| Pin | Value |
|-----|--------|
| nvdiffrast | **v0.4.0** |
| nvdiffrec | branch `renderutils` |
| o-voxel | copy from TRELLIS.2 tree, not PyPI |
| utils3d | commit `9a4eb15e4021b67b12c460c7057d642626897ec8` |
| FlexGEMM / CuMesh | compile from git via setup.sh |
| flash-attn | **prebuilt wheel** `flash_attn-2.8.3.post1+cu{cuda}torch{mm}cxx11abi{abi}-…whl` `pip install --no-deps`. Do not compile from source. |
| **Never** | `pip install xformers` unconstrained (second torch, fills 30 GB overlay) |
| **Never** | old fallback `flash-attn==2.7.3 \|\| pip install xformers` |
| MAX_JOBS | 2; use 1 only if compile RAM-dies |
| venv | `--system-site-packages` — do not pip torch |
| CUDA version check | `torch.utils.cpp_extension._check_cuda_version = lambda *a, **k: None` if Torch/nvcc disagree |
| Missing ninja / pybind11 | install those; resume compile, not full clone |
| GitHub clone slow | wait; do not start a second clone; zip/codeload is OK |
| Dead NIC | check the pod; do not reinstall Eigen |
| `FileNotFoundError` after `mv` | `cd /tmp` before pip |
| `o_voxel` Eigen | `libeigen3-dev` + CPATH. **Already solved. Do not re-debug.** |

TRELLIS.2 + DINOv3 are gated. Accept DINOv3 in a **PC browser**. Token on 24GB: `$HF_HOME/token`. Skip **BRIA / RMBG** — do not download `briaai/RMBG-2.0`. `trellis2_patch.py` sets rembg to None **and** guards `.to(device)`.

**GATE-MESH-INSTALL**

```bash
/workspace/vendor/trellis2-venv/bin/python -c "import cumesh, o_voxel, nvdiffrast, flash_attn, torch; print('GATE_MESH_INSTALL', torch.cuda.get_device_name(0))"
```

### I.3 Generate

```bash
export HF_HOME=/workspace/.cache/huggingface
export HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
/workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_run.py \
  --image /workspace/in/<stem>.png \
  --out-dir /workspace/out \
  --name <stem> \
  --skip-texture
```

- `Image.convert("RGBA")`, `seed=0`.
- `faulthandler` is on. `OPENCV_IO_ENABLE_OPENEXR=1` is set in the script.
- `--skip-texture` mandatory.
- Isolated remesh is **inside** `export_isolated_remesh` by default (generate, save `.pt` extract, free pipeline, remesh).
- OOM on `1024_cascade` → script retries `512`. Do not jump to 40GB.

If generate finishes but remesh dies: extract is ` /workspace/out/<stem>_raw_extract.pt`. Free VRAM. Run remesh in a **new process**. Combined generate+remesh in one process died on 3.4M-face soup.

RAM monitor: `gpu_box/_pod_mem_monitor.sh` reads `/workspace/trellis2.pid`. Measure, do not guess.

### I.4 Isolated remesh (the deliverable)

Locked parameters:

- `band=1`, `project_back=0`
- `cu.fill_holes(max_hole_perimeter=3e-2)`
- `cu.simplify(1_000_000)` — **not 30k**
- `o_voxel.postprocess.to_glb(..., remesh=False, decimation_target=1_000_000, texture_size=2048)`
- `glb.export(..., extension_webp=False)` (Windows 3D Viewer)

**Do not use `trellis2_manual_remesh.py` for the paint-ready GLB.** That script `trimesh.export`s vertices/faces only — no `to_glb` UVs/attrs. It is crash-recovery geometry only. `CUDA_LAUNCH_BLOCKING=1` is only in that script.

### I.5 Download

gzip+hex. Rename `<stem>_from_front.glb` → `variants/<stem>/mesh.glb`. Tens of MB, not 0 bytes.

**GATE-MESH-DONE (local):** each of the six `mesh.glb` files exists and is tens of MB. **This gate is already green.**

Shut 24GB. Do not wait on mesh to start paint **setup** on 40GB (gates first, then infer).

---

## J. Paint — 40GB (the next rental)

Goal: `infer_multiview.py` → `*_6view.png`. Then shut it. Bake locally.

Code on pod: `/workspace/MV-Painter/MVPainter/infer_multiview.py`  
Weights: `shaomq/MVPainter` public. Ckpt: `unet_w_controlnet/v29_25000.ckpt` (**25.3 GB**) must live in **VRAM**. Snapshot rev: `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`.

Flags always: `--geo_rotation -90` (TRELLIS) `--no_rembg`.

Pipeline once: `MVPainter_Pipeline.from_pretrained` float16 → ControlNet from unet → `hf_hub_download(.../v29_25000.ckpt)` → strip `unet` keys → `.to(cuda)`. Seed **12**. `--diffusion_steps` default 75. Depth EXR channel **V**. Combined 6-view order: `000,005,001,004,002,003`.

### J.1 Volume vs overlay

| On **network volume** `/workspace` | On **overlay** `/opt` |
|------------------------------------|------------------------|
| HF **blobs** `.../hub/models--shaomq--MVPainter/blobs` ~36 GB | Extracted **Blender** `/opt/blender` (full tree, 4.2.4 LTS) |
| Real git clone or **codeload tarball** `/workspace/MV-Painter` (not a symlink to a dead `/opt`) | **venv** `/opt/mvpaint-venv` |
| Input GLBs/PNGs, logs, blender **tarball** `/workspace/pkgs/blender-*.tar.xz` | HF **snapshot pointers** `/opt/hf` (symlinks into volume blobs) + `refs/main` |
| | `/opt/render_temp` EXR/PNG working files |

**geesefs facts (do not rediscover):**

- `chmod +x` on volume binaries does not stick.
- `ln -s` on volume → **0-byte files** or a **copy of only the blender binary** without `4.2/` libs. Listing may show a **139 MB** `blender` that cannot run the render script.
- HF snapshot layout uses symlinks; on geesefs they become **0-byte** `config.json` / `*.safetensors` → `JSONDecodeError` while **blobs are intact**.
- pip into `/workspace/mvpaint-venv` → `OSError` not permitted on executables.
- Do not re-download 36 GB because snapshots look empty. Rebuild pointers on overlay.
- Overlay dies with the pod. Rebuild overlay 5–10 min every new rental, then GATE-PAINT-BLENDER, **then** UNet.

First overlay death: 30 GB container, HF wanted **25327.64 MB**, free **14480.68 MB**, `ENOSPC`. Cache already ~13 GB. Leftover junk 337 MB. **Never one-sentence the disk.**

### J.2 Rebuild HF cache (no re-download)

See `_paint_rebuild_cache.py`. Exact steps:

```bash
export HF_HUB_ENABLE_HF_TRANSFER=0
mkdir -p /opt/hf/hub/models--shaomq--MVPainter/refs
ln -sfn /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs \
        /opt/hf/hub/models--shaomq--MVPainter/blobs
SNAP=/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d
rm -rf "$SNAP"
mkdir -p "$SNAP"
echo 85a9cb12b444a73ba922ac44fd198e8de12f8a9d > /opt/hf/hub/models--shaomq--MVPainter/refs/main
# For each HF tree file: if blob oid exists and size>0, symlink; skip unet_w_controlnet/*.safetensors (~15GB extra)
# FETCH only tiny missing json/README if blob missing
export HF_HOME=/opt/hf
```

If `HF_HUB_ENABLE_HF_TRANSFER=1`, tiny files fail (`.gitattributes`, README, `unet_pbr/config.json`). Keep it **0**.

**Sense-check before any download:** `du -sh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs` must already be tens of GB (volume was **38G used**).

**GATE-PAINT-HF**

```bash
export HF_HOME=/opt/hf HF_HUB_ENABLE_HF_TRANSFER=0
python3 - << 'PY'
from pathlib import Path
import json
snap = Path("/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d")
idx = snap / "model_index.json"
assert idx.exists() and idx.stat().st_size > 0, "empty or missing model_index.json"
json.loads(idx.read_text())
for p in snap.rglob("*"):
    if p.is_symlink() or p.is_file():
        real = p.resolve() if p.is_symlink() else p
        if real.is_file() and real.stat().st_size == 0:
            raise SystemExit(f"ZERO {p} -> {real}")
print("GATE_PAINT_HF ok")
PY
du -sh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs
```

### J.3 Overlay venv

```bash
cd /tmp
python3 -m venv --system-site-packages /opt/mvpaint-venv
# Do not pip torch. TORCH_CUDA_ARCH_LIST=8.6 on Ampere.
/opt/mvpaint-venv/bin/pip install \
  diffusers==0.20.2 transformers==4.40.1 huggingface_hub==0.25.2 \
  einops omegaconf opencv-python pytorch-lightning==2.2.4 \
  accelerate addict safetensors OpenEXR==3.2.4 \
  trimesh pygltflib kiui scikit-image imageio \
  jaxtyping lightning-utilities timm onnxruntime tqdm Pillow rembg \
  numpy==1.26.3 scipy==1.13.0
```

**Why those pins:** new `huggingface_hub` breaks `diffusers==0.20.2`. Pin hub **0.25.2**. Pin **numpy 1.26.3**. Do not upgrade numpy to 2 for rembg.

`infer_multiview.py` still **`import rembg` at module top** even with `--no_rembg`. Install rembg so import works. `--no_rembg` only skips calling it.

Compile `custom_rasterizer` and `differentiable_renderer` with cwd in those dirs; skip CUDA version check if needed. Need `ninja` + `pybind11`. If they already `import` in the venv, do not recompile.

Do not install `xatlas` on this pod.

### J.4 Overlay Blender 4.2.x

We used **4.2.4 LTS**. Upstream hard-codes `../blender-4.2.9-linux-x64/blender` — that name is a lie. Point infer at `/opt/blender/blender`. Do not `ln -sfn /opt/blender` onto the volume.

Save tarball on volume: `/workspace/pkgs/blender-*.tar.xz`.

Never `rm -rf /opt/blender` or `pkill blender` while infer is why you rented the box.

```bash
chmod +x /opt/blender/blender
/opt/blender/blender --version   # necessary, NOT sufficient
BPY=/opt/blender/4.2/python/bin/python3.11
$BPY -m ensurepip --upgrade || true
$BPY -m pip install opencv-python-headless
OPENCV_IO_ENABLE_OPENEXR=1 $BPY -c "import cv2; print('BLEND_CV2', cv2.__version__)"
/opt/blender/blender --background --python-expr "import cv2; print('BLEND_CV2', cv2.__version__)"
```

`blender_render_ortho.py` does `import cv2` at module load. Missing cv2 → zero files.

HDRI must be non-zero: `scripts/overcast_soil_puresky_4k.exr` (**~66 MB**). 0-byte geesefs HDRI → bad lighting.

### J.5 Blender ortho — the 40GB money pit

`infer_multiview` always runs Blender, then reads `/opt/render_temp/<uid>/depth/000.exr`. Missing EXR dies **after** the UNet is loaded.

#### Must-patch before any infer

In `scripts/blender_render_ortho.py`:

1. `bpy.app.debug_value=256` → **`bpy.app.debug_value=0`**.
   - 256 makes Blender 4.2 `io_scene_gltf2.set_debug_log()` return **None**.
   - Importer does `self.loglevel = set_debug_log()` and **overwrites** `loglevel=0` on the operator.
   - Crash: `IMPORT_SCENE_OT_gltf.loglevel expected an int type, not NoneType`.
   - Blender still **exits 0**.
2. Both glTF imports: `filepath=object_path` **and** `filepath=glb_path` need `loglevel=0`. Operator arg alone is **not** enough — still patch addon + `debug_value=0`.
3. `OPENCV_IO_ENABLE_OPENEXR=1` before `import cv2`.
4. Guard `if normal is None` before `(normal * 65535)` (`EXR_READ_FAIL`). Fallback: load via `bpy.data.images`.

In `/opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py` `set_debug_log`: after the 0–4 branches, **`return logging.INFO`**.

Patch `infer_multiview.py`:

- `blender_path = '/opt/blender/blender'`
- `--output_dir /opt/render_temp`
- all `render_temp` reads → `/opt/render_temp`
- after subprocess: print `BLENDER_RC`; **require** `depth/000.exr`; RC is not enough
- `shutil.copy` of exported obj can fail on geesefs → `shutil.copyfile`

**Grep proof after patch:** no `debug_value=256`; `infer_multiview.py` contains `/opt/blender/blender` and `/opt/render_temp`. Fragile whitespace replace printed `CMDS_BLOCK_NOT_FOUND` yesterday.

#### GATE-PAINT-BLENDER (mandatory; before UNet)

```bash
mkdir -p /opt/render_temp
/opt/blender/blender --background --python-expr "import cv2; print('BLEND_CV2', cv2.__version__)"
/opt/blender/blender --background -Y --python-expr \
  "import bpy; bpy.app.debug_value=0; bpy.ops.import_scene.gltf(filepath='/workspace/mvpaint_in/glbs/gpt2_front_ink.glb', merge_vertices=True, loglevel=0); print('GLTF_OK', len(bpy.data.objects))"
```

`GLTF_OK` with object count > 0. **If this fails, do not start infer_multiview.**

Optional stronger gate (still cheaper than a 25 min UNet load):

```bash
cd /workspace/MV-Painter/MVPainter
OPENCV_IO_ENABLE_OPENEXR=1 /opt/blender/blender --background -Y \
  --python scripts/blender_render_ortho.py -- \
  --object_path /workspace/mvpaint_in/glbs/gpt2_front_ink.glb \
  --geo_rotation -90 --output_dir /opt/render_temp
test -s /opt/render_temp/gpt2_front_ink/depth/000.exr
```

Compositor may write `0000001.exr` then rename to `000.exr`. Infer wants `000.exr` … `005.exr`.

**False success directories:** `save_images` creates `camera/` **before** glTF import. Infer creates `depth_png/` **after** Blender returns. Empty `camera/` or empty `depth_png/` is **failure**. Success is non-empty `depth/000.exr` (usually also `normal/000.png`).

`cd` for infer **must** be `/workspace/MV-Painter/MVPainter` so `scripts/blender_render_ortho.py` resolves.

### J.6 Inputs

```text
/workspace/mvpaint_in/glbs/<stem>.glb
/workspace/mvpaint_in/imgs/<stem>.png
```

Same stem. PNG not JPG. Missing PNG → **silent skip** (no error). 0-byte uploads → skip. `test -s` both. Six pairs. Old demo GLB in `_old/`.

If a **0-byte** (or leftover) `*_6view.png` exists in `mvpaint_out`, infer **returns immediately** for that stem (`if os.path.exists(...6view.png): return`). Delete empty 6-views first.

### J.7 Run infer (only after GATE-PAINT-HF + GATE-PAINT-BLENDER)

```bash
cd /workspace/MV-Painter/MVPainter
export HF_HOME=/opt/hf
export HF_HUB_ENABLE_HF_TRANSFER=0
export PYTHONUNBUFFERED=1
export OPENCV_IO_ENABLE_OPENEXR=1
nohup /opt/mvpaint-venv/bin/python -u infer_multiview.py \
  --input_glb_dir /workspace/mvpaint_in/glbs \
  --input_img_dir /workspace/mvpaint_in/imgs \
  --output_dir /workspace/mvpaint_out \
  --geo_rotation -90 \
  --no_rembg \
  > /workspace/logs/infer.log 2>&1 &
```

Load pipeline **once**, loop all meshes.

Watch **files**, not script text:

```bash
python3 -c "import pathlib; print(len(list(pathlib.Path('/workspace/mvpaint_out').rglob('*6view.png'))))"
```

Grep of the shell script for `6view` is a **false `HAVE_6VIEW`**. `_paint_watch.py` uses `SIXVIEW_COUNT` + `TSTAT` (traceback in full log) + `DSTAT` (`INFER_MULTIVIEW_DONE`). `tail -5` can miss a traceback earlier. tqdm `\r` looks frozen at `1/7`. RSS/VRAM climbing = still loading. GPU 0% with process alive is not death.

**First real `*_6view.png`:** tell the user they can start **local CPU bake** for that stem. Remaining stems stay on the same process.

Pull 6-views. Shut 40GB. Never bake here.

---

## K. Local UV / bake

| Work | Machine |
|------|---------|
| Extra Blender camera/ortho if paint did not produce usable controls | Local CPU |
| UV unwrap | Local CPU. **Skip xatlas if the mesh already has UVs** (`to_glb` already unwrapped ~2 min). Re-running xatlas on full remesh ≈ **1 h 10 min** and is what wasted the A6000. |
| `bake_pipeline` | Local NVIDIA, else a **small** CUDA pod. Never 40GB. After unwrap, bake was ~1.4 GB VRAM / ~3 GB RAM. |
| Mesh for bake | Local remesh `mesh.glb` is source of truth. Infer may copy `blender.obj` after `remove_doubles`. **Not** `blender_low.obj`. **Not** 30k. |

Need `mesh.glb` **and** `*_6view.png`. Unwrap without 6-views is empty work.

---

## L. Stale helpers that will recreate yesterday

Do **not** treat every `_paint_*.py` / `_mesh_*.py` in the Boss repo root as current.

| Script | Trap |
|--------|------|
| `_paint_start_infer.py` | `HF_HOME=/workspace/.cache/huggingface` (volume 0-byte snapshots). `test -x` geesefs `.../blender-4.2.9-linux-x64/blender`. No Blender gate. |
| `_patch_debug.py` | Patches addon then **immediately nohup infer** — skips GATE-PAINT-BLENDER / GATE-PAINT-HF. Uses `_pod_exec`. |
| `_paint_kick*.py`, `_paint_now.py`, `_paint_go.py` | Session debris; hosts stale; may skip gates. |
| `_paint_pod.py` `HOST=` | Stale the moment the pod died. Update host per rental; key/flags stay. |
| `README.md`, `gpu_box/RUNPOD.md`, `PLAN.md` | Historical (SF3D / Hunyuan). **PROCESS.md wins.** |
| `3D_GENERATION.md` | Pointer only. PROCESS.md wins. |

Durable helpers: `trellis2_setup.sh` / `trellis2_run.py` / `trellis2_patch.py`, `_paint_rebuild_cache.py`, `_paint_gltf_fix.py`, `_paint_fix_exr_restart.py`, `_paint_watch.py` (file count), `_paint_put.py`, `_paint_cache_sense.py`, `_pod_mem_monitor.sh`, `_mesh_fix_eigen.py`. Still **grep-proof** every patch; still run gates; do not start infer from a helper that skips them.

---

## M. Bug encyclopedia (search here first)

### M.1 Machines / ops

| Symptom | Cause | Fix |
|---------|--------|-----|
| GTX 1050 / 4 GB | Local PC | 24GB mesh; 40GB paint |
| `nvidia-smi` not found on Windows | Not on PATH | `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe` |
| Dirty `dev_tmxlevels` | Uncommitted Private work | Do not `git switch`. Boss worktree. |
| `ssh` without `-tt` | RunPod PTY | `-tt` + 6 s banner wait |
| `id_ed25519` missing | Key is `ppp` | `-i ...\ppp` |
| `scp` subsystem failed | RunPod proxy | gzip + hex TTY |
| Volume on two pods | geesefs lock | One pod per volume |
| Overlay `ENOSPC` | 25.3 GB ckpt on 30 GB overlay (14.5 GB free) | Blobs on volume; pointers on overlay |
| `df -h /workspace` shows 1.0P | geesefs fake capacity | Bought size + `du` |
| Paint volume full + TRELLIS | 50 GB can’t hold both | Separate disk/pod |
| Conflating paint ENOSPC with TRELLIS | Two disks | `df` + `du` before download |
| “Enough disk for ~15 GB” | Wrong file (skipped safetensors) | State overlay, volume, blob, **and** `v29_25000.ckpt` 25.3 GB |
| `container create: exit status 1` | Custom image / start / volume on Community | Official PyTorch devel template; no start command |
| 16 GB Ada first pod | Too small for official 1024 TRELLIS.2 | 24GB-class |
| A5000 + 30 GB overlay, no volume | Wrong disk | 60 GB container or a volume that is **not** 36 GB of paint |
| Pod GPU 0%, process alive, tqdm frozen | `\r` or geesefs read | VRAM/RSS; parse `\r` |
| Process dead, `tail -5` empty | Traceback earlier | Full log; `TSTAT` |
| `Killed` | Maybe OOM — **measure** | `free`, `dmesg`; remesh death was **not** OOM |
| Slow GitHub | Network | Wait; don’t double clone |
| Dead NIC | Pod | Check RunPod; don’t reinstall Eigen |
| `groups: cannot find name for group ID 109` | RunPod noise | Ignore |
| Watcher `HAVE_6VIEW` immediately | Matched the word in a script | Count files only |
| `nohup` then SSH `Terminated` | HUP | `pgrep` after disconnect |
| CRLF bash | Windows edit | `sed -i 's/\r$//'` |
| Cannot stop pod from agent | No API key | User dashboard. Do not invent `runpodctl`. Do not tell them to kill a stopped pod. |
| Host in helper wrong | Pod recycled | Edit HOST; keep key/flags |

### M.2 TRELLIS / CuMesh

| Symptom | Cause | Fix |
|---------|--------|-----|
| Compile no Eigen | Missing headers | `libeigen3-dev` + CPATH. Do not re-debug. |
| Second torch / disk full | `pip install xformers` | Don’t. Also delete `flash-attn \|\| xformers` fallback. |
| flash-attn compile forever | Building from source | Prebuilt wheel 2.8.3.post1 `--no-deps` |
| CUDA mismatch on `setup.py` | Torch vs nvcc | Skip `_check_cuda_version` |
| `nvcc` missing / not on PATH | Non-devel image or PATH | devel image; `CUDA_HOME=/usr/local/cuda` |
| RMBG gated / crash | `rembg_model` | Patch None + `.to` guard; skip BRIA; alpha inputs |
| DINOv3 AttributeError | Transformers 5 `self.model.layer` | `trellis2_patch.py` |
| DINOv3 gated download | No browser on pod | Accept on PC; token on 24GB only |
| `1024` OOM | VRAM | Retry `512`; stay 24GB-class |
| Generate+remesh die together | 3.4M-face soup in-process; CuMesh native abort | Isolated `export_isolated_remesh`; measure RAM |
| `--skip-texture` forgotten | Brown TRELLIS PBR | Always skip |
| `trellis2_manual_remesh.py` GLB has no UVs | trimesh.export only | Use `export_isolated_remesh` |
| `remesh=False` “works” with holes | Skipped repair | Isolated remesh of extract |
| Remesh 256 looks blobbed | Crash-test resolution | Official 1024 remesh of extract |
| WebP GLB unreadable on Windows | `extension_webp=True` | `False` |
| HF tiny file fail | `hf_transfer` | `HF_HUB_ENABLE_HF_TRANSFER=0` |
| HF token missing | New pod | User login on 24GB; agent does not paste |

### M.3 MV-Painter / Blender / EXR

| Symptom | Cause | Fix |
|---------|--------|-----|
| `JSONDecodeError` / empty snapshot | geesefs 0-byte HF pointers | Rebuild `/opt/hf` → blobs; write `refs/main` |
| pip `OSError` in venv | venv on geesefs | `/opt/mvpaint-venv` |
| `chmod +x` blender fails | geesefs | Overlay `/opt/blender` |
| Blender `--version` works, render writes nothing | Binary-only copy (139 MB) or script crash | Overlay full tree + GATE-PAINT-BLENDER |
| `import cv2` in Blender dies | OpenCV not in Blender Python | pip into `$BPY` |
| `depth/000.exr` missing, `BLENDER_RC 0` | glTF `loglevel=None` from `debug_value=256` | `debug_value=0` + `set_debug_log` fallback |
| `loglevel=0` on operator still crashes | execute() overwrites via `set_debug_log()` | Patch addon **and** debug_value. Both glTF call sites. |
| Empty `camera/` or `depth_png/` only | Dirs created before/after failed render | Need `depth/000.exr` |
| Patch `CMDS_BLOCK_NOT_FOUND` | Fragile whitespace | Grep the live file |
| Log stuck on `Loading custom unet ...` | `torch.load` 25.3 GB off geesefs; no tqdm | Watch VRAM → ~27 GB; do not restart |
| OpenCV EXR `None` | OpenCV without EXR | `OPENCV_IO_ENABLE_OPENEXR=1`; None-guard; bpy fallback |
| Files named `0000001.exr` | Compositor frame suffix | Rename to `000.exr` |
| HDRI 0 bytes | geesefs | Real 66 MB EXR |
| `../blender-4.2.9-linux-x64` | Relative geesefs path | `/opt/blender/blender` |
| Blender 4.2.4 vs path 4.2.9 | Upstream hard-coded name | Ignore the name; overlay blender |
| `render_temp` on volume empty | Write/symlink failure | `/opt/render_temp` |
| `shutil.copy` fail | geesefs | `copyfile` |
| rembg/numpy 2 fight | Version clash | `--no_rembg`; numpy 1.26.3; still **install rembg** for import |
| `huggingface_hub` vs `diffusers` 0.20.2 | Hub API drift | `huggingface_hub==0.25.2` |
| 24GB card OOM on infer | UNet too big | 40GB+; no CPU-offload plan |
| “15 min GPU” | Bad estimate | ~38 s once in VRAM; 20–30 min geesefs load |
| xatlas hour on A6000 | `bake_pipeline` / `infer_paint` | Never on 40GB; skip if UVs exist |
| `blender_low.obj` bake | Official reduce | Full `blender.obj` / remesh GLB |
| `infer_multiview` ignores Blender failure | `subprocess.run` no check + Blender exit 0 | Require EXR files |
| Extra 15 GB unet safetensors download | Wrong file | Use `v29_25000.ckpt`; skip the other |
| MV-Painter clone is symlink to `/opt` | Died with old pod | Real tarball clone on volume |
| `FileNotFoundError` pip cwd | `mv` away from cwd | `cd /tmp` |
| Matching `.glb` to `.jpg` | Code wants `.png` via string replace | PNG copies, same stem |
| Pair missing from the loop | PNG missing or 0-byte; silent skip | `test -s` both |
| Infer “succeeds” in 0 s for a stem | Leftover `*_6view.png` (even empty) | `rm` empty 6-views first |
| `scripts/blender_render_ortho.py` not found | Wrong cwd | `cd .../MVPainter` |
| 40GB death #1 | geesefs blender / no OpenCV in Blender Python | Overlay blender + BLEND_CV2 |
| 40GB death #2 | `/opt/blender` but `debug_value=256` still set | Grep proof + GLTF_OK **before** UNet |

### M.4 Bake / UV

| Symptom | Cause | Fix |
|---------|--------|-----|
| ~1 h 10 min CPU, GPU idle | xatlas unwrap full remesh | Local; skip if UVs already on mesh |
| Low-quality bake | Used `blender_low` / 30k | Full remesh |
| 40GB sitting in bake | Wrong machine | Stop; move to local/small CUDA |
| Unwrap with no 6-view | Wrong order | 6-view first |

---

## N. First-try sequences (copy)

### N.A New 24GB mesh pod (install already on disk → skip to generate)

1. GATE-MESH-BOX (24 GB+, nvcc on PATH, devel image)  
2. If GATE-MESH-INSTALL fails → `trellis2_setup.sh` once (Eigen, no xformers, flash wheel, `trellis2_patch.py`, HF token for DINOv3, skip BRIA)  
3. Upload PNG stills (`test -s`)  
4. `trellis2_run.py --skip-texture` per stem  
5. Isolated remesh if generate-only (not `trellis2_manual_remesh.py` for deliverable)  
6. Hex-pull each GLB; rename `_from_front` → `variants/<stem>/mesh.glb`  
7. Shut 24GB as soon as files are local  
8. Do not wait to start paint **setup** on 40GB (after paint gates, not before)  

**This round: skip N.A. Meshes are local.**

### N.B New 40GB paint pod (volume already has 36 GB blobs)

1. Volume **not** attached elsewhere. Overlay ~30 GB is for Blender/venv/pointers only.  
2. Extract Blender tarball → `/opt/blender` (full tree).  
3. Overlay venv `/opt/mvpaint-venv` (`cd /tmp`, pins above, rembg installed, numpy 1.26.3).  
4. Real `/workspace/MV-Painter` on volume (tarball if clone already extracted).  
5. `du -sh` blobs; rebuild `/opt/hf` pointers + `refs/main`; skip extra 15 GB safetensors.  
6. Patch ortho `debug_value=0`, both glTF calls `loglevel=0`, `set_debug_log` fallback, infer blender path + `/opt/render_temp` + require EXR + `copyfile`.  
6b. **Grep proof:** no `debug_value=256`; infer contains `/opt/blender/blender` and `/opt/render_temp`.  
7. OpenCV in Blender Python; rasterizers import in venv. HDRI ~66 MB.  
8. Upload six GLB+PNG pairs; `test -s`; delete leftover `*_6view.png`.  
9. **GATE-PAINT-BLENDER** (`BLEND_CV2` + `GLTF_OK`) — **stop if this fails**  
10. **GATE-PAINT-HF**  
11. **Only then** `infer_multiview` with `HF_HOME=/opt/hf` `--geo_rotation -90 --no_rembg`  
12. First real `*_6view.png` file → tell the user they can bake locally  
13. Same process finishes the rest  
14. Pull 6-views; shut 40GB; never bake here  

### N.C Local bake

1. Have `mesh.glb` + `*_6view.png`  
2. Skip xatlas if UVs present  
3. Full mesh, not `blender_low`  
4. Local NVIDIA or small CUDA  

---

## O. Explicitly not a reason to use 40GB

- CuMesh remesh / TRELLIS `1024`  
- Blender being slow on a 1M mesh (still not remesh; still not a reason to skip GATE-PAINT-BLENDER)  
- xatlas / bake / `infer_paint`  
- “Weights are on the volume so infer is 15 minutes” (VRAM load 20–30 min; paint 38 s)  
- CPU-offload of the UNet  

40GB = UNet fits in VRAM. That is the whole justification.

---

## P. Check 2 contrast vs previous PROCESS.md (findings)

Added in this rewrite because they were missing or too weak:

1. Meshes-already-done table at the top; do not remesh.  
2. User already stopped the 40GB pod; agent cannot `runpodctl`.  
3. Hunyuan3D mesh ban **and** Hunyuan-Paint; TRELLIS.2 vs older LEGAL TRELLIS v1 note; SF3D $1M.  
4. GTX 1050 / Windows `nvidia-smi` path; Linode too small.  
5. Never one-sentence disk: 15 GB safetensors vs **25.3 GB ckpt**; overlay ENOSPC numbers.  
6. Buy 50 GB volume, not 40/80. 60 GB container disk for mesh without volume.  
7. RunPod `container create: exit status 1`; 16 GB Ada wrong; devel image; `CUDA_HOME`.  
8. Guessed remesh OOM was **false**; measured RSS/dmesg; hole-fill counts; `remesh=False` holes; remesh-256 crash test; ~465k/940k success.  
9. DINOv3 gated + skip BRIA; agent does not paste token.  
10. flash-attn `2.7.3 \|\| xformers` fallback is a disk killer; FlexGEMM pin; utils3d full hash.  
11. `huggingface_hub==0.25.2`; rembg still imported; both glTF call sites; `refs/main`; HDRI 66 MB; 139 MB fake blender.  
12. Stale helper table (`_paint_start_infer.py` wrong `HF_HOME`).  
13. xatlas **1 h 10 min**; mid-load 6.5/2 GB; target ~27 GB VRAM.  
14. CRLF; no prompt on MV-Painter; silent PNG skip; 0-byte 6view skip.  
15. Watcher `SIXVIEW_COUNT` / `TSTAT` / `DSTAT`.  

Kept from previous PROCESS.md: gates, geesefs facts, debug_value chain, cost split, first-try sequences, WebP off, `--skip-texture`, overlay vs volume, session laws 1–10.
