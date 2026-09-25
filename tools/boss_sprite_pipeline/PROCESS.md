# Boss 3D — canonical runbook

**Read this before any pod command. Do not improvise. Do not re-derive.**
If a failure looks new, it is almost certainly in **§8 (bug encyclopedia)** — search there first.
Every hour of the wasted week was a bug from §8 being rediscovered in the same session.

- The **do-it-now checklist** is [`CHECKLIST.md`](CHECKLIST.md). This file is the *why* + every command + every bug.
- Facts below were re-verified against the repo on disk and MV-Painter / TRELLIS.2 / Hugging Face upstream on **2026-09-20**. Numbers marked *(verified)* were checked against source or disk.
- **✅ VALIDATED END-TO-END on 2026-09-20.** This runbook was executed on a real pod and produced all six
  textured GLBs in ~2 h of pod time, one pod, no reruns. Numbers marked *(measured)* come from that run.
  Where the run contradicted what this file said that morning, **the file has been corrected** — see §10 changelog.
- Historical files (`README.md`, `gpu_box/RUNPOD.md`, `PLAN.md`, `LEGAL_LIABILITY.md`, `_checks/*.md`) are **superseded**. If any of them disagrees with this file, **this file wins.**

| Need | Go to |
|------|-------|
| What is done / what not to redo | §0 |
| The one rule + parked-Blender rule | §1 |
| Bans: legal + never-do | §2 |
| Machines & cost split | §3 |
| **Paint runbook (the live task)** | §4 |
| Local bake | §5 |
| Mesh runbook (future characters) | §6 |
| SSH / file transfer | §7 |
| Bug encyclopedia (search first) | §8 |
| Stale helper scripts (do not run) | §9 |
| Timings, incidents, changelog | §10 |

---

## §0 — State: what is done, what is left

### Done — do NOT redo

The six round-2 meshes exist on this PC, are the right size, have UVs, and read as real 3-D bipeds
from the side *(verified: rendered front+side locally 2026-09-20 — solid volume, not pancakes)*.

| Stem | `variants/<stem>/mesh.glb` bytes | verts *(verified)* |
|------|----------------------------------|--------------------|
| `gpt2_front_paint`       | 47,518,728 | 714,462 |
| `gpt2_front_ink`         | 47,387,500 | 724,239 |
| `gpt2_front_sculpt`      | 45,702,676 | 659,015 |
| `nano2_concept_art`      | 47,201,284 | 693,713 |
| `nano2_2d_illustration`  | 47,323,308 | 702,818 |
| `nano2_3d_render`        | 44,977,296 | 640,344 |

All under `generated/bosses/demon/`. All carry `POSITION, NORMAL, TEXCOORD_0` (they **already have UVs**),
PNG textures, no WebP. Concepts: `concept/round2/*.jpg`; opaque PNG copies: `concept/round2_png/*.png`.

**GATE L0 — meshes are local (run on this PC; if OK, never rent a mesh pod for these six):**

```powershell
$stems='gpt2_front_paint','gpt2_front_ink','gpt2_front_sculpt','nano2_concept_art','nano2_2d_illustration','nano2_3d_render'
$root='C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants'
$ok=$true
foreach($s in $stems){ $p=Join-Path $root "$s\mesh.glb"
  if(-not(Test-Path $p) -or (Get-Item $p).Length -lt 10MB){$ok=$false; "MISSING_OR_TINY $s"} else {"HAVE $s $((Get-Item $p).Length)"} }
if($ok){'GATE_L0_OK'}else{'GATE_L0_FAIL'}
```

Do **not** confuse these with older files in `generated/bosses/demon/mesh/`:
`raw_desert_sf3d.glb` (Stable Fast 3D pancake), `demon_from_front_manual_remesh.glb` (crash-test, **no UVs**),
`demon_from_front_noremesh.glb` (holes), `trellis2_textured_png.glb` (TRELLIS PBR we do not ship),
`demon_painted*.glb` (an **earlier** single-demon paint, not round 2).

### Left to do

1. **Paint** the six meshes → `*_6view.png` per stem → bake → textured GLB. **§4 then §5.** Zero 6-views exist yet.
2. There is **no other open step.** Mesh is finished; do not touch it.

---

## §1 — The rule that caused the wasted week

> **Never load the 25 GB paint UNet (`v29_25000.ckpt`) until GATE B9 has printed `GATE_B9_OK`.**

That load is 20–30 min. The day was burned loading it into a Blender that had already crashed, then
throwing away the load and reloading. **Blender exits 0 even after a Python traceback**, so
`blender --version`, `BLENDER_RC 0`, and "blender ran" are **never** proof. Proof is only:
`depth/000.exr … 005.exr` exist and are non-zero.

### Is it working, or hung? (deterministic — never judge by "no output")

**The single test is CPU-time delta, not log output.** Sample `utime` from `/proc/<pid>/stat` twice, 20 s apart:

```bash
P=<pid>; awk '{print $14}' /proc/$P/stat; sleep 20; awk '{print $14}' /proc/$P/stat
# grew by ~2000 jiffies (=20 s of CPU) -> the process is WORKING. Leave it alone.
# unchanged, and no new output files -> genuinely stuck.
```

- Blender ortho on a ~700 k-vertex mesh: **~2 min** *(measured)*. `%CPU == 0` **and** RSS flat **and** no
  `depth/000.exr` after 60 s → dead gate, kill and re-run.
- Success is always the **artifact**: `depth/000.exr … 005.exr` non-zero.

**⚠️ CORRECTION (learned the hard way 2026-09-20): silence is NOT evidence of failure.**
`bake_pipeline.py` prints **nothing** between `UV_REUSE` and writing the finished GLB — so a healthy 25-minute
bake and a hang look *identical* in the log. On the validated run a 15-minute "stop threshold" would have
**killed six working jobs** that completed minutes later. Before killing anything that has no progress output:

1. check the CPU-time delta above — if CPU is advancing, it is working;
2. remember which tools have no progress output: **`bake_pipeline.py`** (silent until the GLB) and the
   ckpt `torch.load` (silent, tqdm `\r`).

"GPU 0 % is not death" is broader than previously written: it is normal for the ckpt `torch.load` **and** for
bake, which is largely single-core CPU with short GPU bursts that instantaneous `nvidia-smi` sampling misses.
A non-zero VRAM allocation with 0 % utilisation is not a stall.

### Process laws (these are why it repeated, not software bugs)

1. **A named bug in §8 is solved. Apply the fix; do not rediscover it.**
2. **Every restart replays the FULL gate**, never a subset. The repeats happened because a restart
   fixed one thing and silently dropped a fix from the previous restart.
3. **After any code patch, `grep` the live file for the result.** A Python `replace()` that printed
   `*_NOT_FOUND` changed nothing. `sed`/replace on RunPod TTY can be corrupted by line-wrap — keep patch lines short.
4. **If install/compile already succeeded, resume the job — do not reinstall.** A dead process →
   read `free -h`, `dmesg`, the *full* log. Do **not** guess "OOM": the one measured remesh death was RSS
   ~24 GB of **256 GB**, dmesg empty (a CuMesh native abort), not the OOM killer.
5. **Keep ONE `infer_multiview` alive** once weights are in VRAM. Killing it to "fix Blender" pays the
   20–30 min load again. Fix Blender **before** infer, via the gate.
6. **Tell the user the instant** a real `*_6view.png` exists (bake can start) and the instant a different
   machine is needed. Never invent an ETA that contradicts §10.
7. **You cannot stop a pod from here** (no RunPod API key on this PC). The user stops it in the dashboard.
   Confirm state before telling them anything about a pod; never tell them to kill a pod they already stopped.

---

## §2 — Bans

### Legal (hard stop — this is a licence line, not a preference)

| Tool | Status | Why |
|------|--------|-----|
| **Hunyuan3D mesh** (2 / 2.1 / 2mini / 2mv) | **Forbidden** | Tencent Hunyuan 3D Community Licence excludes the EU, UK, South Korea, and restricts the **outputs**, not just the weights. `gpu_box/hunyuan3d_cli.py` is historical; do not run it "just to look." |
| **Hunyuan-Paint** (Hunyuan3D-Paint 2.x) | **Forbidden** | Same licence, same territory + output ban. |
| **MV-Painter** (`shaomq/MVPainter`) | **USE THIS** for paint | Apache-2.0. Public/ungated *(verified)*. Image + mesh only, **no text prompt**. |
| **TRELLIS.2** (`microsoft/TRELLIS.2-4B`) | **USE THIS** for mesh | Microsoft weights MIT, public *(verified)*. Its own textured export pulls NVIDIA `nvdiffrast`/`nvdiffrec` (non-commercial), so we **`--skip-texture`** and paint with MV-Painter instead. |
| **Stable Fast 3D** | Historical only | Single-image → pancake (`raw_desert_sf3d.glb`). Not used now. |

`LEGAL_LIABILITY.md` still records the SF3D revenue clause and the Hunyuan/TRELLIS rejection — leave it as a
record. Do **not** "fix" a mesh/paint problem by switching to Hunyuan.

### Never-do (each one cost real money)

- `pip install xformers` unpinned on the mesh pod → pulls a **second torch**, fills the disk.
- Compile flash-attn from source → use the prebuilt wheel (§6).
- Decimate to `blender_low.obj` / 30 k for bake → texture quality dies. Use the full mesh.
- Run `infer_paint` / `bake_pipeline` / `xatlas.parametrize` on the 40 GB pod (§5).
- Attach one network volume to two pods, or lean on the network volume at all (§3 — use a big container disk instead).
- Start `infer_multiview` before `GATE_B9_OK`.

---

## §3 — Machines & cost split

| Step | Work | GPU | Disk | Notes |
|------|------|-----|------|-------|
| 0 Concept | front PNG/JPG, subject on black/alpha | **local** | — | this PC (GTX 1050, too small for any ML) |
| 1 Mesh (TRELLIS.2 + CuMesh remesh) | image → `mesh.glb`, `--skip-texture` | **24 GB-class** (A5000/3090) | **60 GB container**, no volume | toy 4/8/12 GB OOMs 1024. **Already done for the six.** §6 |
| 2 **Paint** (`infer_multiview` → `*_6view.png`) | the 25 GB UNet must sit in VRAM | **40 GB+** (A6000 48 GB, A40, A100) | **80 GB container**, no volume | the live task. §4 |
| 3 Bake (unwrap + back-project) | xatlas (CPU-heavy) + small CUDA | **local NVIDIA or a small ~$0.15/hr CUDA pod** | — | never the 40 GB box. §5 |

**Disk: both layouts work. Pick one and be consistent.** *(corrected after the validated run)*

| Layout | Verdict |
|---|---|
| **A — volume + 30 GB container** (what the validated run used) | **Works.** Keep the ~38 GB HF blobs on the volume; put **venv, Blender, MVPainter, `render_temp`, outputs on the container**. Rebuild the HF snapshot pointers onto the container (§4 P3). Do **not** copy the 25 GB ckpt to a 30 GB container — it will not fit alongside the venv. Loading the ckpt from the volume was **fast on the validated run** (page cache, 503 GB RAM), not the feared 20–30 min. |
| **B — 80 GB container, no volume** | Also fine, and avoids geesefs entirely; costs a ~38 GB re-download per pod. |

**The earlier claim "never use a volume, always 80 GB container" was overstated.** The volume is fine *provided*
nothing executable and no `render_temp` lives on it — that, not the volume itself, was the original bug.
Measured on the validated run: container peaked ~**5 GB of 30 GB** with the blobs on the volume.

Non-negotiable either way: **venv, Blender, MVPainter checkout and `render_temp` go on the container.**
geesefs breaks executables (`chmod +x` doesn't stick, truncated `libsycl.so.7`, venv `OSError`) and turns HF
snapshot symlinks into 0-byte files while the blobs stay intact.

**RunPod deploy:** official **PyTorch devel** image (`runpod/pytorch:…-devel-…`, so `nvcc`+`g++` exist),
public IP, TCP 22, SSH key = paste `ppp.pub`, **no custom start command**. Community `container create:
exit status 1` bills $0 — retry / different region / Secure Cloud on the third failure. Mesh A5000 ≈ $0.16/hr,
paint A6000 ≈ $0.22–0.53/hr.

---

## §4 — Paint runbook (40 GB pod). The live task.

Goal: `infer_multiview.py` → one `*_6view.png` per stem. Then bake **locally** (§5). Never bake here.

Upstream facts *(verified against MV-Painter `main`)* you must respect:
- `infer_multiview.py` runs Blender, then reads `render_temp/<uid>/…` **relative to its cwd**. Keep cwd =
  the MVPainter dir and put MVPainter on the container → `render_temp` is on the container, writable, no geesefs.
- It downloads `unet_w_controlnet/v29_25000.ckpt` (**25.33 GB**) and `torch.load`s it → the file must be on
  **fast local disk**, never read through a network volume.
- It reference-matches GLB→image by the literal string `base_name.replace("glb","png")` → the PNG must have the
  **same stem** as the GLB and live in `input_img_dir`. A missing PNG is a **silent skip** (no error).
- Seed 12, 75 steps, depth EXR channel `V`, 6-view tile order `000,005,001,004,002,003`.
- The blender path is hard-coded as `../blender-4.2.9-linux-x64/blender` (relative to MVPainter). We satisfy it
  with a symlink instead of editing that line.

### P0 — deploy & GATE_GPU

40 GB+ GPU, disk per §3 (**volume + 30 GB container**, or **80 GB container alone** — both validated/fine),
devel image, and **Public IP + TCP 22 exposed** so `scp` works for the 293 MB upload (§7). Then:

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader   # memory.total must be >= 40000 MiB
which nvcc g++ ; df -h /
```

`memory.total >= 40000` → `GATE_GPU_OK`. A 24 GB card OOMs the ckpt; do not try to CPU-offload it.

### P1 — download weights → GATE_HF (no volume, no pointer rebuild)

`shaomq/MVPainter` is public — **no HF login needed.** Skip the 15 GB `v29_25000.safetensors` (unused; infer uses the `.ckpt`).

```bash
export HF_HOME=/root/hf HF_HUB_ENABLE_HF_TRANSFER=0
pip install -U "huggingface_hub[cli]"
hf download shaomq/MVPainter --exclude "unet_w_controlnet/v29_25000.safetensors"
python3 - <<'PY'
import json,glob,os
snap=glob.glob("/root/hf/hub/models--shaomq--MVPainter/snapshots/*")[0]
idx=os.path.join(snap,"model_index.json"); assert os.path.getsize(idx)>0; json.load(open(idx))
ck=os.path.join(snap,"unet_w_controlnet","v29_25000.ckpt")
assert os.path.getsize(ck) > 20_000_000_000, "ckpt missing/small"
print("GATE_HF_OK ckpt_bytes", os.path.getsize(ck))
PY
```

Expected total ≈ **38.6 GB** *(verified)*. If `HF_HUB_ENABLE_HF_TRANSFER=1`, tiny files fail — keep it `0`.

### P2 — MVPainter, venv, Blender → INSTALL_OK

```bash
cd /opt && git clone --depth 1 https://github.com/amap-cvlab/MV-Painter.git
python3 -m venv --system-site-packages /opt/mvpaint-venv    # do NOT pip torch; system torch on the devel image
cd /tmp                                                     # never pip from a dir you just moved
/opt/mvpaint-venv/bin/pip install -U pip wheel ninja pybind11
/opt/mvpaint-venv/bin/pip install \
  diffusers==0.20.2 transformers==4.40.1 huggingface_hub==0.25.2 \
  einops omegaconf opencv-python pytorch-lightning==2.2.4 accelerate addict safetensors \
  OpenEXR==3.2.4 trimesh pygltflib kiui scikit-image imageio jaxtyping \
  lightning-utilities timm onnxruntime tqdm Pillow rembg numpy==1.26.3 scipy==1.13.0
# Blender 4.2.4 LTS (its own name says 4.2.x — the hard-coded 4.2.9 is a lie; ignore it)
cd /tmp && curl -L --fail -o bl.tar.xz https://download.blender.org/release/Blender4.2/blender-4.2.4-linux-x64.tar.xz
tar -xJf bl.tar.xz && rm -rf /opt/blender && mv blender-4.2.4-linux-x64 /opt/blender && chmod +x /opt/blender/blender
/opt/blender/4.2/python/bin/python3.11 -m ensurepip --upgrade || true
/opt/blender/4.2/python/bin/python3.11 -m pip install opencv-python-headless
echo INSTALL_OK
```

Pins matter: newer `huggingface_hub` breaks `diffusers==0.20.2` (pin **0.25.2**); keep **numpy 1.26.3**.
`infer_multiview.py` does `import rembg` at module top even with `--no_rembg`, so rembg must import (we still pass `--no_rembg`).

Then satisfy the hard-coded blender path with a symlink (no need to edit the source line):

```bash
ln -sfn /opt/blender /opt/MV-Painter/blender-4.2.9-linux-x64
echo INSTALL_OK
```

> **The paint pod does NOT need the CUDA rasterizers.** *(verified)* `infer_multiview` imports only
> `mvpainter_pipeline` + `controlnet`, and neither imports `custom_rasterizer` / `differentiable_renderer`.
> Those compile only for **bake** (§5) — do not compile them here, and do not let a rasterizer build failure
> block the paint run. (nvcc is likewise only needed on the bake machine, not for paint.)

### P3 — patch the Blender ortho script → GATE_PATCH

Five patches to `scripts/blender_render_ortho.py` (upstream line refs *(verified)*):

1. `bpy.app.debug_value=256` → **`=0`**. (256 makes glTF `set_debug_log()` return `None`; the importer then sets
   `loglevel=None` and dies with `IMPORT_SCENE_OT_gltf.loglevel expected an int … NoneType` — while Blender still exits 0.)
2. Both glTF imports get `loglevel=0`: `import_scene.gltf(filepath=object_path, merge_vertices=True)` **and**
   `import_scene.gltf(filepath=glb_path)`. (Operator arg alone is not enough — patch #1 and #3 too.)
3. In `/opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py`, `set_debug_log()`: add a final
   **`return logging.INFO`** after the 0–4 branches (so it never returns `None`).
4. `OPENCV_IO_ENABLE_OPENEXR=1` **before** `import cv2` (the module does `import cv2` at load; without EXR support cv2 reads the normal EXR as `None`).
5. The normal-EXR block — replace with the **proven** fallback below. The upstream/naïve guard leaves
   `normal_unit16` unset when `cv2.imread` returns `None`, so `cv2.imwrite(...)` raises `UnboundLocalError`
   **after view 0** and `depth/001.exr` never appears.

Proven block (this is the version that produced a real 6-view):

```python
if os.path.exists(os.path.join(args.output_dir, object_uid, 'normal', f"{view_id:03d}0001.exr")):
    exr_p = os.path.join(args.output_dir, object_uid, 'normal', f"{view_id:03d}0001.exr")
    png_p = os.path.join(args.output_dir, object_uid, 'normal', f"{view_id:03d}.png")
    normal = cv2.imread(exr_p, cv2.IMREAD_UNCHANGED)
    if normal is None:                         # OpenCV EXR read failed → load via Blender
        img = bpy.data.images.load(exr_p)
        w, h = img.size; ch = img.channels
        pix = np.array(img.pixels[:], dtype=np.float32).reshape((h, w, ch))
        normal = np.flipud(pix)[:, :, :3].copy()
        bpy.data.images.remove(img)
        print('EXR_BPY_FALLBACK', view_id, normal.shape)
    normal_unit16 = (np.clip(normal, 0, 1) * 65535).astype(np.uint16)
    cv2.imwrite(png_p, normal_unit16)
    os.remove(exr_p)
```

**Grep proof** (patch is worthless unless the live file shows it):

```bash
f=/opt/MV-Painter/MVPainter/scripts/blender_render_ortho.py
grep -c "bpy.app.debug_value=256" $f        # must be 0
grep -c "loglevel=0" $f                      # must be 2
grep -c "EXR_BPY_FALLBACK" $f                # must be 1
grep -c "return logging.INFO" /opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py   # >= 1
echo GATE_PATCH_OK
```

### P4 — upload the six pairs → GATE_PAIR

Same stem, PNG (not JPG) in `imgs/`, GLB in `glbs/`. Delete any leftover `*_6view.png` (a 0-byte or old one makes
infer **return instantly** for that stem and skip it).

```bash
mkdir -p /opt/MV-Painter/MVPainter/mvpaint_in/glbs /opt/MV-Painter/MVPainter/mvpaint_in/imgs
# hex-upload the 6 mesh.glb (as <stem>.glb) and 6 round2_png/<stem>.png (as <stem>.png) — see §7
find /opt/MV-Painter/MVPainter/mvpaint_out -name '*_6view.png' -delete 2>/dev/null || true
python3 - <<'PY'
import os
b="/opt/MV-Painter/MVPainter/mvpaint_in"
stems=["gpt2_front_paint","gpt2_front_ink","gpt2_front_sculpt","nano2_concept_art","nano2_2d_illustration","nano2_3d_render"]
ok=True
for s in stems:
    g=f"{b}/glbs/{s}.glb"; p=f"{b}/imgs/{s}.png"
    gs=os.path.getsize(g) if os.path.exists(g) else 0
    ps=os.path.getsize(p) if os.path.exists(p) else 0
    print(s,"glb",gs,"png",ps)
    if gs<10_000_000 or ps<1000: ok=False
print("GATE_PAIR_OK" if ok else "GATE_PAIR_FAIL")
PY
```

### ⚠️ REFERENCE BACKGROUND MUST BE WHITE (or real alpha) — NOT opaque black

**This was got wrong on the validated run and it visibly degraded every result.** The round2 PNGs were opaque
with a **57–65% pure-black** background *(measured)*. MV-Painter's `to_rgb_image()` composites RGBA onto white
**using the alpha mask** — with alpha all 255 the white is fully covered, so the model received a black-background
image. MV-Painter conditions on the reference through CLIP + VAE, and it is trained on **white** backgrounds
(`recenter_img` pads with `(255,255,255)`). Out-of-distribution input →
**pale, desaturated, low-contrast output; small high-contrast details such as glowing red eyes wash out.**

An earlier revision of this file claimed a black background was "fine for paint because only mesh-covered pixels
are projected." **That is wrong** — the reference conditions the entire generation, not just projected texels.

**Do this:** give the reference **real alpha** (cut the background out) so `to_rgb_image` composites it onto white,
or composite onto white yourself. Verify before upload:

```python
from PIL import Image; import numpy as np
a = np.array(Image.open(p))                      # want: RGBA with a real alpha channel
assert a.shape[2] == 4 and not (a[...,3] == 255).all(), "opaque -> background will survive"
```

Related quality levers when the face/eyes lack detail:
- `BakeConfig.texture_size` is **1024** for the whole body — raise to 2048/4096 for facial detail.
- `mvpainter_pipeline.py` computes `cond_image = recenter_img(image)` then **immediately overwrites it** with
  `to_rgb_image(image)` (upstream bug). Fixing that makes the subject fill the 512 px conditioning frame.

(Separately, for a future *mesh* run the same opaque-alpha issue routes TRELLIS into the rembg branch — see §6.)

### P5 — the wall: GATE_B9 (Blender), before the UNet

```bash
cd /opt/MV-Painter/MVPainter
G=mvpaint_in/glbs/gpt2_front_ink.glb
/opt/blender/blender --background --python-expr "import cv2; print('BLEND_CV2', cv2.__version__)"
/opt/blender/blender --background -Y --python-expr "import bpy; bpy.app.debug_value=0; bpy.ops.import_scene.gltf(filepath='$G', merge_vertices=True, loglevel=0); print('GLTF_OK', len(bpy.data.objects))"
rm -rf render_temp/gpt2_front_ink
OPENCV_IO_ENABLE_OPENEXR=1 /opt/blender/blender --background -Y --python scripts/blender_render_ortho.py -- \
  --object_path $G --geo_rotation -90        # writes to ./render_temp (container, relative)
for i in 000 001 002 003 004 005; do test -s render_temp/gpt2_front_ink/depth/$i.exr || { echo GATE_B9_FAIL $i; exit 1; }; done
echo GATE_B9_OK
```

`BLEND_CV2` + `GLTF_OK` (objects > 0) + all six `depth/*.exr` non-zero. **If this fails, stop — do not load the UNet.**
`camera/` is created *before* import and `depth_png/` *after*; an empty one of those is failure, not progress.

### P6 — ONLY NOW: infer_multiview

```bash
cd /opt/MV-Painter/MVPainter
export HF_HOME=/root/hf HF_HUB_ENABLE_HF_TRANSFER=0 PYTHONUNBUFFERED=1 OPENCV_IO_ENABLE_OPENEXR=1
nohup /opt/mvpaint-venv/bin/python -u infer_multiview.py \
  --input_glb_dir mvpaint_in/glbs --input_img_dir mvpaint_in/imgs \
  --output_dir mvpaint_out --geo_rotation -90 --no_rembg \
  > /root/infer.log 2>&1 &
echo INFER_PID=$!
```

The pipeline loads **once**, then loops all six. Watch **files**, not log text:

```bash
python3 -c "import pathlib; print('SIXVIEW', len(list(pathlib.Path('/opt/MV-Painter/MVPainter/mvpaint_out').rglob('*_6view.png'))))"
```

`Loading custom unet …` sitting still with GPU 0 % = the 25 GB `torch.load`; VRAM climbs 2 → ~27 GB — **do not
restart** (per §1). tqdm shows `1/7` frozen because of `\r`; not a hang. A grep of a shell script for `6view`
is a false positive — count the actual files.

### P7 — deliver, **pipelined** (do not wait for all six)

Paint is **fast per stem** (~2–3 min: Blender ortho + ~38 s GPU). Bake is **slow per stem** (minutes at best,
up to ~1 h if xatlas runs). So **bake is the long pole and the pod is not** — the schedule that wastes the least
money is to overlap them:

```
pod:    [ckpt load]  stem1  stem2  stem3  stem4  stem5  stem6   → STOP POD
local:               ........ bake1  bake2  bake3  bake4  bake5  bake6 ...
                     ↑ start local bake on stem1 while the pod paints stem2
```

1. The **instant** `mvpaint_out/mvpainter/<stem>/<stem>_0_6view.png` appears for the **first** stem:
   **tell the user**, pull that one folder, and **start the local bake for it immediately.**
   Do **not** wait for the batch. The pod keeps painting the rest on the same loaded model.
2. Pull each later stem's folder as its 6-view lands (`blender.obj`, `result_1..6.png`, `*_6view.png`).
3. **Stop the pod the moment the sixth folder is on the PC** — never keep it alive during local bake.
   The GPU has nothing left to do; every minute after that is pure waste.

### Parallelism rules (the pod meter is the thing being optimised)

| While the pod is doing this | Do this at the same time |
|---|---|
| installing (clone / pip / Blender) | **upload the 293 MB of inputs** — do not wait for install to finish |
| the one-off ckpt load (20–30 min off a volume) | nothing touches the pod; prepare the **local bake toolchain** and patches |
| painting stem *N* | **pull + bake stem *N−1* locally** |
| nothing useful | **stop it** — say so to the user immediately |

**Wall-clock budget — *(measured on the validated 2026-09-20 run, six stems)***. If a step runs far over,
check the CPU-time delta (§1) before concluding anything is wrong.

| Phase | Measured |
|---|---|
| install (clone + pip + Blender + opencv-in-Blender) | ~8 min |
| upload 293 MB via `scp` on the **direct IP** | ~2 min |
| patch ortho + rebuild HF pointers | ~1 min |
| GATE_B9 (glTF import + 6-view ortho, ~700 k mesh) | ~2 min |
| pipeline components 7/7 | **2 min 40 s** |
| ckpt load (25.3 GB, from volume, warm page cache) | **~3 min** (cold/uncached: allow 20–30) |
| **paint per stem** (Blender ortho + 75-step diffusion) | ~2 min + **39 s** GPU |
| **all six paints** | **~12 min** |
| **bake, six stems run IN PARALLEL** | **~30 min total** (see §5 — sequential would be ~6×) |
| **whole job, one pod** | **~2 h** including debugging |

---

## §5 — Local bake (the "long CPU part")

Bake is `infer_paint.py` → `bake_pipeline.py`: it back-projects the six painted views onto the mesh and writes
the textured `<stem>.glb`. The bake used only ~1.4 GB VRAM / ~3 GB RAM *(measured)* — the machine cost is tiny.
The **only** expensive thing is `xatlas.parametrize` (UV unwrap): on the A6000 it took **1 h 10 min** because
`bake_pipeline` recomputes UVs from scratch on the ~700 k-face mesh.

**Where:** a **local NVIDIA GPU** or a **small ~$0.15/hr CUDA pod**. **Never** a fresh 40 GB rental for bake.
Bake — unlike paint — **does** need the two CUDA rasterizers, so this machine needs `nvcc` (devel image) to compile them:

```bash
export TORCH_CUDA_ARCH_LIST=<your arch>  PATH=/usr/local/cuda/bin:$PATH CUDA_HOME=/usr/local/cuda
for d in custom_rasterizer differentiable_renderer; do
  cd MV-Painter/MVPainter/mvpainter/$d
  python - <<'PY'
import runpy,sys,torch.utils.cpp_extension as ext
ext._check_cuda_version=lambda *a,**k:None
sys.argv=["setup.py","install"]; runpy.run_path("setup.py",run_name="__main__")
PY
done
python -c "import custom_rasterizer, differentiable_renderer; print('RAST_OK')"   # needs ninja + pybind11
```

Inputs per stem: the pulled `mvpainter/<stem>/` folder (`blender.obj` + `result_1..6.png`), plus `xatlas` and `trimesh`.

### Extra deps bake needs that paint does NOT *(both cost real time on the validated run)*

- **`cupy-cuda12x`** — `differentiable_renderer/voronoi.py` does `import cupy` at module load. Without it bake
  dies at import, *after* paint has finished. Install it before bake.
- **numpy is stage-specific. Do NOT "restore the paint pin" for bake.** `numpy==1.26.3` belongs to the *paint*
  stack (diffusers 0.20.2). cupy 14.x requires **numpy ≥ 2.0**. For bake use **`numpy>=2.0,<2.6` + `scipy>=1.14`**
  *(validated: numpy 2.5.3 / scipy 1.18.1 / cupy 14.2.0)*. Changing numpy under a **running** paint job is safe —
  loaded modules stay in memory — but do it after paint anyway.
- `import torch` **before** `custom_rasterizer`, or you get `ImportError: libc10.so`. That is an import-**order**
  artifact, **not** a broken build. `bake_pipeline.py` already imports torch first.

### Two patches

1. **Bake the full mesh**, not the 30 k decimate. `infer_paint.py` calls `reduce_mesh(..., target_vertices=30000)`
   → `blender_low.obj`, and `bake_pipeline.py` loads `blender_low.obj`. Point bake at `blender.obj` instead.
   *(validated: output kept 638 k–713 k verts, ~950 k–995 k tris, with UVs + one baked texture.)*
2. **Kill the xatlas hour.** `mesh_uv_wrap` in `mvpainter/uv_warp_utils.py` always calls `xatlas.parametrize`.
   The `blender.obj` **does** carry UVs *(verified: `f v/vt/vn`, 708 k `vt`, trimesh `visual.uv` 718 440×2 in [0,1])*,
   so patch `mesh_uv_wrap` to return early when `mesh.visual.uv` matches the vertex count. Confirm at runtime by
   the `UV_REUSE <n>` line. This removed the 1 h 10 m unwrap.

### ⭐ Run the stems IN PARALLEL — the single biggest bake win

Bake is **single-core CPU-bound**. One stem at a time wastes the box. Give each stem its own input dir and launch
one process per stem *(validated: 6 procs × ~1.3 GB = **7.7 GB VRAM**, load avg ~8.5 on 9 vCPU, ~**30 min for all
six** instead of ~6×)*:

```bash
cd /opt/MV-Painter/MVPainter
for s in <stems>; do rm -rf bake_split/$s; mkdir -p bake_split/$s
  ln -sfn $PWD/mvpaint_out/mvpainter/$s bake_split/$s/$s; done
cd mvpainter
for s in <stems>; do PYTHONUNBUFFERED=1 nohup /opt/mvpaint-venv/bin/python bake_pipeline.py \
   --input_dir bake_split/$s --save_dir mvpaint_out/glbs --offset 0 > /opt/logs/bake_$s.log 2>&1 & done
```

`--offset` = `geo_rotation + 90` → **0** for our `-90`. Paths are relative to `MVPainter` (bake prepends `..`).

**Expect ~25–30 min of total silence.** See the correction in §1: `bake_pipeline` prints nothing between
`UV_REUSE` and the finished GLB. Do not kill it on silence — check the CPU-time delta.

*Optional:* `back_project` calls `trimesh.geometry.mean_vertex_normals` on CPU once per view (6× per stem).
A GPU scatter-add (`index_add_` over the 3 face corners, then `F.normalize`) is equivalent — *verified to
1.2e-06 deg in float64; the 0.028 deg float32 gap is accumulation order only*. **Note the same block appears in
BOTH `render_normal` and `back_project`** — a `replace(..., 1)` patches only the first, which is the one bake
does **not** call. Patch all occurrences and verify by enclosing function name.

Result is a textured `<stem>.glb` → the deliverable for the sprite pipeline (render → pack; see README / `PLAN.md`).

---

## §6 — Mesh runbook (24 GB pod). Done for the six; keep for the next character.

Code: `gpu_box/trellis2_setup.sh`, `trellis2_run.py`, `trellis2_patch.py`. Not `trellis2_manual_remesh.py`
(that exports vertices/faces only — **no UVs** — it is crash-recovery geometry, never the paint-ready GLB).

**Deploy:** 24 GB-class (A5000/3090), **60 GB container, no volume**, devel image. `TRELLIS.2-4B` is 16.2 GB +
DINOv3 ~1.7 GB + venv/extensions — fits 60 GB with room. `df -h /workspace` on geesefs has shown `1.0P` — never trust it.

**Install once (resume, don't reinstall, if `import cumesh, o_voxel, nvdiffrast, flash_attn` already works):**

```bash
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3   # o_voxel needs Eigen headers
export TORCH_CUDA_ARCH_LIST=8.6 MAX_JOBS=2 HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn
bash tools/boss_sprite_pipeline/gpu_box/trellis2_setup.sh
/workspace/vendor/trellis2-venv/bin/python -c "import cumesh,o_voxel,nvdiffrast,flash_attn,torch;print('GATE_MESH_INSTALL',torch.cuda.get_device_name(0))"
```

Pins that already bit us: nvdiffrast **v0.4.0**; nvdiffrec branch `renderutils`; o-voxel copied from the TRELLIS.2
tree (not PyPI); utils3d commit `9a4eb15e…`; flash-attn **prebuilt wheel** `2.8.3.post1` `--no-deps` (never compile);
**never** `pip install xformers`; `MAX_JOBS=2` (1 if compile RAM-dies); venv `--system-site-packages` (do not pip torch).
If Torch/nvcc versions disagree: `torch.utils.cpp_extension._check_cuda_version = lambda *a,**k: None`.
GitHub clone stalling on Community → kill it, curl the tarball, fake a `.git` so setup's `[ -d $ROOT/.git ]` passes;
do not start a second clone.

**Gating:** DINOv3 is `gated=manual` *(verified)* — accept it in a **browser** and wait until the page no longer says
"awaiting review" (agreeing ≠ approval; otherwise generate 401s after a 20–30 min load). Token lives at `$HF_HOME/token`
and does **not** survive a new pod; log in on the box with `hf auth login` (old `huggingface-cli login` may 404).
**Skip BRIA/RMBG** — `trellis2_patch.py` sets rembg to `None` and guards `.to(device)`.

**rembg / opaque input:** TRELLIS `preprocess_image` uses the alpha channel **only if** it exists *and* is not all-255
*(verified upstream)*. The round2 PNGs are opaque (alpha all 255), so TRELLIS falls to the rembg branch. Either feed
real-alpha cutouts, or apply `_mesh_skip_rembg_restart.py`'s patch (`if rembg_model is None: output = input.convert('RGBA')`).
`--no_rembg` is a **paint** flag; it does nothing for TRELLIS.

**Generate + remesh:**

```bash
export HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
/workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_run.py \
  --image /workspace/in/<stem>.png --out-dir /workspace/out --name <stem> --skip-texture
```

`--skip-texture` mandatory (else brown TRELLIS PBR). Remesh is done **in-process** by `export_isolated_remesh`
(`band=1`, `project_back=0`, `fill_holes`, `simplify(1_000_000)`, `to_glb(remesh=False, texture_size=2048,
extension_webp=False)`). If generate finishes but remesh dies, the extract is saved as `<stem>_raw_extract.pt`;
re-run remesh in a **fresh** process (combined generate+remesh on the 3.4 M-face soup is what died in-process, a
CuMesh abort — **not** OOM; measure `free -h`/`dmesg`, don't guess). `1024_cascade` OOM → the script retries `512`;
stay on a 24 GB-class card, do not "try 512 on 16 GB." If `<stem>_from_front.glb` exists, skip that name.

Pull each GLB (hex, §7), rename `<stem>_from_front.glb` → `variants/<stem>/mesh.glb`, tens of MB. Shut the pod.

---

## §7 — SSH & file transfer

| Item | Value |
|------|-------|
| Key | `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp`. There is **no** `~/.ssh/id_ed25519` on this PC — RunPod Connect strings that cite it fall back to a password. Paste **`ppp.pub`** into the pod's SSH keys at deploy. Never paste the private key or an HF token into chat. |
| Flags | `-tt` (RunPod needs a PTY), `-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25`. Helpers sleep ~6 s for the banner before sending — do not "fix" by dropping `-tt`. |
| `Connection refused` | The pod is stopped. Get a fresh Connect line; do not invent a host. |
| Host string | Changes every pod. `HOST=` inside `_paint_pod.py` / `_mesh_pod.py` / `_pod_exec.py` goes stale the moment a pod dies — update it, keep key/flags. |
| **`scp` — check for a direct IP FIRST** | **Deploy with Public IP + TCP 22, then use the direct line, not the proxy.** The pod exposes `RUNPOD_PUBLIC_IP` and `RUNPOD_TCP_PORT_22` in its env (read them over the proxy: `env \| grep -i runpod`). With `ssh -p <port> root@<ip>`, plain `scp` works. *(measured: **293 MB in ~2 min**; the same over hex-on-TTY would be ~590 MB of text and take hours.)* Only fall back to gzip+hex (`_paint_put.py` / `_mesh_pull_glb.py`) when no public IP exists. After transfer: `test -s`, size in tens of MB, not 0. |
| Direct SSH is also **far cleaner** | The TTY proxy garbles output with escape codes and line-wrap, which corrupts long heredocs. On the direct line, `ssh host 'cmd'` gives clean output. **Ship non-trivial patches as a file via `scp` and run them** — do not paste long Python through a TTY heredoc. |
| ⚠️ `pkill -f <pattern>` can **kill your own SSH session** | `pkill -f` matches full command lines, including the remote shell running your script if the pattern appears in it. Killed the session (exit 255) on the validated run. Use the bracket trick — `pkill -f "[b]ake_pipeline.py"` — or an explicit PID. |
| ⚠️ `ssh host 'cmd'` does **not** load RunPod's env | Non-interactive/non-login shells have **no** `RUNPOD_POD_ID` / `RUNPOD_API_KEY`, so `runpodctl` fails with `API key not found` and `accepts 1 arg(s), received 0`. Use the **TTY session** (`pod.py`) for `runpodctl`, or pass the pod id explicitly after `runpodctl config --apiKey "$RUNPOD_API_KEY"`. |
| CRLF | A Windows-edited `.sh` breaks bash (`$'\r'`). First byte of `trellis2_setup.sh` must be `#` (`0x23`), not `0x0d`; `sed -i 's/\r$//'` after upload. Do not "debug bash." |
| `groups: cannot find name for group ID` / `nohup … Terminated` | RunPod noise / HUP on disconnect. Ignore the first; `pgrep` after reconnect for the second. |

---

## §8 — Bug encyclopedia (search here FIRST when something "looks new")

### Ops / disk / pod

| Symptom | Cause | Fix |
|---------|-------|-----|
| GTX 1050 / 4 GB "not enough" | local PC | 24 GB mesh / 40 GB paint pod |
| `nvidia-smi` not found (Windows) | not on PATH | `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe` |
| `container create: exit status 1` | custom image/start/volume on Community; billed $0 | official PyTorch **devel** template, no start command, different GPU/region, Secure Cloud on 3rd try |
| Overlay `ENOSPC`, 25 GB ckpt won't fit | 30 GB container | **80 GB container** (§3); do not add a volume as the fix |
| `df -h /workspace` shows `1.0P` | geesefs fake capacity | container disk + `du`, never `df` on geesefs |
| ckpt `torch.load` takes 20–30 min | reading 25 GB **through the network volume** | don't use a volume; if you must, copy the ckpt to the container first, then load |
| `chmod +x` won't stick / `libsycl.so.7` truncated / venv `OSError` / 0-byte HF snapshots | anything executable or symlinked on geesefs | put venv, Blender, MVPainter, ckpt on the **container**; blobs-only on a volume if used |
| Can't stop the pod from here | no RunPod API key on this PC | user stops it in the dashboard; never claim `runpodctl` works here |

### Mesh (TRELLIS / CuMesh)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `o_voxel` won't compile, no Eigen | missing headers | `libeigen3-dev` + `CPATH=/usr/include/eigen3`. **Solved — do not re-debug.** |
| second torch / disk fills | `pip install xformers` | don't; also delete any `flash-attn \|\| xformers` fallback |
| flash-attn compiles forever | building from source | prebuilt wheel 2.8.3.post1 `--no-deps` |
| `nvcc` missing / CUDA version mismatch | non-devel image / PATH / torch-vs-nvcc | devel image; `CUDA_HOME`; `_check_cuda_version=lambda…` |
| DINOv3 401 / "awaiting review" | agreeing ≠ approval; token not on this pod | wait for real grant; `hf auth login` on the box |
| RMBG gated / JPEG hits `rembg_model(input)` | opaque input → rembg branch | `trellis2_patch.py` + `_mesh_skip_rembg_restart.py`; `--no_rembg` does NOT skip TRELLIS rembg |
| generate+remesh die together | 3.4 M-face soup, CuMesh native abort (not OOM) | isolated remesh in a fresh process; `free`/`dmesg` to confirm not OOM |
| `1024` OOM | VRAM | script retries `512`; stay 24 GB-class |
| GLB unreadable in Windows 3D Viewer | `extension_webp=True` | export `extension_webp=False` |
| `trellis2_manual_remesh.py` GLB has no UVs | `trimesh.export` only | use `export_isolated_remesh` |

### Paint (MV-Painter / Blender / EXR)

| Symptom | Cause | Fix |
|---------|-------|-----|
| Blender `--version` OK but render writes nothing | binary-only/truncated Blender, or a Python crash (Blender exits 0) | full `/opt/blender` tree + GATE_B9 (EXR files), never `--version` |
| `import cv2` in Blender dies / EXR reads `None` | OpenCV without EXR in Blender's Python | `pip opencv-python-headless` into Blender's python; `OPENCV_IO_ENABLE_OPENEXR=1` before `import cv2` |
| `depth/000.exr` missing, `BLENDER_RC 0` | glTF `loglevel=None` from `debug_value=256` | patch `debug_value=0`, `loglevel=0` on both imports, addon `set_debug_log` returns `logging.INFO` |
| `UnboundLocalError` / `depth/001.exr` missing after view 0 | None-guard left `normal_unit16` unset | the proven fallback block in §4 P3 (bpy `images.load`) |
| infer returns in 0 s for a stem | leftover/0-byte `*_6view.png` | delete all `*_6view.png` before infer |
| a pair silently skipped | PNG missing / 0-byte / wrong stem (`replace("glb","png")`) | `test -s` both, same stem, PNG not JPG |
| `scripts/blender_render_ortho.py` not found | wrong cwd | `cd /opt/MV-Painter/MVPainter` |
| `JSONDecodeError` / 0-byte `config.json` | geesefs symlink snapshots | don't use the volume; download to the container |
| `huggingface_hub` vs `diffusers 0.20.2` | hub API drift | pin `huggingface_hub==0.25.2` |
| 24 GB card OOM on infer | 25 GB UNet in VRAM | 40 GB+; no CPU-offload plan |
| GPU 0 % for 20 min after pipeline 7/7 | `torch.load` of 25 GB off disk; VRAM climbing | wait (only for this step); do not restart |
| `Loading custom unet …` frozen | tqdm `\r` | count `*_6view.png` files, not log text |

### Bake / UV

| Symptom | Cause | Fix |
|---------|-------|-----|
| ~1 h 10 min CPU, GPU idle | `xatlas.parametrize` recomputes UVs the mesh already has | skip xatlas when `mesh.visual.uv` exists (§5); confirm via `UV_REUSE` |
| low-quality texture | baked `blender_low.obj` / 30 k | patch bake to full `blender.obj` |
| bake on the 40 GB pod | wrong machine | local NVIDIA or a small CUDA pod. *(On the validated run bake ran on the paint pod because it was already up — acceptable **only** because the 6-views were already pulled and the run was parallel + bounded.)* |
| `ModuleNotFoundError: cupy` at bake start | `voronoi.py` imports cupy at module load | `pip install cupy-cuda12x` **before** bake (§5) |
| `numpy.core.multiarray failed to import` after downgrading numpy | cupy 14.x needs numpy ≥ 2; the 1.26.3 pin is **paint-only** | bake: `numpy>=2.0,<2.6` + `scipy>=1.14` |
| `ImportError: libc10.so` importing `custom_rasterizer` | torch not imported first | `import torch` first — **not** a failed build |
| bake silent for 25 min, GPU 0 %, no GLB | `bake_pipeline` writes nothing until the GLB; work is single-core CPU | **do not kill** — check CPU-time delta (§1). Run stems in parallel (§5) |
| patched the normals but bake still slow | the same block exists in **`render_normal` and `back_project`**; `replace(...,1)` hits `render_normal`, which bake never calls | patch all occurrences; verify by enclosing function |
| grep assertion fails after a correct patch | your own **comment** mentions the old function name | assert on the *call* (`trimesh.geometry.mean_vertex_normals(`), not the bare name |

---

## §9 — Stale helper scripts (in the Boss repo root — do NOT trust blindly)

Dozens of `_paint_*.py` / `_mesh_*.py` / `_pod_*.py` are one-off scratch from the debugging days. Their `HOST=`
is dead and several **skip the gates or point at geesefs**. Do not run one because its name sounds right.

**Never run:** `_paint_fix_blender.py`, `_paint_blender_libs.py` (139 MB fake / geesefs-symlink Blender),
`_mesh_keep_going.py` (restarts on a dead host), `_pod_install_trellis2.sh` (old `flash-attn||xformers`),
`_paint_start_infer.py`, `_patch_debug.py`, `_paint_kick*.py`, and anything that `nohup … infer_multiview` without
running GATE_B9 first.

**Reference only (read the logic, don't launch):** `_paint_pod.py`/`_mesh_pod.py`/`_pod_exec.py` (SSH wrappers —
update `HOST` each pod), `_paint_put.py`/`_mesh_pull_glb.py`/`_mesh_upload.py` (hex transfer), `_pod_mem_monitor.sh`,
`gpu_box/trellis2_*` (the durable mesh code).

The one-off scripts are safe to delete once you trust this runbook; nothing in the pipeline imports them.

---

## §10 — Timings, incidents, changelog

### Measured timings (quote these; do not invent)

| Event | Time |
|-------|------|
| TRELLIS `1024_cascade` generate | minutes–tens of minutes (24 GB) |
| Isolated CuMesh remesh + `to_glb(remesh=False)` | minutes (still runs xatlas ~2 min) |
| MV-Painter pipeline load (7/7) from warm cache | ~5 min |
| 25 GB ckpt `torch.load` **from local disk** | ~2–5 min |
| 25 GB ckpt `torch.load` **through a network volume** | 20–30 min (do not do this) |
| Blender ortho, one ~700 k mesh | under ~2 min |
| GPU 75-step paint, per stem | **~38 s** (not 15 min) |
| Six stems, one live process | 1× UNet load + 6× (Blender + ~38 s) |
| `xatlas` unwrap on full mesh (A6000, un-skipped) | **1 h 10 min** — skip it (§5) |

### Incident → section

Legal (Hunyuan/SF3D) §2 · deploy/`container create` §3 · Eigen/xformers/flash-attn/DINOv3/rembg §6 · generate+remesh
death §6 · disk `ENOSPC`/geesefs/ckpt-load §3+§8 · Blender exit-0 / `debug_value=256` / EXR-None §4 P3 · silent
PNG skip / 0-byte 6-view §4 P4 · xatlas hour / `blender_low` §5 · kill-already-stopped-pod / regenerate-done-meshes §0.

### Validated run — 2026-09-20 (what actually happened)

One A6000 (46 GB) pod, 30 GB container + existing network volume, **~2 h total including debugging**, six
textured GLBs delivered. Gates caught three real problems **before** they could cost the expensive step:

- `GATE_B9` showed `EXR_BPY_FALLBACK` firing **6/6 views** — without patch #5 the run dies at view 0, exactly
  as it did all week. The patch is load-bearing, not defensive.
- Missing `cupy` found **during the ckpt load** (dead time) — would otherwise have killed bake after paint.
- `libc10.so` looked like a broken build; it was import order. Cost ~2 min because it was measured, not assumed.

Mistakes made during the run, recorded so they are not repeated:

1. Baked on the 40 GB pod, against this file's own rule. The justification (xatlas skipped) was true but
   incomplete — bake was slow for an unrelated reason. Mitigated only because the 6-views were pulled first.
2. Patched `render_normal` instead of `back_project`, then **dismissed the assertion that caught it**. ~20 min lost.
   *The check was right and was overridden.*
3. Set a 15-min "stop threshold" on a tool with no progress output, and nearly killed six healthy bakes that
   finished minutes later. → the §1 correction.

Ordering that worked and should be repeated: **upload during install**, **diagnose during the ckpt load**,
**pull the 6-views the moment they exist** (they are the only artifact needing a 40 GB GPU — once local, the
pod is disposable and bake can run anywhere).

### Changelog

- **2026-09-20 rewrite.** Re-verified every number against the repo and MV-Painter/TRELLIS.2/HF upstream. Fixed the two
  contradictions that made the prior version un-followable: (a) the paint path now uses an **80 GB container and no
  network volume**, removing the geesefs class of bugs (the volume was only a workaround for a too-small container);
  (b) MVPainter lives on the container so `render_temp` is relative-and-local — no `/opt/render_temp` redirect, no
  ckpt-copy step, matching the setup that actually produced a 6-view. Collapsed the duplicated encyclopedia and the
  10-copy check log into one place. The `_checks/PROCESS_checkNN.md` copies are superseded scratch.
