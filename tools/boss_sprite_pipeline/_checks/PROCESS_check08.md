# CHECK 8 of 10 — FAQ: TRELLIS.2 mesh + MV-Painter 6-view

Standalone reconstruction. Every heading is a question an agent asked (or should have asked) before burning a pod. Answers are commands and paths, not vibes.

**Session facts, do not re-litigate**

- User **already stopped the 40GB paint pod**. Do not start it. There is no RunPod API key here; `runpodctl` on a box cannot terminate anything.
- **All six remesh GLBs are already on this PC.** Do not remesh. Do not clone TRELLIS.2 again for these six.
- Legal: **no Hunyuan3D and no Hunyuan-Paint.** Same Tencent Hunyuan 3D 2.1 Community License (EU / UK / South Korea excluded; covers weights **and** output). Mesh = TRELLIS.2 + isolated CuMesh. Paint = MV-Painter (`shaomq/MVPainter`, Apache-2.0). Do not “fix” a crash by switching backends.

SSH from this Windows machine is always the `ppp` key with a TTY:

```powershell
ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25 `
  -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp `
  <pod-user>@ssh.runpod.io
```

`id_ed25519` is **not** on this PC. Paste `ppp.pub` into RunPod SSH keys on a new pod. Do not paste the private key or a Hugging Face token into chat.

---

## Can I use Hunyuan? Hunyuan3D? Hunyuan-Paint? “Just this once from Europe?”

No. All three are the same ban.

`LEGAL_LIABILITY.md` rejected **Tencent Hunyuan3D-2 / 2.1** because the community license excludes the **European Union, United Kingdom, and South Korea**. The grant is territory-only and covers **weights and Output**. Running it from Europe, or shipping a Hunyuan mesh/paint from here, is unlicensed.

**Hunyuan-Paint / Hunyuan3D-Paint / `hy3dgen` texgen** is the same Tencent Hunyuan 3D 2.1 Community License. Same territory. Same “output” coverage. A pretty gallery is not a license.

If a plan, clone URL, Docker image, or Hugging Face Space is `Tencent-Hunyuan`, `Hunyuan3D`, `Hunyuan-Paint`, or `hy3dgen`: delete the idea. Do not download “to compare.”

Paint we actually use: **MV-Painter**, Apache-2.0, image + mesh, **no text prompt**.

```text
https://github.com/amap-cvlab/MV-Painter
https://huggingface.co/shaomq/MVPainter
```

---

## TRELLIS v1 was rejected — so why did we run TRELLIS.2?

Different jobs.

`LEGAL_LIABILITY.md` rejected **Microsoft TRELLIS (v1)** as the *ship* backend: Microsoft code/weights are MIT, but the official textured-GLB path pulls NVIDIA `nvdiffrast` / `nvdiffrec` with non-commercial flags.

**TRELLIS.2** (`microsoft/TRELLIS.2-4B`) is the mesh factory we actually ran. Weights MIT. Official export still pulls those NVIDIA libs. That is why every generate command includes **`--skip-texture`**. We do **not** ship TRELLIS PBR. We remesh with isolated CuMesh, export geometry (+ the UVs `to_glb` still builds), then paint with MV-Painter.

Do not “fix” TRELLIS export legality by switching to Hunyuan. Do not run `Trellis2TexturingPipeline` as the paint we ship.

Stable Fast 3D (`raw.glb`) was the earlier pancake. Stability Community License: free commercial use under **USD 1,000,000** annual revenue; keep records; do not assume grandfathering. SF3D is historical, not the current factory.

---

## Where are the meshes? Did yesterday’s 40GB produce paint?

Meshes: **yes, local, all six.** Paint: **no 6-view from that 40GB session.** Zero. User stopped the box.

```text
C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants\<name>\mesh.glb
```

| name | typical size |
|---|---|
| `gpt2_front_paint` | ~45.3 MB |
| `gpt2_front_ink` | ~45.2 MB |
| `gpt2_front_sculpt` | ~43.6 MB |
| `nano2_concept_art` | ~45.0 MB |
| `nano2_2d_illustration` | ~45.1 MB |
| `nano2_3d_render` | ~42.9 MB |

Sense-check before any pod:

```powershell
Get-ChildItem "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants\*\mesh.glb" |
  Select-Object FullName, Length
```

Each file must be **> 1_000_000 bytes**. These are TRELLIS `1024_cascade` → isolated CuMesh remesh (band=1, project=0, ~1M faces) → `to_glb remesh=False` → `--skip-texture`. **Not** Blender remesh. **Not** the 256-res debug `demon_from_front_manual_remesh.glb`.

Matching stills (PNG stem **must** equal GLB stem):

```text
...\concept\round2\<name>.jpg          # TRELLIS input (JPEG, no real alpha)
...\concept\round2_png\<name>.png      # MV-Painter input (copy, same stem)
```

Older one-off artifacts (do not mix into the six):

```text
generated\bosses\demon\mesh\demon_from_front.glb              # ~48 MB remesh
generated\bosses\demon\mesh\demon_from_front_manual_remesh.glb # 256-res debug
generated\bosses\demon\mesh\demon_painted.glb                 # crushed ~30k / 54k faces — DO NOT SHIP
generated\bosses\demon\mesh\demon_painted_full.glb            # full remesh paint (~827k verts)
generated\bosses\demon\mesh\raw.glb                           # SF3D pancake
generated\bosses\demon\concept\front.png                      # keyed standing still
```

Next paint session: upload those six `mesh.glb` + six `round2_png/*.png`. Do not regenerate geometry.

---

## How do I SSH? Why `-tt`? Why `ppp`? Why not `scp` / `BatchMode`?

RunPod’s `user@ssh.runpod.io` proxy **requires a TTY**. Without `-tt`, the session hangs on the “Enjoy your Pod” banner or dies with no shell.

```powershell
ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25 `
  -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp `
  <pod-user>@ssh.runpod.io
```

Python helpers (`_paint_pod.py`, `_mesh_pod.py`, `_pod_exec.py`) do the same: `ssh -tt`, sleep **~6 s** for the banner, then write `cmd\nexit\n` on stdin. Direct `ssh -T` / `BatchMode=yes` + a command argv worked on some older `root@IP -p PORT` pods and **fails** on the proxy.

`ppp` is the key that actually exists here. `~/.ssh/id_ed25519` does not. User-facing SSH lines that say `-i ~/.ssh/id_ed25519` still mean **this** file.

**Do not `scp` GLBs over the proxy as the default.** It flakes. Use gzip+hex over the same `-tt` session (`_mesh_pull_glb.py`, `_paint_put.py`, `_mesh_upload.py`). Strip CRLF on every script you drop:

```bash
python3 -c "from pathlib import Path; p=Path('/workspace/gpu_box/trellis2_setup.sh'); p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n').replace(b'\r',b'\n'))"
# or
sed -i 's/\r$//' /workspace/gpu_box/trellis2_setup.sh /workspace/gpu_box/trellis2_run.py /workspace/gpu_box/trellis2_patch.py
```

Windows `set: pipefail` / `$'\r': command not found` = CRLF. Fix bytes, then rerun. Do not “debug bash.”

Hosts change every deploy. Examples from yesterday (dead unless the user says they are up):

| job | helper | host |
|---|---|---|
| 24GB mesh | `_mesh_pod.py` | `4lmqwpwp84x1qs-6441135a@ssh.runpod.io` |
| 40GB paint | `_paint_pod.py` | `luc0g32c1tmgou-64410d8b@ssh.runpod.io` |
| earlier A6000 `-T` | `_pod_a6000.py` | `3k2fy27ejbp6np-64411158@ssh.runpod.io` |
| earlier paint `-tt` | `_pod_exec.py` | `pqnmasqgnexpbd-644112d3@ssh.runpod.io` |
| older direct | port `22156` | `root@194.68.245.170` |

Always use the SSH line the user just pasted. Always `-i ppp`. Always `-tt` on `ssh.runpod.io`.

---

## Why 40GB? Is this for remesh? For Blender? For xatlas?

**40GB+ VRAM is only so MV-Painter’s UNet can sit in GPU memory.** Official infer loads `unet_w_controlnet/v29_25000.ckpt` (~**25.3 GB**). A 24GB card OOMs that checkpoint. A6000 48GB is fine. PRO 6000 **MIG 24GB is still 24GB** — same class as last night’s failure, reject it.

Not remesh. Not xatlas. Not “Blender is slow on a 1M mesh.” Those are different machines.

| step | machine | why |
|---|---|---|
| TRELLIS.2 `1024_cascade` + isolated CuMesh | **24GB-class** (A5000 / 3090). Container disk **≥60 GB**. | Microsoft: “NVIDIA GPU with at least 24GB.” `1024_cascade` OOM is a **toy** GPU problem. |
| MV-Painter `infer_multiview` (UNet in VRAM + 75-step generate) | **40GB+** (A6000 48GB). 50GB network volume that already has the blobs. Overlay ~30GB for Blender/venv. | 25.3 GB ckpt must live in VRAM. |
| Blender ortho inside `infer_multiview` | Same 40GB box, **only because the official script will not paint without it**. CPU, minutes. | Do not rent 40GB *for* Blender. |
| UV / xatlas / bake | **This Windows PC** (CPU unwrap). Bake on local NVIDIA, or a **small** CUDA box. | Hour-scale xatlas on 930k faces burned the A6000. Never again. |
| Linode | Unwrap only | No CUDA. Tiny 1–2 vCPU can be **slower** than the A6000 xatlas hour. |
| Local GTX 1050 **4096 MiB** | Fox/Blender sprite test only | Too small for TRELLIS, Hunyuan, MV-Painter UNet. |
| 16 GB Ada | Do not | TRELLIS.2 official path and MV-Painter ckpt both lose. |

CPU-offload of the 25GB UNet is **not the plan**. Overnight “workaround” on a 24GB A5000 already cost a night and produced nothing. Do not repeat.

---

## Why not remesh here (on the 40GB)? We had remesh problems, right?

Remesh **never needed 40GB**. The problems were:

1. `1024_cascade` CUDA OOM on a **too-small** GPU → retry `pipeline_type="512"` after `torch.cuda.empty_cache()`. Stay 24GB-class.
2. CuMesh abort / process **Killed** during `remesh_narrow_band_dc` **in-process** with generate. That is why `trellis2_run.py` does **isolated remesh** after freeing the i23d pipeline, and why `trellis2_manual_remesh.py` exists.
3. Guessing “host OOM / GPU OOM” from a silent death without `dmesg`. Check, don’t guess.

Meshes for these six **already exist locally**. Do not remesh on any pod for this batch.

If you ever remesh a **new** still, do it on 24GB:

```bash
export CUDA_HOME=/usr/local/cuda
export PATH=/usr/local/cuda/bin:$PATH
export HF_HOME=/workspace/.cache/huggingface
export HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa
export SPARSE_ATTN_BACKEND=flash_attn
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/usr/include/eigen3
export CPLUS_INCLUDE_PATH=/usr/include/eigen3
export OPENCV_IO_ENABLE_OPENEXR=1

/workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_run.py \
  --image /workspace/in/gpt2_front_paint.jpg \
  --out-dir /workspace/out \
  --name gpt2_front_paint \
  --skip-texture
```

Default remesh is **on**. `--no-remesh` is debug only.

---

## Why 15 min? Was GPU paint actually 15 minutes? Why did a “1h15” run happen?

Three different clocks got mashed into one sentence. They are not the same.

**Measured once (small/crushed mesh, weights already hot):** Blender ortho ~**30 s**, GPU 75-step paint ~**38 s**. The hour was **not** that.

**Quoted “~15 min”:** one mesh’s GPU generate **after the UNet is already in VRAM**, on a warm `/opt/hf`. It is **not** “the whole 40GB job.” It is **not** six meshes. It is **not** xatlas.

**Old A6000 ~1h15:** most of that hour was **xatlas.parametrize on ~930k faces** during official bake, GPU idle. Official MV-Painter **recomputes UVs even when the remesh already has them** (~708k `vt`). People report 30–60 min above ~400k faces; 1.3M-face logs look frozen. **Do not bake/unwrap on 40GB.**

**Geesefs UNet load:** 24GB ckpt **on the volume ≠ in VRAM**. `torch.load` off FUSE is **~20–30 min**, GPU at 0%, VRAM climbing 2→25 GB. Looks “parked.” It is not hung. Do not restart it.

**Pipeline `from_pretrained` 7/7** from warm `/opt/hf`: ~**5 min**. First component looks stuck because tqdm uses `\r`. `tail` without replacing `\r` lies.

**Six meshes, honest 40GB wall clock if infer actually runs:** one UNet load + 6×(Blender ortho of the 1M remesh + generate). Restarting after a Blender crash **re-pays the 20–30 min load**. That is how two hours produced **zero** `*_6view.png`.

Do not tell the user “15 min and we’re done” unless the UNet is in VRAM **and** Blender already wrote `depth/000.exr`.

---

## Can I bake on A6000? Should I unwrap on the 40GB while I wait?

No. Bake/unwrap on 40GB is how we burned an hour of A6000 on CPU.

Order is locked:

1. Blender ortho (normals/depth) — `infer_multiview` will not paint without this.
2. 75-step `infer_multiview` — the only reason 40GB exists.
3. UV/bake — **after** `*_6view.png` exists. Skip xatlas if UVs exist (they do, from TRELLIS `to_glb`). Full mesh, **not** 30k decimate.

`demon_painted.glb` (~54k faces / `blender_low.obj` 30k) was the crushed bake. `demon_painted_full.glb` kept the remesh (~930k faces / ~827k verts; verts went up because unwrap duplicates seams). **Do not decimate to 30k.**

Local bake when a real 6-view exists. Linode is CPU-only: fine for unwrap, useless for TRELLIS / generate / CUDA bake.

---

## Why is Blender `--version` not enough?

Because Blender 4.2 can print a version, exit **0**, and still write **nothing**.

`blender --version` does not prove:

- the binary is the overlay copy (`/opt/blender/blender`), not a geesefs tree
- `*.so` are real files, not 0-byte symlink stubs (`libsycl.so.7`)
- Blender’s own Python has OpenCV **and** OpenEXR
- glTF import of **this** remesh GLB works
- `bpy.app.debug_value` is not `256`

**Required smoke, every restart, before `infer_multiview`:**

```bash
test -x /opt/blender/blender
file /opt/blender/blender
ls -l /opt/blender/lib/libsycl.so.7 /opt/blender/4.2
/opt/blender/blender --version | head -2

export OPENCV_IO_ENABLE_OPENEXR=1
BPY=/opt/blender/4.2/python/bin/python3.11
OPENCV_IO_ENABLE_OPENEXR=1 $BPY -c "import os; os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'; import cv2; print('CV2_OK', cv2.__version__)"

# REAL remesh, not Suzanne
/opt/blender/blender --background -Y --python-expr \
  "import bpy; bpy.app.debug_value=0; bpy.ops.import_scene.gltf(filepath='/workspace/mvpaint_in/glbs/gpt2_front_ink.glb', merge_vertices=True, loglevel=0); print('GLTF_OK', len(bpy.data.objects))"
```

If that last line is not `GLTF_OK`, **do not load the 25GB UNet.** Official `infer_multiview` does not check Blender’s return code. You will pay 20–30 min of geesefs `torch.load`, Blender will write nothing, then Python dies on missing `depth/000.exr`. That is yesterday’s two-hour bill.

---

## Why did infer skip a mesh? Why did it return in 0 s?

Two silent skips in official `infer_multiview.py`. Both look like “it ran.”

**1. Name match is a string replace, not a suffix.**

```python
base_name.replace("glb", "png")
```

`gpt2_front_paint.glb` → looks for `gpt2_front_paint.png`. A `.jpg` on disk is **not** that file. Infer skips with no useful error. Copy JPGs to PNG **same stem**:

```powershell
# local
C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\concept\round2_png\<name>.png
# pod
/workspace/mvpaint_in/glbs/<name>.glb
/workspace/mvpaint_in/imgs/<name>.png
```

**2. Leftover `*_6view.png` (including empty) short-circuits.**

```python
if os.path.exists(...6view.png):
    return
```

A 0-byte leftover from a crashed run = **0 s success**. Delete empty/partial 6-views before restart:

```bash
find /workspace/mvpaint_out -name '*_6view.png' -ls
find /workspace/mvpaint_out -name '*_6view.png' -size -1k -delete
```

Watcher trap: `rglob('*6view.png')` counts **any** match, including junk and `camera/` trees. `SIXVIEW_COUNT > 0` is not “paint worked.” Open the PNG; it must be a real 6-panel image.

---

## Why `JSONDecodeError`? Why `Unterminated string`?

Hugging Face snapshot **pointers on geesefs were 0-byte files**. `model_index.json` and other tiny JSON in

```text
/workspace/.cache/huggingface/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d/
```

are empty. `from_pretrained` tries to `json.loads` them → `JSONDecodeError: Unterminated string` / invalid JSON. The **36 GB blobs are fine**. Do not re-download weights.

Sense-check (must already be tens of GB before any fetch):

```bash
du -sh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs
find /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs -type f -size +1M | wc -l
find /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/snapshots -type f -size 0 | head
head -c 200 /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d/model_index.json; echo
```

Rebuild **pointers on overlay**, blobs stay on the volume:

```bash
export HF_HUB_ENABLE_HF_TRANSFER=0 HF_HOME=/opt/hf
mkdir -p /opt/hf/hub/models--shaomq--MVPainter/refs
ln -sfn /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs \
        /opt/hf/hub/models--shaomq--MVPainter/blobs
SNAP=/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d
rm -rf "$SNAP"; mkdir -p "$SNAP"
echo 85a9cb12b444a73ba922ac44fd198e8de12f8a9d > /opt/hf/hub/models--shaomq--MVPainter/refs/main
```

Then symlink each tree path to `blobs/<lfs oid>`. Skip the extra ~15GB `unet_w_controlnet/*.safetensors` if `v29_25000.ckpt` is present. Fetch only missing **tiny** `*.json` / `*.txt` (KB). Confirm `model_index.json` starts with `{`.

`HF_HOME=/opt/hf` for infer so Python does not parse the 0-byte volume snapshots.

---

## Why `Killed`? Is this OOM? GPU? Host RAM? Disk?

`Killed` is not a diagnosis. Read the killer.

```bash
dmesg -T 2>/dev/null | grep -iE 'killed process|out of memory|oom-kill|segfault' | tail -n 20
awk '/MemTotal:|MemAvailable:|MemFree:|Cached:|SwapFree:/ {print}' /proc/meminfo
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
# if the pid still exists:
awk '/VmRSS:|VmSize:|VmPeak:/' /proc/$PID/status
df -h / /workspace /opt
```

What we actually saw:

| symptom | what it was | what it was not |
|---|---|---|
| Python `torch.cuda.OutOfMemoryError` on `1024_cascade` | GPU VRAM. Retry `512`. | Host RAM. |
| Process `Killed` in CuMesh remesh, GPU not full | In-process remesh abort / host pressure. Isolate remesh; `faulthandler`; `CUDA_LAUNCH_BLOCKING=1` on the manual runner. | “Need 40GB for remesh.” |
| `ENOSPC` / `No space left on device (os error 28)` / Hugging Face `expected 25327.64 MB, free 14480.68 MB` | **Container disk 30GB.** | VRAM. GPU was idle 0 MiB. |
| `Killed` during `pip install xformers` | Second PyTorch filling 30GB overlay. | Model OOM. |
| Job 4 RSS ~18 GB on a 251 Gi host | Normal TRELLIS load spike. Peak finished mesh ~23 GB. | Host OOM. Do not “fix RAM.” |
| MV-Painter on 24GB A5000 | UNet does not fit in VRAM. | A disk trick will not save it. |

`trellis2_run.py` and `_pod_mem_monitor.sh` print `MEM <tag> rss_mb=… cuda_alloc_mb=…`. Use them. `_pod_crash_digest.sh` greps `Killed` / `Aborted` / `Fatal` and tails `dmesg`.

Do not guess remesh OOM. Yesterday’s “maybe it is RAM” loop on a 251 Gi box was false.

---

## Why did the 30GB overlay die? Why did someone say 80GB? Why 50GB volume?

Three different disks. Mixing them is how “80” and “40” fought for an hour.

**VRAM** — GPU. 24GB mesh / 40GB+ paint.

**Container / overlay disk** (`df -h /`, often ~30GB default) — OS, `/opt/blender`, `/opt/mvpaint-venv`, `/opt/hf` pointers, `/opt/render_temp`. Ephemeral. Dies with the pod.

**Network volume** (`/workspace` when attached at **deploy**) — geesefs/FUSE. Yesterday: **50GB**, ~**36–38G used** by `models--shaomq--MVPainter/blobs`, including the **24G** `v29_25000.ckpt`. You pay the volume monthly even with no GPU (`$3.50/mo` on that 50GB). `df` on geesefs can **lie** (1 petabyte). Trust `du -sh` of the blob dir.

“80GB” was padding for **one disk holding OS + 13GB partial cache + 25.3GB ckpt + Blender**. Once weights live on the **50GB volume**, you do **not** need an 80GB container. You need:

- 40GB+ **VRAM**
- **50GB volume already containing the blobs** (sense-check `du` first)
- ~30GB overlay for Blender + venv
- **Do not** put TRELLIS (~20GB) on that 50GB volume. 40GB used + 20GB mesh cache does not fit.

You **cannot** attach a volume to a running pod. Terminate the empty one. **Configure Pod with volume** → same datacenter (EUR-IS-1 for that volume) → A6000 → Deploy. A live “nothing mounted” pod will never grow.

**One volume, one pod.** Two pods on the same geesefs volume lock/corrupt it.

30GB overlay + `pip install xformers` (unconstrained) = second torch, disk full. Mesh pod wants **≥60GB container disk** if there is **no** mesh volume.

---

## Why can’t I `chmod +x` Blender on `/workspace`? Why are `.so` files 0 bytes?

geesefs.

- `chmod +x /workspace/blender/blender` does nothing useful.
- Library **symlinks become 0-byte files** (`libsycl.so.7`). `blender --version` may still print; loading `lib` then dies.
- Volume venv **cannot write binaries** reliably. Put `/opt/mvpaint-venv` on overlay.
- Last session’s `/workspace/MV-Painter` as a **symlink into `/opt`** vanished with the old overlay. Code must be a **real tree or GitHub tarball on the volume**:

```bash
if [ ! -f /workspace/MV-Painter/MVPainter/infer_multiview.py ]; then
  rm -f /workspace/MV-Painter
  curl -L --fail --retry 5 --retry-delay 2 -o /tmp/mvp.tgz \
    https://codeload.github.com/amap-cvlab/MV-Painter/tar.gz/refs/heads/main
  tar -xzf /tmp/mvp.tgz -C /tmp
  mv /tmp/MV-Painter-main /workspace/MV-Painter
  rm -f /tmp/mvp.tgz
fi
```

Keep a **Blender `.tar.xz` on the volume**; **extract to `/opt/blender` on overlay** every boot:

```bash
# overlay extract (4.2.4 LTS used when 4.2.9 failed)
curl -L --fail --retry 5 -o /tmp/blender.tar.xz \
  https://download.blender.org/release/Blender4.2/blender-4.2.4-linux-x64.tar.xz
tar -xf /tmp/blender.tar.xz -C /tmp
rm -rf /opt/blender
mv /tmp/blender-4.2.4-linux-x64 /opt/blender
chmod +x /opt/blender/blender
ln -sfn /opt/blender /workspace/MV-Painter/blender-4.2.9-linux-x64
```

If you copy from a broken volume tree, also link real `.so`:

```bash
# only if the volume tree still has intact libs — yesterday it did not
export LD_LIBRARY_PATH=/opt/blender:/opt/blender/lib:${LD_LIBRARY_PATH:-}
```

Infer must call **`/opt/blender/blender`**, not `../blender-4.2.9-linux-x64/blender` if that path is the volume.

---

## What is the glTF `loglevel=None` / `debug_value=256` crash?

Blender 4.2 importer: `IMPORT_SCENE_OT_gltf.loglevel expected an int, not None`.

Passing `loglevel=0` on **our** `bpy.ops.import_scene.gltf(...)` is **not enough**. The addon overwrites it with `set_debug_log()`, and `blender_render_ortho.py` sets `bpy.app.debug_value=256`, which that function **does not handle**, so it returns `None`.

Symptoms: Blender **exit 0**, no objects, no `depth/000.exr`, then Python `FileNotFoundError` on the EXR.

Fix **both**:

```python
# scripts/blender_render_ortho.py
bpy.app.debug_value = 0   # was 256
bpy.ops.import_scene.gltf(..., merge_vertices=True, loglevel=0)
```

```python
# /opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py
# after the debug_value==4 branch, add:
    return logging.INFO
```

That is `_patch_debug.py` / `_paint_gltf_fix.py`. Run the GLTF smoke **before** UNet load. Yesterday’s second infer patched OpenCV/path and **left `debug_value=256`**, so we paid another full load for the same crash.

Also set:

```python
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
# before import cv2 in blender_render_ortho.py
```

and install OpenCV **into Blender’s Python**, not only the venv:

```bash
/opt/blender/4.2/python/bin/python3.11 -m ensurepip --upgrade || true
/opt/blender/4.2/python/bin/python3.11 -m pip install -q opencv-python-headless
```

EXR depth channel is **`V`** (`depth_exr_to_png(..., depth_channel="V")`). If `cv2` returns `None` on the HDRI/normal EXR, patch the `normal_unit16 = (normal * 65535)` line to print `EXR_READ_FAIL` instead of crashing. Confirm HDRI exists:

```bash
ls -lh /workspace/MV-Painter/MVPainter/scripts/overcast_soil_puresky_4k.exr
```

Write renders to **overlay**: `--output_dir /opt/render_temp`. geesefs `render_temp` is a trap. Patch every `"render_temp"` in `infer_multiview.py` to `/opt/render_temp`, and **raise if Blender `returncode != 0`**. Official code does not.

`cd` **must** be `/workspace/MV-Painter/MVPainter` so `scripts/blender_render_ortho.py` resolves. Wrong cwd → `../blender_render_ortho.py` / script not found.

```bash
cd /workspace/MV-Painter/MVPainter
export HF_HOME=/opt/hf
export HF_HUB_ENABLE_HF_TRANSFER=0
export PYTHONUNBUFFERED=1
export OPENCV_IO_ENABLE_OPENEXR=1
/opt/mvpaint-venv/bin/python -u infer_multiview.py \
  --input_glb_dir /workspace/mvpaint_in/glbs \
  --input_img_dir /workspace/mvpaint_in/imgs \
  --output_dir /workspace/mvpaint_out \
  --geo_rotation -90 \
  --no_rembg
```

`--no_rembg` always (stills already cut). `--geo_rotation -90` is the value we used. Seed in the custom path was **12**, steps **75**, `float16`. Combined 6-view tile order: `000, 005, 001, 004, 002, 003`.

`rembg` / `numpy` can still get **imported** even with `--no_rembg`. If that import explodes, it is not “needs rembg weights.” Do not fetch BRIA.

---

## Do I need a Hugging Face login on the 40GB box? On the 24GB box?

**Paint / 40GB: no.** `shaomq/MVPainter` is public. User already said the volume has ~40GB taken — that **is** the blobs. Sense-check `du` and proceed. Do not `hf auth login` there. Do not paste a token in chat.

**Mesh / 24GB: yes, on the pod, for gated Facebook DINOv3** (`facebook/dinov3-vitl16-pretrain-lvd1689m`). User accepts the license **in a PC browser**, then:

```bash
export HF_HOME=/workspace/.cache/huggingface
/workspace/vendor/trellis2-venv/bin/hf auth login --token  # paste ONLY in that SSH window
/workspace/vendor/trellis2-venv/bin/hf auth whoami         # must print a username
```

Old `huggingface-cli login` may 404; use `hf auth login`. “Add as git credential” / browser prompt on the pod is a dead end. **Agreeing is not enough** if the model page still says “awaiting review.” Then TRELLIS cannot start. Do not bill the A5000 waiting on Meta.

Copy token onto `HF_HOME` so the job sees it:

```bash
mkdir -p /workspace/.cache/huggingface /root/.cache/huggingface
# after login, both of these should exist:
test -s /workspace/.cache/huggingface/token && echo TOKEN_OK
test -s /root/.cache/huggingface/token && echo ROOT_TOKEN
```

Skip **BRIA `briaai/RMBG-2.0`** entirely. Concept stills already have alpha (PNG) or we force RGBA. `trellis2_patch.py` sets `pipeline.rembg_model = None` and guards `.to()`.

JPEG round2 stills have **no real alpha**. After `rembg_model=None`, preprocess still did `self.rembg_model.to(self.device)` → `None.to`. Guard:

```python
if self.rembg_model is None:
    output = input.convert('RGBA')
else:
    ...
```

and the preprocess `.to()`:

```python
if self.rembg_model is not None:
    self.rembg_model.to(self.device)
```

That is `_mesh_skip_rembg_restart.py` / `_mesh_fix_rembg_run.py` / `trellis2_patch.py`. Apply **both** i23d and texturing modules even if we `--skip-texture`.

---

## Why did DINOv3 / transformers crash after login worked?

Transformers 5 moved DINOv3 encoder layers under `.model`. Stock TRELLIS.2 does `for layer in self.model.layer` and dies. `trellis2_patch.py` uses `layer_root = self.model if hasattr(self.model, "layer") else self.model.model`.

Run the patch **after** install, **before** generate:

```bash
/workspace/vendor/trellis2-venv/bin/python /workspace/gpu_box/trellis2_patch.py
# expect: rembg_i23d / rembg_tex / dino / rembg_to_i23d  → patched or already patched
```

Do not invent a new DINO hack if that pattern is missing — the file changed upstream; stop and diff.

---

## Why not `pip install xformers`? Why a flash-attn **wheel**?

Unconstrained `pip install xformers` pulls a **second PyTorch** and fills a 30GB overlay. `trellis2_setup.sh` says this in the header. Skip it. If a TRELLIS venv xformers then breaks MV-Painter’s old `diffusers==0.20.2`, uninstall it; do not “align versions” by installing another torch.

flash-attn: **prebuilt wheel only**, `--no-deps`, matching torch / CUDA major / py / cxx11 ABI:

```text
flash_attn-2.8.3.post1+cu12torch2.8cxx11abiTRUE-cp312-cp312-linux_x86_64.whl
https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post1/<that>
pip install --no-deps /tmp/flash_attn-*.whl
python -c "import flash_attn, torch; print(flash_attn.__version__, torch.__version__)"
```

`ATTN_BACKEND=sdpa`, `SPARSE_ATTN_BACKEND=flash_attn`. Compiling flash-attn from source with `MAX_JOBS` high will melt the box. Setup uses `MAX_JOBS=2`, `TORCH_CUDA_ARCH_LIST=8.6` (A5000/A6000 Ampere).

CUDA compile needs `nvcc` **on PATH**:

```bash
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
command -v nvcc && nvcc --version
```

o-voxel needs Eigen:

```bash
test -f /usr/include/eigen3/Eigen/Dense || {
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libeigen3-dev
}
export CPATH=/usr/include/eigen3
export CPLUS_INCLUDE_PATH=/usr/include/eigen3
```

Missing Eigen = `o_voxel` wheel fail after a long compile. `_mesh_fix_eigen.py` / `_mesh_resume_ovoxel.py`. Rasterizer CUDA version mismatch (12.8 vs “PyTorch 13” check): `torch.utils.cpp_extension._check_cuda_version = lambda *a, **k: None` then `setup.py install`. Missing `pybind11` also died the renderer compile — install it.

Venv: `python3 -m venv ... --system-site-packages` so we reuse image torch instead of downloading another.

Clone TRELLIS.2: `git clone --depth 1` at 12–40 KB/s is a night. Prefer GitHub **codeload tarball**, then `git init` if the setup script wants `.git`:

```bash
curl -L --retry 5 -o /tmp/trellis2.tgz https://codeload.github.com/microsoft/TRELLIS.2/tar.gz/refs/heads/main
tar -xzf /tmp/trellis2.tgz -C /tmp
mv /tmp/TRELLIS.2-main /workspace/vendor/TRELLIS.2
```

`HF_HUB_ENABLE_HF_TRANSFER=0` — hf_transfer OOMs/fills disk. `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. `OPENCV_IO_ENABLE_OPENEXR=1`.

Setup does **not** download `microsoft/TRELLIS.2-4B`. Token must exist before `trellis2_run.py`. Confirm:

```bash
/workspace/vendor/trellis2-venv/bin/python -c \
  "import nvdiffrast, o_voxel, torch; print('INSTALL_OK', torch.__version__, torch.cuda.get_device_name(0))"
df -h / | tail -1
```

---

## What is “isolated remesh” and why not `to_glb(remesh=True)`?

Official `to_glb(..., remesh=True)` runs CuMesh **and then UV unwrap / texture bake** in the same call. That is the path that hung, baked brown PBR we do not ship, or died after generate already succeeded.

`trellis2_run.py` default:

1. `Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")` → `run(..., pipeline_type="1024_cascade")` (OOM → `512`).
2. `save_extract` → `/workspace/out/<name>_raw_extract.pt`.
3. `del pipeline; empty_cache`.
4. Isolated CuMesh: `fill_holes(max_hole_perimeter=3e-2)` → `cuBVH` → `remesh_narrow_band_dc(band=1, project_back=0)` at grid resolution from voxel_size / aabb `[[-0.5,-0.5,-0.5],[0.5,0.5,0.5]]` → `simplify(1_000_000)`.
5. `o_voxel.postprocess.to_glb(..., remesh=False, decimation_target=1_000_000, texture_size=2048, verbose=True)`.
6. `glb.export(..., extension_webp=False)` — WebP inside GLB breaks Windows 3D Viewer.

`--skip-texture` so `Trellis2TexturingPipeline` never loads.

Manual debug (no generate, no UV): `trellis2_manual_remesh.py --resolution 256` was a **probe**, not the ship remesh. Ship is 1024-class isolated remesh as in `export_isolated_remesh`.

Queue remaining names without repeating finished GLBs:

```bash
for name in gpt2_front_ink gpt2_front_sculpt nano2_concept_art nano2_2d_illustration nano2_3d_render; do
  out=/workspace/out/${name}_from_front.glb
  if [ -f "$out" ]; then echo SKIP_EXISTS $name; continue; fi
  $PY -u /workspace/gpu_box/trellis2_run.py --image /workspace/in/${name}.jpg \
    --out-dir /workspace/out --name "$name" --skip-texture
done
```

Pull with `_mesh_pull_glb.py` (gzip+hex). Local dest: `generated/bosses/demon/variants/<name>/mesh.glb`.

`faulthandler.enable(all_threads=True)` is on in the runners. Keep it.

---

## Can I paint with a prompt? Should I regenerate the mesh to get red eyes?

MV-Painter has **no text prompt**. Image + mesh only. A prompt-only model is a different pipeline (and MVPaint-the-CVPR-text-tool is not this job).

To change look: punchier **reference PNG** (eyes, teeth, light). **Keep the remesh.** New TRELLIS mesh only if the **shape** is wrong.

`--no_rembg` on paint. TRELLIS rembg patched off.

---

## Why did `container create: exit status 1` happen? Which RunPod template?

Community hosts often refuse the container. The image tag can be valid and still fail.

Do **not** paste a custom image string after it already failed. Official **RunPod PyTorch** template, CUDA 12.4 if listed, **different GPU/region**, 60GB+ container disk for mesh, public IP, TCP 22, SSH key = `ppp.pub`. No custom start command. Attach the paint volume **only** on the paint deploy, same datacenter.

Secure Cloud if Community fails twice. Do not stack failed pods.

---

## Can this agent stop the pod when done?

No. `runpodctl` without a RunPod API key cannot stop or terminate. User stops it in the dashboard. User **already stopped the 40GB**. Do not tell them to keep it overnight. Do not start another 40GB until they send a new SSH line **and** the Blender/glTF/OpenCV/HF-pointer gate above is green **before** UNet load.

---

## What is the full gate before TRELLIS generate on 24GB?

Meshes for the six round2 names are local. Skip this section unless the user wants a new image meshed.

```bash
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
# expect ~24GB class, not 16GB Ada, not 4GB
df -h / | tail -1
# expect tens of GB free; 30GB overlay + xformers already died
test -x /workspace/vendor/trellis2-venv/bin/python
test -f /usr/include/eigen3/Eigen/Dense
command -v nvcc
/workspace/vendor/trellis2-venv/bin/python -c \
  "import nvdiffrast,o_voxel,flash_attn,torch; print(torch.__version__, torch.cuda.get_device_name(0))"
/workspace/vendor/trellis2-venv/bin/hf auth whoami
test -s /workspace/.cache/huggingface/token
test -f /workspace/in/<stem>.jpg
grep -n 'rembg_model = None' /workspace/vendor/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py
grep -n 'layer_root' /workspace/vendor/TRELLIS.2/trellis2/modules/image_feature_extractor.py
# scripts LF not CRLF:
python3 -c "from pathlib import Path; b=Path('/workspace/gpu_box/trellis2_setup.sh').read_bytes(); assert b'\r' not in b"
```

Then the `trellis2_run.py` command with `--skip-texture`. Log: `/workspace/i23d.log`. Monitor: `_pod_mem_monitor.sh`. Out: `/workspace/out/<name>_from_front.glb` plus `_raw_extract.pt`.

---

## What is the full gate before MV-Painter infer on 40GB?

User stopped the last 40GB. When they bring a new one:

1. Confirm GPU ≥40GB VRAM (`nvidia-smi`). Reject MIG 24GB.
2. `du -sh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs` already tens of GB. If not, stop and ask; do not start a 36GB download onto a 30GB overlay.
3. Real `/workspace/MV-Painter/MVPainter/infer_multiview.py` (not a symlink to dead `/opt`).
4. Overlay `/opt/blender/blender` + OpenCV-in-Blender + `debug_value=0` + `set_debug_log` fallback + **GLTF_OK on a real remesh**.
5. `/opt/hf` snapshot pointers non-empty JSON; blobs symlinked; `model_index.json` parses.
6. `/opt/mvpaint-venv` on overlay with `diffusers cv2 OpenEXR pytorch_lightning`.
7. Inputs: GLB + **PNG same stem**. No leftover empty `*_6view.png`.
8. `cd /workspace/MV-Painter/MVPainter`. `--geo_rotation -90 --no_rembg`. `HF_HOME=/opt/hf`. EXRs on `/opt/render_temp`.
9. Infer checks Blender `returncode`. Watcher does not treat tqdm `\r` or a file-count as success.
10. Stop the pod after `*_6view.png` exists (real pixels). Unwrap/bake **local**.

Upload from PC:

```powershell
python C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\_paint_upload_ready.py
```

names: `gpt2_front_paint`, `gpt2_front_ink`, `gpt2_front_sculpt`, `nano2_concept_art`, `nano2_2d_illustration`, `nano2_3d_render`.

---

## What does this log line mean? (every named failure)

If the log line matches the left column, do the right column. Do not invent a fourth backend.

| What you see | What it is | Exact move |
|---|---|---|
| Plan mentions Hunyuan / Hunyuan-Paint / `hy3dgen` | License banned in EU/UK/SK | Delete. Mesh TRELLIS.2, paint MV-Painter. |
| “Let’s CPU-offload MV-Painter on 24GB” | UNet ~25GB must sit in VRAM | 40GB+. Stop the 24GB paint attempt. |
| PRO 6000 MIG 24GB | Still 24GB VRAM | Reject. A6000 48GB or other 40GB+. |
| `pip install xformers` (unpinned) | Second torch, 30GB full | Never. Prebuilt flash-attn wheel `--no-deps` only. |
| `o_voxel` / Eigen compile error | Missing `libeigen3-dev` / `CPATH` | `apt-get install libeigen3-dev`; export `CPATH=/usr/include/eigen3`. |
| `nvcc: not found` | CUDA not on PATH | `export CUDA_HOME=/usr/local/cuda; export PATH=$CUDA_HOME/bin:$PATH`. |
| `$'\r': command not found` / `set: pipefail` | CRLF | Rewrite script bytes to LF; `sed -i 's/\r$//'`. |
| Git clone 12 KB/s for hours | GitHub crawl | `codeload.github.com/.../tar.gz` tarball. |
| `facebook/dinov3` 401/403 / gated | User must accept + `hf auth login` **on 24GB** | Browser agree; token only in pod SSH; `whoami`. Not in chat. Not on 40GB. |
| DINOv3 “awaiting review” | Agree ≠ approved | Stop the pod or wait; do not loop generate. |
| `self.model.layer` AttributeError | transformers 5 DINOv3 layout | `trellis2_patch.py` `layer_root`. |
| `None.to` / `rembg_model` | Skip BRIA but `.to()` still called; or JPEG has no alpha | `rembg_model is None` → `convert('RGBA')`; guard `.to()`. |
| `OOM 1024_cascade` | VRAM on generate | Printed retry `512`. Stay 24GB-class, not 40GB. |
| Process `Killed` in remesh, GPU not full | CuMesh abort / host — **check dmesg** | Isolated remesh after freeing pipeline. Not “buy 40GB.” |
| Brown / TRELLIS PBR | `--skip-texture` omitted | Always `--skip-texture`. Paint is MV-Painter. |
| Windows 3D Viewer fails GLB | WebP in GLB | `extension_webp=False`. |
| `scp` hang / empty | Proxy has no real scp | gzip+hex over `ssh -tt`. |
| SSH hangs, no prompt | Missing `-tt` or 6s banner wait | `ssh -tt -i ppp user@ssh.runpod.io`. |
| `container create: exit status 1` | Host/template | Official PyTorch template, other region, no custom start, 60GB disk. |
| `expected 25327.64 MB, free 14480` | 30GB container vs 25.3GB ckpt | Volume for blobs; do not squeeze. |
| 50GB volume + TRELLIS download | 36G blobs + ~20G mesh cache | One volume, one job. Paint volume ≠ mesh cache. |
| `df` shows 1P / nonsense | geesefs lie | `du -sh` the blob dir. |
| `chmod +x` blender on `/workspace` | geesefs no exec | Extract Blender to `/opt`. |
| 0-byte `libsycl.so.7` | geesefs smashed symlinks | Overlay Blender; `file` the `.so`. |
| MV-Painter path is symlink to `/opt` | Died with old pod | Tarball clone on volume. |
| `JSONDecodeError` / empty `model_index.json` | 0-byte snapshot pointers | Rebuild `/opt/hf` links to volume blobs. Tiny JSON fetch only. |
| Infer 0 s, no GPU | leftover `*_6view.png` or `.jpg` vs `.png` | Delete empty 6-views; PNG same stem as GLB. |
| `SIXVIEW_COUNT 1` but junk | Watcher file-count / `camera/` | Inspect the PNG pixels. |
| tqdm `1/7` forever in `tail` | `\r` not newline | `tr '\r' '\n' < log \| tail`. Pipeline 7/7 ~5 min is normal. |
| GPU 0% for 20 min after 7/7 | `torch.load` 25GB off geesefs | Wait. VRAM should climb. Do not restart. |
| `FileNotFoundError: depth/000.exr` | Blender wrote nothing, exit 0 | OpenCV + `debug_value=0` + `set_debug_log` + `/opt/blender` + `/opt/render_temp` + check rc. |
| `loglevel expected an int, not None` | `debug_value=256` / `set_debug_log` | Patch addon fallback; smoke GLTF **before** UNet. |
| `blender --version` OK, infer dies | Version ≠ import | GLTF smoke on **this** remesh. |
| `scripts/blender_render_ortho.py` not found | Wrong cwd | `cd /workspace/MV-Painter/MVPainter`. |
| `normal is None` / EXR | OpenCV EXR disabled | `OPENCV_IO_ENABLE_OPENEXR=1` in Blender Python. Channel **V**. |
| CUDA OOM on MV-Painter 24GB | Official ckpt ~25GB | 40GB+. Not offload. |
| xatlas 47–70+ min, GPU idle | Official bake re-unwraps 930k faces | Kill that bake on 40GB. Local UV. Skip xatlas if UVs exist. |
| `blender_low` / 30k decimate | Crushed paint | Full remesh. `demon_painted.glb` is the bad one. |
| “Paint with a prompt” | No such flag | Punchier PNG. Keep remesh. |
| `runpodctl` stop | No API key | User dashboard. 40GB **already stopped**. |
| Attach volume to running pod | Not supported | Deploy new pod with volume. Same DC. |
| Two pods, one volume | geesefs lock | One at a time. |
| GTX 1050 / Linode for generate | No VRAM / no CUDA | Mesh 24GB, paint 40GB, Linode unwrap only. |
| `hf_transfer` / disk 99% | Transfer + 15GB file together | `HF_HUB_ENABLE_HF_TRANSFER=0`; don’t dual-download. |
| Extra 15GB `.safetensors` plus 25GB `.ckpt` | Two copies of ControlNet | Keep ckpt; skip that safetensors in snapshot rebuild. |
| Compile `custom_rasterizer` CUDA version assert | Image CUDA vs torch | Monkeypatch `_check_cuda_version`; install `pybind11`. |
| `diffusers` vs venv xformers | TRELLIS extra | Uninstall xformers; pin `diffusers==0.20.2`. |
| Overlay pip `cwd` bug | `os.chdir` leftover | `cd /tmp` before pip; venv on `/opt`. |
| False “have 6-view” then Blender still running | Monitor exited early | Require `INFER_MULTIVIEW_DONE` or a non-empty PNG, not a glob hit. |
| “Remesh on 40GB to go faster” | Wrong split | Remesh already local. 40GB is UNet VRAM. |
| SF3D `raw.glb` as ship mesh | Pancake + $1M cap | Historical. Record in `LEGAL_LIABILITY.md` if any remain in a build. |

---

## What is the ship split, in one block?

```text
Concept stills     already local (round2 jpg + round2_png)
TRELLIS.2 mesh     already local (six variants/*/mesh.glb) — 24GB A5000 did this
MV-Painter 6-view  NOT done — 40GB died in Blender; user stopped the pod
UV / xatlas / bake local CPU / local NVIDIA after a real *_6view.png exists
Game               still 8-dir PNGs; GLB is a factory, not a pygame character
```

Do not clone TRELLIS. Do not remesh these six. Do not start 40GB until the user sends SSH **and** the Blender/glTF/HF-pointer gate is green **before** the UNet moves. Do not use Hunyuan3D. Do not use Hunyuan-Paint. SSH is `ppp` with `-tt`.
