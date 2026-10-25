# CHECK 3 of 10 — TRELLIS.2 mesh + MV-Painter 6-view (fail-closed runbook)

This file is a **standalone replacement runbook**. Point an agent at **this file**. If a log line already has a row in §2, apply that row. Do not re-apt Eigen, do not re-clone TRELLIS.2, do not re-download the 36 GB MV-Painter blobs, do not re-rent a 40 GB box to “debug Blender,” and do not invent a new backend.

**This CHECK task is DOCUMENT ONLY. Do not start pods. Do not SSH to start infer. Do not generate.**

Checkpoint at time of writing (2026-09-19):

- Six remesh GLBs already sit on this PC under `generated/bosses/demon/variants/<stem>/mesh.glb` (tens of MB each, not 0-byte).
- The 40 GB paint pod was **already stopped by the user**. Do not tell them to kill it again. Confirm dashboard state first.
- Local bake / UV / xatlas has **not** been the 40 GB job. That work is this PC (CPU) plus local NVIDIA or a small CUDA box, **after** a real `*_6view.png` exists.

---

## Point-at-this-file laws (read before any command)

**Europe / UK / South Korea — hard legal split**

| Role | Allowed | Forbidden |
|---|---|---|
| Mesh | **TRELLIS.2** (`microsoft/TRELLIS.2-4B`) + **isolated CuMesh** remesh (`--skip-texture`) | **Hunyuan3D** mesh of any version (2, 2.1, 2mini, 2mv). Community licence excludes EU, UK, South Korea for weights **and Output**. Do not download it “just to look.” Do not hide origin. |
| Paint | **MV-Painter** (`shaomq/MVPainter`, **Apache-2.0**). Image + mesh only. No text prompt. | **Hunyuan-Paint** / Hunyuan 2.1 texgen. Same Tencent Hunyuan 3D 2.1 Community License. |
| Historical note | `LEGAL_LIABILITY.md` records Stable Fast 3D (Stability Community License, free commercial under USD 1M revenue; outputs not assumed grandfathered) and **rejects TRELLIS v1** because the official textured-GLB path pulled NVIDIA `nvdiffrast` / `nvdiffrec` (non-commercial flags). This round still **uses TRELLIS.2 as the mesh factory** and skips TRELLIS retexture. Official TRELLIS.2 still compiles those NVIDIA extras. Do not “fix” the legal file by switching to Hunyuan. |

`gpu_box/hunyuan3d_cli.py` and `gpu_box/setup.sh` Hunyuan paths are **historical**. Running them is a licence violation in Europe.

**Machines (do not collapse into one sentence)**

| Work | Box | Never |
|---|---|---|
| TRELLIS.2 `1024_cascade` + isolated CuMesh remesh | **24 GB** class (A5000 / 3090). Official README: ≥24 GB. | 16 GB Ada. This PC’s GTX 1050 (4096 MiB). 40 GB “because remesh died.” |
| MV-Painter `infer_multiview` (UNet in VRAM) | **40 GB+** (A6000 48 GB is fine). Official infer loads `v29_25000.ckpt` (~25.3 GB). | 24 GB card. CPU-offload as the plan. Overlay-only 30 GB disk. |
| UV / Blender unwrap / bake | **This PC (CPU)** for Blender + UV. **Local NVIDIA** for bake, or a **small** CUDA box. | The 40 GB box. xatlas / `infer_paint` / `bake_pipeline` / `blender_low` / 30k decimate on the A6000. |
| Linode | Blender/unwrap only | TRELLIS, MV-Painter generate, CUDA bake |

Never unwrap, never xatlas, never bake on 40 GB. Never decimate to 30k. `to_glb` already writes UVs on the remesh we keep. `blender_low.obj` is the crushed mesh (~85k verts vs ~754k original on the first remesh). Forbidden.

**SSH / git**

- Key: `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp` (there is no `~/.ssh/id_ed25519` on this Windows box).
- Always `ssh -tt`. RunPod’s proxy hangs without a TTY. Helpers sleep ~6 s for the banner.
- **Do not commit `ppp`.**
- Pipeline edits live in `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss`. The Private repo is dirty `dev_tmxlevels`. **Do not `git switch` that worktree.**

**Same-session waste this file exists to stop**

geesefs Blender, Eigen, OpenCV-inside-Blender, and `debug_value=256` were each rediscovered after they were already fixed. Two 40 GB UNet loads (20–30 min each) were spent re-learning Blender bugs. Search §2 first.

On any `Killed` / silent death: `free -h`, `dmesg`, full log, `nvidia-smi`. Do **not** guess OOM. One remesh death had ~24 GB RSS of 256 GB and an empty dmesg; CuMesh aborted in-process, it was not the OOM killer.

---

# 1. Fail-closed GATES

Print the `GATE_*` token. **No** `trellis2_run.py`, **no** `infer_multiview.py`, **no** Hugging Face download, **no** `pip install` of weights until the matching token exists.

Hosts change every rental. `_mesh_pod.py` and `_paint_pod.py` hard-code **dead** SSH hosts. Paste a fresh Connect line, keep `-tt` and `-i …\ppp`.

Windows local gates are PowerShell. Pod gates are bash on the box (via `ssh -tt -i ppp`).

---

### GATE_WORKTREE (this PC — before any git)

```powershell
Set-Location C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
$b = (git branch --show-current)
$priv = git -C C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private branch --show-current
if ($b -match 'dev_3d_boss' -and $priv -eq 'dev_tmxlevels') { Write-Host 'GATE_WORKTREE_OK' } else { Write-Host "GATE_WORKTREE_FAIL boss=$b private=$priv" }
```

Must print `GATE_WORKTREE_OK`. If Private is not `dev_tmxlevels` you already switched the dirty tree. Stop.

---

### GATE_KEY (this PC)

```powershell
$k = 'C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp'
if ((Test-Path $k) -and (Get-Item $k).Length -gt 200) { Write-Host 'GATE_KEY_OK' } else { Write-Host 'GATE_KEY_FAIL' }
```

Must print `GATE_KEY_OK`. Never `git add ppp`.

---

### GATE_LOCAL_MESH (this PC — current checkpoint)

Meshes already local. If this token prints, **do not generate TRELLIS again**.

```powershell
$stems = @(
  'gpt2_front_paint','gpt2_front_ink','gpt2_front_sculpt',
  'nano2_concept_art','nano2_2d_illustration','nano2_3d_render'
)
$root = 'C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants'
$ok = $true
foreach ($s in $stems) {
  $p = Join-Path $root "$s\mesh.glb"
  if (-not (Test-Path $p) -or (Get-Item $p).Length -lt 10MB) {
    $ok = $false
    Write-Host "MISSING_OR_TINY $p"
  } else {
    Write-Host "HAVE $s $((Get-Item $p).Length)"
  }
}
if ($ok) { Write-Host 'GATE_LOCAL_MESH_OK' } else { Write-Host 'GATE_LOCAL_MESH_FAIL' }
```

Must print `GATE_LOCAL_MESH_OK` and six `HAVE` lines with ~45–48 million bytes. A 0-byte or kilobyte file is a geesefs / failed hex download, not a mesh.

---

### GATE_PAINT_STOPPED (this PC — current checkpoint)

The 40 GB pod is already stopped. Do not start it from this CHECK.

```powershell
Write-Host 'GATE_PAINT_STOPPED_OK  (user stopped 40GB; do not start a pod in this task)'
```

---

### GATE_MESH_GPU (24 GB box only — future generate)

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
python3 - <<'PY'
import torch
name = torch.cuda.get_device_name(0)
mb = torch.cuda.get_device_properties(0).total_memory / 1024**2
print("TORCH", torch.__version__, name, int(mb))
raise SystemExit(0 if mb >= 22000 else 1)
PY
echo GATE_MESH_GPU_OK
```

Must print `GATE_MESH_GPU_OK` and a 24 GB-class name (A5000 / 3090 / A100). **Fail** on 16 GB Ada, 12 GB, or GTX 1050. Do not “try 512 on 16 GB” as the plan; `trellis2_run.py` may retry 512 after a 1024 OOM, that is a last resort, not a SKU.

Also require a **devel** image so `nvcc` exists:

```bash
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH
command -v nvcc && nvcc --version | tail -1
command -v g++ && g++ --version | head -1
echo GATE_MESH_NVCC_OK
```

---

### GATE_MESH_DISK (24 GB box)

Overlay for TRELLIS install + DINOv3 + TRELLIS.2-4B is **not** the 50 GB MV-Painter volume.

```bash
df -h / /workspace
du -sh /workspace/vendor /workspace/.cache/huggingface 2>/dev/null
echo GATE_MESH_DISK_OK
```

Need ~60 GB **container** disk on a fresh mesh pod. A 30 GB overlay plus unconstrained `xformers` fills the box. **Do not attach the 50 GB paint volume** (already ~36–38 GB of MV-Painter blobs). One volume, one pod. geesefs locks if two pods share it.

If `df -h /workspace` prints `1.0P`, that is **geesefs lying**. Ignore capacity. Use the bought size + `du -sh` of known trees.

---

### GATE_MESH_INSTALL (24 GB box)

```bash
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3
test -f /usr/include/eigen3/Eigen/Dense && echo EIGEN_HEADER_OK
/workspace/vendor/trellis2-venv/bin/python - <<'PY'
import nvdiffrast, o_voxel, torch, flash_attn, cumesh
print("INSTALL_OK", torch.__version__, torch.cuda.get_device_name(0))
print("flash_attn", flash_attn.__version__)
print("CUMESH", getattr(cumesh, "__file__", None))
PY
echo GATE_MESH_INSTALL_OK
```

Must print `INSTALL_OK`, `EIGEN_HEADER_OK`, `GATE_MESH_INSTALL_OK`. If that already prints, **do not** re-run `trellis2_setup.sh`, do not re-apt Eigen, do not recompile CuMesh.

`trellis2_setup.sh` is the only installer: `ATTN_BACKEND=sdpa`, `SPARSE_ATTN_BACKEND=flash_attn`, **no unconstrained xformers**, flash-attn **prebuilt wheel** (`pip install --no-deps /tmp/flash_attn-*.whl`), `MAX_JOBS=2`, nvdiffrast **v0.4.0**, nvdiffrec branch **renderutils**, CuMesh, FlexGEMM, `cp -a $ROOT/o-voxel` (not PyPI o-voxel), `python trellis2_patch.py`.

---

### GATE_MESH_TOKEN (24 GB box — DINOv3 gated)

```bash
export HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0
test -s "$HF_HOME/token" && echo TOKEN_FILE_OK || echo TOKEN_MISSING
/workspace/vendor/trellis2-venv/bin/hf auth whoami
echo GATE_MESH_TOKEN_OK
```

Must print a Hugging Face username and `GATE_MESH_TOKEN_OK`. User accepts Facebook **DINOv3** in a **PC browser**, then `hf auth login --token` **on the 24 GB box**. Do not paste the token in chat. Skip BRIA/RMBG (patched off). `shaomq/MVPainter` is public — **no HF login on the 40 GB box**.

---

### GATE_MESH_PATCH (24 GB box)

```bash
python3 - <<'PY'
from pathlib import Path
root = Path("/workspace/vendor/TRELLIS.2")
i23d = (root / "trellis2/pipelines/trellis2_image_to_3d.py").read_text()
tex = (root / "trellis2/pipelines/trellis2_texturing.py").read_text()
dino = (root / "trellis2/modules/image_feature_extractor.py").read_text()
ok = True
for label, cond in [
    ("REMBG_NONE", "pipeline.rembg_model = None" in i23d and "pipeline.rembg_model = None" in tex),
    ("REMBG_GUARD", "if self.rembg_model is not None:" in i23d),
    ("DINO_LAYER", 'layer_root = self.model if hasattr(self.model, "layer")' in dino),
]:
    print(label, cond)
    ok = ok and cond
print("GATE_MESH_PATCH_OK" if ok else "GATE_MESH_PATCH_FAIL")
PY
```

Must print `GATE_MESH_PATCH_OK`. If generate dies on `rembg_model=None` then `.to()`, the guard is missing — apply `trellis2_patch.py` / `_mesh_fix_rembg_run.py`, do not download `briaai/RMBG-2.0`.

---

### GATE_PAINT_GPU (40 GB box only)

```bash
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
python3 - <<'PY'
import torch
mb = torch.cuda.get_device_properties(0).total_memory / 1024**2
print("VRAM_MB", int(mb))
raise SystemExit(0 if mb >= 40000 else 1)
PY
echo GATE_PAINT_GPU_OK
```

Must print `GATE_PAINT_GPU_OK`. A5000 24 GB **fails**. The 24 GB-safe custom infer was a dead end.

---

### GATE_PAINT_VOL (40 GB box — sense-check **before** any Hugging Face download)

`df` on geesefs is a lie (`1.0P`). Blobs live on the volume. Snapshots look empty (0-byte pointers).

```bash
echo '=== DF (often fake on geesefs) ==='
df -h / /workspace
echo '=== BLOBS ==='
du -sh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs
find /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs -type f -size +1M | wc -l
ls -lh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs | head
echo GATE_PAINT_VOL_OK
```

Must print tens of GB for blobs (measured **~36 GB**, including **~24–25.3 GB** `v29_25000.ckpt`) and `GATE_PAINT_VOL_OK`. If blobs are already tens of GB, **rebuild `/opt/hf` pointers only**. Do not `hf_hub_download` the repo again.

The file infer actually loads is `unet_w_controlnet/v29_25000.ckpt` (**25.3 GB**), not the extra ~15 GB `unet_w_controlnet/*.safetensors`. “Enough disk for ~15 GB” on a 30 GB overlay was the ENOSPC that killed the first paint (`expected 25327.64 MB`, free `14480.68 MB`, `os error 28`). **50 GB volume** for paint blobs. Not 40. Not 80 as a magic number. That 50 GB volume **cannot also hold TRELLIS (~20 GB)**.

---

### GATE_PAINT_HF (40 GB box — overlay pointers, not volume snapshots)

```bash
export HF_HOME=/opt/hf HF_HUB_ENABLE_HF_TRANSFER=0
SNAP=/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d
python3 - <<'PY'
import json
from pathlib import Path
p = Path("/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d/model_index.json")
raw = p.read_text()
assert len(raw) > 20 and raw.lstrip()[:1] == "{", "empty or junk JSON"
json.loads(raw)
print("INDEX_OK", p, len(raw))
PY
test -s "$SNAP/model_index.json"
echo GATE_PAINT_HF_OK
```

Must print `INDEX_OK` and `GATE_PAINT_HF_OK`. `JSONDecodeError` here means 0-byte geesefs snapshot files. Rebuild with `_paint_rebuild_cache.py` (skip linking extra 15 GB safetensors). `HF_HOME` **must** be `/opt/hf` on paint. Volume snapshot pointers are 0-byte.

---

### GATE_PAINT_VENV (40 GB box)

```bash
test -x /opt/mvpaint-venv/bin/python
/opt/mvpaint-venv/bin/python -c "import diffusers,cv2,OpenEXR,pytorch_lightning,numpy; print('PYDEPS_OK', diffusers.__version__, numpy.__version__)"
echo GATE_PAINT_VENV_OK
```

Must print `PYDEPS_OK` with **numpy 1.26.x** (not 2) and `GATE_PAINT_VENV_OK`. Venv is **`/opt/mvpaint-venv` on overlay**, `--system-site-packages` (reuse image CUDA torch — do not pip-install torch). Volume venv executables fail `chmod` / pip `OSError`. `cd /tmp` before pip (`FileNotFoundError` after `mv` if cwd was the moved dir). Pins: `diffusers==0.20.2`, `transformers==4.40.1`, `huggingface_hub==0.25.2`, `pytorch-lightning==2.2.4`, `OpenEXR==3.2.4`, `numpy==1.26.3`, `scipy==1.13.0`. Install `rembg` even with `--no_rembg` (module-level import still runs).

---

### GATE_PAINT_BLENDER (40 GB box — **before** any UNet load)

`blender --version` and `test -x blender` are **false success**. Official Blender **exits 0 after a Python traceback**. Success is files on overlay, not a version string.

Do **not** load `v29_25000.ckpt` until this token prints.

```bash
test -x /opt/blender/blender
BPY=/opt/blender/4.2/python/bin/python3.11
test -x "$BPY"
OPENCV_IO_ENABLE_OPENEXR=1 "$BPY" -c "import os; os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'; import cv2; print('CV2_OK', cv2.__version__)"
/opt/blender/blender --background --python-expr "import cv2; print('BLEND_CV2', cv2.__version__)"
# live infer must call overlay blender, not the volume 4.2.9 tree
python3 - <<'PY'
from pathlib import Path
t = Path("/workspace/MV-Painter/MVPainter/infer_multiview.py").read_text()
assert "/opt/blender/blender" in t, "blender_path still the 4.2.9 volume lie"
assert "/opt/render_temp" in t, "render_temp still on volume"
print("INFER_PATHS_OK")
PY
echo GATE_PAINT_BLENDER_OK
```

Must print `CV2_OK`, `BLEND_CV2`, `INFER_PATHS_OK`, `GATE_PAINT_BLENDER_OK`.

Volume Blender cannot `chmod +x` on geesefs. Symlinks become **0-byte**. Copying only the `blender` binary (139 MB) looks installed and cannot load `4.2/` scripts. Extract the **full tree** to overlay `/opt/blender` (we used Blender **4.2.4 LTS**; the official path name `../blender-4.2.9-linux-x64/blender` is a lie). Persist a `.tar.xz` on the volume; extract to overlay every new pod (~5–10 min). Never `ln -s` Blender onto the volume.

HDRI must be real, not 0-byte:

```bash
ls -lh /workspace/MV-Painter/MVPainter/scripts/overcast_soil_puresky_4k.exr
# expect ~66 MB
```

---

### GATE_PAINT_GLTF (40 GB box — **before** UNet)

`bpy.app.debug_value=256` makes `io_scene_gltf2.set_debug_log()` return **None**. The importer then dies: `IMPORT_SCENE_OT_gltf.loglevel expected an int, not NoneType`. Passing `loglevel=0` on the **operator** is not enough — `execute()` overwrites it.

```bash
python3 - <<'PY'
from pathlib import Path
ortho = Path("/workspace/MV-Painter/MVPainter/scripts/blender_render_ortho.py").read_text()
addon = Path("/opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py").read_text()
assert "debug_value=256" not in ortho, "debug_value=256 still in ortho"
assert "debug_value=0" in ortho or "bpy.app.debug_value=0" in ortho
idx = addon.find("def set_debug_log")
chunk = addon[idx:idx+700]
assert "return logging.INFO" in chunk.split("return logging.DEBUG")[-1][:120], "no set_debug_log fallback"
print("SET_DEBUG_PATCH_OK")
print("ORTHO_DEBUG_OK")
PY
# smoke: replace the glb path with a real uploaded remesh
/opt/blender/blender --background -Y --python-expr "import bpy; bpy.app.debug_value=0; bpy.ops.import_scene.gltf(filepath='/workspace/mvpaint_in/glbs/gpt2_front_ink.glb', merge_vertices=True, loglevel=0); print('GLTF_OK', len(bpy.data.objects))"
echo GATE_PAINT_GLTF_OK
```

Must print `SET_DEBUG_PATCH_OK`, `GLTF_OK`, `GATE_PAINT_GLTF_OK`. Grep **live files** after every patch. `_paint_dump_cmds.py` exists because a whitespace `replace` printed success and left `CMDS_BLOCK` unpatched (`CMDS_BLOCK_NOT_FOUND`).

Full ortho smoke (the real gate, not `--version`):

```bash
mkdir -p /opt/render_temp
export OPENCV_IO_ENABLE_OPENEXR=1
/opt/blender/blender --background -Y --python /workspace/MV-Painter/MVPainter/scripts/blender_render_ortho.py -- \
  --object_path /workspace/mvpaint_in/glbs/gpt2_front_ink.glb \
  --geo_rotation -90 \
  --output_dir /opt/render_temp
ls -lh /opt/render_temp/*/depth/000.exr && echo GATE_PAINT_EXR_OK
```

Must print `GATE_PAINT_EXR_OK` and a non-empty `depth/000.exr`. Empty `camera/` or `depth_png/` is **not** success: `save_images` creates `camera/` **before** glTF import; infer creates `depth_png/` **after** Blender returns 0. Compositor may write `0000001.exr` — rename to `000.exr`…`005.exr`. Infer wants `000.exr`–`005.exr`.

Never `rm -rf /opt/blender` or `pkill blender` while infer is why you rented the box.

---

### GATE_PAINT_PAIR (40 GB box — six stems, same names)

MV-Painter matches with **string** `base_name.replace("glb", "png")`, not a suffix replace. JPG on disk and PNG missing = **silent skip**. Leftover empty `*_6view.png` makes infer return in 0 s (`if os.path.exists(...6view.png): return`).

```bash
python3 - <<'PY'
from pathlib import Path
stems = [
  "gpt2_front_paint","gpt2_front_ink","gpt2_front_sculpt",
  "nano2_concept_art","nano2_2d_illustration","nano2_3d_render",
]
ok = True
for s in stems:
    g = Path(f"/workspace/mvpaint_in/glbs/{s}.glb")
    p = Path(f"/workspace/mvpaint_in/imgs/{s}.png")
    gs = g.stat().st_size if g.is_file() else 0
    ps = p.stat().st_size if p.is_file() else 0
    print(s, "glb", gs, "png", ps)
    if gs < 10_000_000 or ps < 1000:
        ok = False
print("GATE_PAINT_PAIR_OK" if ok else "GATE_PAINT_PAIR_FAIL")
PY
rm -f /workspace/mvpaint_out/*_6view.png
```

Must print `GATE_PAINT_PAIR_OK`. `test -s` every GLB and PNG. Old demo GLBs go in `_old/`. 0-byte uploads happened on geesefs.

---

### GATE_PAINT_CMDS (40 GB box — live infer, not a helper’s memory)

```bash
python3 - <<'PY'
from pathlib import Path
t = Path("/workspace/MV-Painter/MVPainter/infer_multiview.py").read_text()
need = ["/opt/blender/blender", "/opt/render_temp", "geo_rotation", "BLENDER_RC"]
for n in need:
    print(n, n in t)
ok = all(n in t for n in need) and "../blender-4.2.9-linux-x64/blender" not in t.replace(" ","")
print("GATE_PAINT_CMDS_OK" if ok else "GATE_PAINT_CMDS_FAIL")
PY
```

Must print `GATE_PAINT_CMDS_OK`. If `CMDS_BLOCK_NOT_FOUND`, dump the live file (`_paint_dump_cmds.py`) and patch what is actually there.

---

### GATE_6VIEW (success token after infer — count **files**, not script text)

```bash
python3 -c "import pathlib; n=len(list(pathlib.Path('/workspace/mvpaint_out').rglob('*6view.png'))); print('SIXVIEW_COUNT', n)"
# watcher must print HAVE_6VIEW only from that count
```

A watcher that greps the **shell script** for the string `6view` prints `HAVE_6VIEW` immediately. That is a lie. `_paint_watch.py` counts `Path.rglob('*6view.png')`.

After the first real 6-view: **shut the 40 GB box**. Bake is not that machine.

---

# 2. If you see this log line → exact fix

This is the body of the runbook. Match the **log / symptom**, apply the **exact fix**. Do not improvise a second cause.

| If you see this | It means | Exact fix |
|---|---|---|
| `GATE_*_FAIL` or missing token | A gate did not pass | Stop. Do not infer/generate. Fix that gate only. |
| Hunyuan / `Hunyuan3D` / `hy3dgen` / Hunyuan-Paint in a plan or clone URL | Licence-banned in EU/UK/SK | Delete the idea. Mesh = TRELLIS.2 + isolated CuMesh. Paint = MV-Painter Apache-2.0. |
| `git switch` / `git checkout` on Private `dev_tmxlevels` | Dirty game tree | Stay in `Pixel-Realm-Combat-Heroes-Boss`. Do not switch. |
| `ppp` staged or committed | Private key in git | Unstage. Never commit. Key path is `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp`. |
| SSH hangs with no TTY / `subsystem request failed` on `scp` | RunPod proxy has no SCP; needs TTY | `ssh -tt`. Upload/download = gzip+hex (`_paint_put.py`, `_mesh_pull_glb.py`). `scp -O` does not save you on the proxy host (`user@ssh.runpod.io`). Direct `root@IP -p PORT` scp sometimes worked; do not rely on it. |
| `id_ed25519: No such file` | Key is `ppp`, not default | `-i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp` |
| `NVIDIA GeForce GTX 1050, 4096 MiB` | This PC is not Phase 1 | 24 GB cloud for mesh, 40 GB+ for paint UNet, this PC for Blender/Fox/bake. `nvidia-smi` lives at `C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe` (not on PATH). |
| `container create: exit status 1` | Community host refused the container | Stop+Terminate. Official **RunPod PyTorch** template (CUDA **devel**), no custom image string, no Start command, no volume on first tries, different GPU/region. Secure Cloud if the third try fails (~$0.25–$0.50/hr). Failed creates billed **$0.00**. |
| RTX 2000 Ada **16 GB** as the mesh box | Wrong SKU for official TRELLIS.2 | Rent A5000/3090 **24 GB**. 16 GB can OOM on 1024³ export. A4000 16 GB is a bad bet. Community A5000 ~$0.16/hr, 3090 ~$0.22/hr. Do not pay ~$0.50 for a 12 GB 4070 Ti. |
| `nvcc missing` / `nvcc` installed but not found | Non-devel image, or PATH | Devel image. `export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH` |
| `pip install xformers` / disk filling toward 30 GB during install | Unconstrained xformers pulls a **second torch** | Kill pip. Never install xformers this way. `ATTN_BACKEND=sdpa`, `SPARSE_ATTN_BACKEND=flash_attn`. `trellis2_setup.sh` header exists because this almost filled 30 GB. |
| `flash-attn==2.7.3 \|\| pip install xformers` | Old installer fallback is the disk-killer | Delete that fallback. Prebuilt wheel only: `flash_attn-2.8.3.post1+cu{cuda}torch{mm}cxx11abi{abi}-cpXX-cpXX-linux_x86_64.whl` from Dao-AILab, `pip install --no-deps`. |
| `o_voxel` / `fatal error: Eigen/Dense: No such file` | Missing Eigen headers | `apt-get install -y libeigen3-dev`; `export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3`. `trellis2_setup.sh` already does this **if the file is missing**. If `/usr/include/eigen3/Eigen/Dense` exists, **do not re-apt**. A dead NIC was blamed on Eigen once; check the pod first. |
| CuMesh / nvdiffrast compile RAM death | Too many parallel jobs | `MAX_JOBS=2` (1 only if compile RAM-dies). `TORCH_CUDA_ARCH_LIST=8.6` on Ampere. |
| `torch.utils.cpp_extension` CUDA version check fails (12.8 / torch 2.8) | Image CUDA vs torch tag | `ext._check_cuda_version = lambda *a, **k: None` when compiling extras. Need `ninja` + `pybind11`. Resume the failed extension, do not re-clone TRELLIS. |
| `FileNotFoundError` after pip `mv` | CWD was the directory that got moved | `cd /tmp` before pip/setup. |
| Random PyPI `o-voxel` | Wrong tree | `cp -a $ROOT/o-voxel $EXT/o-voxel` then `pip install --no-build-isolation`. |
| Unpinned nvdiffrast HEAD | Breaks | nvdiffrast **v0.4.0**; nvdiffrec **renderutils**; utils3d commit `9a4eb15e4021b67b12c460c7057d642626897ec8`. |
| `hf_transfer` / tiny file download errors / broken `.gitattributes` | `HF_HUB_ENABLE_HF_TRANSFER=1` (RunPod default) | `export HF_HUB_ENABLE_HF_TRANSFER=0` on **every** setup and run. Rebuild then only fetches tiny JSON, not 36 GB blobs. |
| DINOv3 gated / `Cannot access gated repo` on 24 GB | Facebook DINOv3; pod has no browser | Agree on PC. `hf auth login --token` on the 24 GB box. Copy token file to `$HF_HOME/token`. |
| `AttributeError: ... layer` on DINOv3 / Transformers 5 | Encoder layers moved under `.model` | `trellis2_patch.py` dino patch (`layer_root = self.model if hasattr(self.model, "layer") else getattr(self.model, "model", self.model)`). |
| `briaai/RMBG-2.0` gated / rembg download | Official TRELLIS rembg | Patch rembg **off**. Inputs already have alpha. Do not download RMBG. |
| `NoneType ... rembg_model.to` / `'NoneType' object has no attribute 'to'` | Patch set `rembg_model = None` but preprocess still `.to(device)` | Guard `if self.rembg_model is not None`. Also skip the rembg call: if None, `output = input.convert('RGBA')`. `trellis2_patch.py` + `_mesh_skip_rembg_restart.py`. |
| `OOM 1024_cascade, retry 512` | VRAM spike on 1024 | Script already retries `512` after `empty_cache`. Stay 24 GB-class. Do not jump to 40 GB for remesh. `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is already in `trellis2_run.py`. |
| Process dies at `Building BVH...` / `Finalizing mesh` with **no Python traceback** | CuMesh native abort on raw ~3.4M-face extract **in the same process as generate** | Do **not** guess OOM. Measure: `free -h`, `dmesg -T \| grep -iE 'killed process\|oom-kill\|segfault'`, `_pod_mem_monitor.sh`. Measured: RSS ~24 GB / 256 GB (~170 GB still free), GPU ~3 GB generate / ~200 MB remesh start, 300+ threads → 1, dmesg empty. Use **isolated** remesh: generate `--skip-texture`, `export_isolated_remesh` (`fill_holes(3e-2)`, `band=1`, `project_back=0`, `simplify(1_000_000)`, `to_glb(..., remesh=False)`). Hole-fill was 1,617,464 → 1,617,482 verts (+18) then death in BVH/finalize when remesh stayed in-process. Successful isolated remesh ~465k verts / 940k faces. |
| `remesh=False` GLB “just works” but snout/eyes are holes | Skipped repair; decimated 3.4M → `decimation_target` (~391k verts, 27 MB `demon_from_front_noremesh.glb`) | Isolated remesh of the **extract**, not “ship remesh=False forever.” |
| `trellis2_manual_remesh.py` wrote a GLB with no UVs | `trimesh.export` verts/faces only | **Not paint-ready.** Crash-test only. 256-res crash test: 235,695 verts, 26 open edges, seconds. Official paint-ready path is `export_isolated_remesh` / `to_glb remesh=False` after CuMesh. |
| Remesh 256 / “need 40 GB for remesh” | Coarse voxel / wrong machine myth | Official: **1024** remesh of the raw extract, `band=1` / `project=0`, on **24 GB**. 40 GB is paint UNet. |
| `--skip-texture` omitted / brown TRELLIS PBR | TRELLIS texturing is not the paint we ship | Always `--skip-texture`. Paint is MV-Painter. |
| Windows 3D Viewer rejects the GLB / `EXT_texture_webp` | WebP textures | `glb.export(..., extension_webp=False)` in `trellis2_run.py`. PNG copies: `*_png.glb`. |
| `to_glb remesh=False` sits ~2 min with xatlas spam | Remaining UV unwrap inside `to_glb` | Let it finish. This is **not** the bake hour. |
| `blender_low.obj` / `target_vertices=30000` / 30k decimate | Official reduce path; bake quality dies | **Forbidden.** Bake `blender.obj` / full remesh. First remesh ~754k verts vs crushed ~85k (later note ~930k vs ~53k ≈ 8.5× verts, 17× faces). |
| `TOKEN_MISSING` on a new 24 GB pod | Login does not persist | User logs in on the box. Agent does not paste the token. |
| bash `$'\r': command not found` | Windows CRLF | `sed -i 's/\r$//'` after upload. |
| Two `git clone` of TRELLIS.2 at once | Agent impatience | Wait, or zip/codeload (`_mesh_zip_clone.py`). |
| `No space left on device (os error 28)` / `ENOSPC` / `expected 25327.64 MB` free `14480.68 MB` | 25.3 GB ckpt onto **30 GB overlay** | Volume for blobs. Overlay for Blender/venv/`/opt/hf` pointers. Do not put the ckpt on overlay. Sense-check `du` **before** download. First overlay: 30G total, 17G used, 14G free, cache already 13G. |
| “Enough disk for ~15 GB” | Wrong file (extra safetensors, not the ckpt) | Infer loads `v29_25000.ckpt` (~24–25.3 GB). Skip linking `unet_w_controlnet/*.safetensors` (~15 GB extra) in `_paint_rebuild_cache.py`. Buy **50 GB** volume. |
| `df -h /workspace` shows **1.0P** | geesefs fake capacity | Ignore. Bought size + `du -sh`. Overlay is a **separate** 30G (was 3.7G used for code+Blender while volume had 38G). |
| Paint ENOSPC treated as a TRELLIS disk problem (or the reverse) | Two disks | Sense-check both. `_paint_what_on_vol.py` / `_paint_cache_sense.py`. |
| A5000 + 30 GB overlay + no volume (later mesh) | Wrong **disk**, not wrong GPU | 60 GB container disk for mesh. Do not attach the paint volume if it already holds 36 GB of paint. After TRELLIS+DINOv3 on 30G overlay: ~11 GB free — mesh-only can scrape **if no xformers**. |
| `chmod +x` on volume Blender does nothing | geesefs no exec bit | Full tree on **overlay** `/opt/blender`. |
| 0-byte `.so` / 0-byte snapshot JSON / `JSONDecodeError` on `model_index.json` | geesefs materialized a symlink as empty | Rebuild `/opt/hf` pointers to volume **blobs**. Snapshot rev `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`. Do not re-download 36 GB. `_paint_cache_sense.py` then `_paint_rebuild_cache.py`. |
| `ln -s` Blender / 139 MB `blender` binary that cannot run scripts | geesefs copies binary or empty symlink, not `4.2/` | Never symlink Blender onto the volume. Overlay full tree. `_paint_fix_blender.py` that copies only the binary **is a lie** — see §4. |
| pip `OSError: [Errno 1] Operation not permitted` on volume venv | venv on geesefs | `/opt/mvpaint-venv` on overlay. |
| Putting venv on volume “so next pod does not reinstall” | Executables still broken | Persist **blobs + repo + blender `.tar.xz`**. Rebuild overlay venv/Blender/`/opt/hf` every new pod (5–10 min). |
| MV-Painter was a symlink to `/opt` and vanished | Overlay died with the old pod | Real clone or **codeload tarball** on the volume: `/workspace/MV-Painter`. |
| `blender_path ='../blender-4.2.9-linux-x64/blender'` | Hard-coded volume name | `blender_path ='/opt/blender/blender'`. 4.2.9 name is a lie; 4.2.4 LTS on overlay works. |
| `blender --version` OK but zero EXRs / missing `000.exr` | Blender exited 0 after traceback | Success = `depth/000.exr`. GATE_PAINT_BLENDER + GATE_PAINT_EXR **before** UNet. |
| `ModuleNotFoundError: cv2` inside Blender | OpenCV not in Blender’s Python | pip into `$BPY=/opt/blender/4.2/python/bin/python3.11`, not only the venv. `OPENCV_IO_ENABLE_OPENEXR=1` **before** `import cv2`. |
| `EXR_READ_FAIL` / OpenCV `imread` returns `None` on `.exr` | OpenCV built without EXR | Env var + fallback `bpy.data.images`. None-guard must not still `cv2.imwrite(..., normal_unit16)` unset → `UnboundLocalError` after view 0 (`depth/001.exr` never exists). |
| `IMPORT_SCENE_OT_gltf.loglevel expected an int, not NoneType` | `debug_value=256` → `set_debug_log()` returns None | (1) `debug_value=0` in ortho (2) `return logging.INFO` fallback in addon `set_debug_log` (3) still pass `loglevel=0`. Operator arg **alone failed**. `_paint_gltf_fix.py` + `_patch_debug.py`. |
| Infer used `/opt/blender` but still missing `000.exr` after a **second** UNet load | `debug_value=256` left in place; patch script missed `CMDS_BLOCK` | Grep live files. `GATE_PAINT_CMDS`. Full gate every restart, not a subset. Two UNet loads + zero 6-views was this. |
| `CMDS_BLOCK_NOT_FOUND` | Fragile whitespace replace | Dump live `infer_multiview.py`. Patch what is there. |
| Empty `camera/` or `depth_png/` treated as progress | Created before/after import regardless | Failure unless `depth/000.exr` (and usually `normal/000.png`). |
| `0000001.exr` | Frame suffix | Rename to `000.exr`…`005.exr`. |
| HDRI 0 bytes | geesefs | Real `overcast_soil_puresky_4k.exr` (~66 MB). |
| `render_temp` empty on volume | Write/symlink failure | `--output_dir /opt/render_temp`; replace `"render_temp"` in infer. |
| `shutil.copy` fail on exported obj | geesefs | `shutil.copyfile`. |
| `BLENDER_RC 0` then missing EXR | infer ignores Blender failure | After subprocess, **require** `depth/000.exr`; raise if missing. RC is not enough. |
| `../blender_render_ortho.py` not found | Wrong cwd | `cd /workspace/MV-Painter/MVPainter`. |
| Stem silently skipped / infer “succeeds” in 0 s | PNG missing, 0-byte pair, or leftover `*_6view.png` | Same stem PNG as GLB (`round2_png/`). `rm` empty 6-views. `test -s` both. |
| `import rembg` fails with `--no_rembg` | Module-level import | Install rembg. Keep **numpy 1.26.3**. Do not upgrade numpy to 2. `--no_rembg` only skips calling it. Combined 6-view order: `000,005,001,004,002,003`; depth channel `V`; seed 12; 75 steps. `--geo_rotation -90` required (TRELLIS orientation; Hunyuan would have been 0 — we do not run Hunyuan). |
| `huggingface_hub` vs `diffusers 0.20.2` API errors | New hub | Pin `huggingface_hub==0.25.2`. |
| CUDA OOM on MV-Painter on a 24 GB card | Official path loads ~25 GB UNet | 40 GB+. Do not CPU-offload as the plan. |
| Log stuck on `Loading custom unet ...` / tqdm frozen at `1/7` | `torch.load` of 24 GB ckpt off geesefs; tqdm uses `\r` | Watch VRAM climb toward **~27 GB**. Pipeline 7/7 from warm `/opt/hf` ~5 min. **Do not restart.** Parse `\r` as newlines. RSS/VRAM climbing = still loading. Volume→VRAM **20–30 min** (local SSD: a couple of minutes). Mid-load snapshot: 6.5 GB RAM, 2 GB VRAM, no 6-view yet. GPU **75-step paint is ~38 seconds**, not 15 min. “~15 min if weights on volume” was told repeatedly and is **wrong** as a GPU-step ETA. On disk ≠ in VRAM. |
| Watcher prints `HAVE_6VIEW` immediately | Grepped script text | Count files only (`_paint_watch.py`). |
| GPU 0%, process alive, tqdm frozen | `\r` or geesefs read | Check VRAM/RSS. Do not kill. Killing infer to “fix Blender” costs another 20–30 min geesefs UNet read. Keep **one** live `infer_multiview`. Patch Blender **before** start. Once weights are in VRAM, loop all stems: 1× load + 6× (Blender + ~38 s). |
| Process dead, `tail -5` empty | Traceback earlier / Blender stderr | Read **full** log. `TSTAT` in `_paint_watch.py`. |
| `groups: cannot find name for group ID 109` | RunPod NSS noise | Ignore. |
| `nohup` then SSH `Terminated` | HUP on disconnect | Confirm `pgrep` after disconnect; `nohup` + redirect. |
| `infer_paint.py` / `bake_pipeline.py` / xatlas on 40 GB | Wrong machine | Never. Shut 40 GB after `*_6view.png`. A6000 unwrap: GPU almost idle, process 1.3 GB RSS, ~370 GB / 503 GB RAM free, **1 hour 10 minutes** (16 min with no bar). Then bake 1.4 GB VRAM, RAM ~3 GB. Skip xatlas if UVs exist. Local CPU. |
| Bake without `*_6view.png` | Wrong order | Blender ortho → `infer_multiview` → local UV/bake. |
| Linode as GPU substitute | CPU-only | Unwrap/Blender only. Tiny 1–2 vCPU can be **slower** than the A6000 hour. |
| “Paint with a prompt” | MV-Painter has no prompt | Punchier **reference image** (eyes/teeth/light). Keep remesh. New mesh only if the **shape** is wrong. |
| Agent invents `runpodctl` stop | No RunPod API key | User stops the pod in the dashboard. |
| Overlay `/opt` empty on a new pod | Ephemeral | Persist volume blobs + tarball; rebuild overlay. |
| `HF_HOME=/workspace/.cache/huggingface` on paint infer | Volume snapshot 0-byte JSON | `export HF_HOME=/opt/hf`. `_paint_start_infer.py` still sets the volume path — **do not run it** (see §4). |
| Dramatic 3/4 desert painting as mesh input | Unseen back hallucinates; SF3D/TRELLIS pancake the side | Keyed front-on still. SF3D only reads `front.png` (`raw_desert_sf3d.glb` 546,156 bytes). Extra stills unused. Multi-view Hunyuan-2mv is licence-banned. |
| SF3D `raw.glb` as the ship mesh | Pancake; Stability $1M cap | Historical. Ship path is TRELLIS.2 remesh + MV-Painter. Record SF3D assets in `LEGAL_LIABILITY.md` if any remain in a build. |
| Windows `.venv-bpy/bin/python` | Unix lookup | `.venv-bpy/Scripts/python.exe`. bpy 4.5.13, Python 3.11. Fox CPU render ~10 min; use `render.device: GPU` on a real NVIDIA. |
| Concept attachment vanished after a mode transition | Temp image gone | Re-save under `image_assets/bosses/` / `generated/bosses/demon/concept/`. |
| One network volume on two pods | geesefs lock/corruption | One pod per volume. 24 GB mesh and 40 GB paint may run in parallel only on **separate** disks. |
| Waiting for all six remeshes before paint | 40 GB box idle | First local `mesh.glb` → start paint generate (after paint gates). Do not wait for all six. **This CHECK: meshes already local, 40 GB already stopped — do not start it.** |
| “Kill the 40 GB pod” after the user already stopped it | Agent memory | Confirm. If stopped, do not instruct another kill. |
| One-sentence disk/VRAM answer | Collapses overlay vs volume vs which file infer loads | State overlay size, volume size, blob size, and `v29_25000.ckpt` vs 15 GB safetensors. |
| `OPENCV_IO_ENABLE_OPENEXR` missing | EXR I/O off by default | Set in TRELLIS run and all Blender/infer envs (`trellis2_run.py` already sets it). |
| Seed confusion | Different stages | TRELLIS generate: `Image.convert("RGBA")`, `seed=0`. Paint: seed 12. Keep those. |
| `faulthandler` silent native abort | CuMesh | `trellis2_run.py` and `trellis2_manual_remesh.py` enable faulthandler; remesh script sets `CUDA_LAUNCH_BLOCKING=1`. Still may die without a Python traceback — measure RAM/dmesg. |

---

# 3. Happy-path copy sequences (LAST)

Do **not** start these in this CHECK task. They exist so a future agent copies a known-good order **after** the matching `GATE_*` tokens.

## 3.1 Local, now (no pod)

1. `GATE_WORKTREE` + `GATE_KEY` + `GATE_LOCAL_MESH` + `GATE_PAINT_STOPPED`.
2. Stop. Six remeshes are the checkpoint. Next **paid** work is 40 GB `infer_multiview` **after** paint gates, then local bake. Not TRELLIS again.

## 3.2 Future 24 GB mesh (only if `GATE_LOCAL_MESH_FAIL`)

1. Deploy Community **A5000/3090 24 GB**, official RunPod PyTorch **devel**, **60 GB** container disk, public IP, TCP 22, **no** paint volume, no custom start.
2. SSH: `ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25 -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp USER@ssh.runpod.io`
3. `GATE_MESH_GPU` + `GATE_MESH_NVCC` + `GATE_MESH_DISK`.
4. Hex-upload `gpu_box/trellis2_setup.sh`, `trellis2_patch.py`, `trellis2_run.py`, `_pod_mem_monitor.sh` (LF only).
5. `bash /workspace/gpu_box/trellis2_setup.sh` until `INSTALL_OK`. Never xformers. If Eigen missing, the script installs it.
6. `GATE_MESH_INSTALL` + `GATE_MESH_PATCH`.
7. User: DINOv3 agree in browser; `hf auth login` on the box. `GATE_MESH_TOKEN`.
8. Hex-upload stills to `/workspace/in/<stem>.png` (or jpg). Name = stem.
9. Generate **one** stem, remesh on, no TRELLIS texture:

```bash
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH
export HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3
export PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1
nohup /workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_run.py \
  --image /workspace/in/STEM.png \
  --out-dir /workspace/out \
  --name STEM \
  --skip-texture \
  >> /workspace/i23d.log 2>&1 &
echo $! > /workspace/trellis2.pid
nohup bash /workspace/gpu_box/_pod_mem_monitor.sh >> /workspace/monitor.log 2>&1 &
```

10. Wait for `WROTE /workspace/out/STEM_from_front.glb` and `ALL_DONE`. Hex-download to `generated/bosses/demon/variants/STEM/mesh.glb`. Bytes tens of MB.
11. **Ping the user the moment the first remesh is local** so they can start the **separate** 40 GB pod. Do not wait for all six. Do not attach this disk to that pod.

## 3.3 Future 40 GB paint generate (only after a local remesh exists)

1. Deploy **40 GB+** (A6000 fine), **50 GB volume** that already has MV-Painter blobs, overlay ~30 GB for Blender/venv. Same volume **not** mounted on the mesh pod.
2. `GATE_PAINT_GPU` + `GATE_PAINT_VOL` (blobs tens of GB — do not download).
3. Overlay rebuild (~5–10 min): extract Blender tarball → `/opt/blender`; `chmod +x`; venv `/opt/mvpaint-venv`; `_paint_rebuild_cache.py` pointers at snapshot `85a9cb12…`; `HF_HOME=/opt/hf`; `hf_transfer=0`.
4. `GATE_PAINT_HF` + `GATE_PAINT_VENV` + `GATE_PAINT_BLENDER` + `GATE_PAINT_GLTF` + `GATE_PAINT_EXR` (real `000.exr` on a sample GLB) + `GATE_PAINT_CMDS` + `GATE_PAINT_PAIR`.
5. **Then** start **one** `infer_multiview`:

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

6. Watch VRAM toward ~27 GB for 20–30 min. Do not kill. Watcher counts `*6view.png` files. GPU steps ~38 s each after load.
7. Hex-download `*_6view.png`. **User stops the 40 GB pod.**
8. Local: skip xatlas if UVs exist. Full mesh, not 30k. Bake on this PC / small CUDA. Never the 40 GB box.

Hex upload (because scp dies on the proxy), from PC:

```text
python C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\_paint_put.py LOCALFILE /workspace/mvpaint_in/glbs/STEM.glb
```

(`_paint_put.py` currently imports `_paint_pod.SSH` — **rewrite HOST** to the live Connect line first. The checked-in host is dead.)

---

# 4. Stale helper scripts that will lie

Checked-in `_*.py` at the Boss repo root are session debris. Several encode a **fixed** trap. Several encode the **bug**. Running the wrong one costs a 20–30 min UNet load or a 36 GB re-download.

| Script | Why it lies / when it is safe |
|---|---|
| `_mesh_pod.py` | Hard-coded host `4lmqwpwp84x1qs-6441135a@ssh.runpod.io`. Dead after stop. `-tt` + `ppp` pattern is right; **HOST is not**. |
| `_paint_pod.py` | Hard-coded host `luc0g32c1tmgou-64410d8b@ssh.runpod.io`. Same. Do not SSH it “to check.” |
| `_paint_start_infer.py` | `HF_HOME=/workspace/.cache/huggingface` (0-byte snapshots). `test -x` volume `blender-4.2.9`. **No** `debug_value` / OpenCV-in-Blender / `/opt/render_temp` / `000.exr` gate. Starts infer anyway. **Do not run.** |
| `_paint_fix_blender.py` | Copies **binaries only** and `ln -sfn /workspace/blender/4.2`. That is the 139 MB fake-success / geesefs symlink trap. Full overlay tree required. **Do not run.** |
| `_paint_blender_libs.py` | `ln -sfn` `.so` from volume next to overlay binary. geesefs 0-byte `.so`. **Do not run.** |
| `_paint_rebuild_cache.py` | Pointer rebuild is the right HF fix (`85a9cb12…`, skip extra 15 GB safetensors, `HF_HOME=/opt/hf`) **then it `pkill`s infer and starts infer**. Only safe after GATE_PAINT_BLENDER + GATE_PAINT_GLTF + GATE_PAINT_EXR. |
| `_paint_fix_exr_restart.py` | Correct OpenCV-in-Blender + `CMDS_BLOCK` `/opt/render_temp` patch, **then starts infer**. Same: gates first. `CMDS_BLOCK_NOT_FOUND` if whitespace drifted. |
| `_paint_gltf_fix.py` | Correct `debug_value=0` + `set_debug_log` fallback + smoke import. Smoke path hard-codes `gpt2_front_ink.glb` — fail if that pair is not uploaded. Does not start infer. Prefer this over operator-only patches. |
| `_patch_debug.py` | Addon fallback is required. Then starts `/opt/run_infer.sh` via `_pod_exec` (possibly another dead host). Patch only; do not trust the restart. |
| `_paint_pip_overlay.py` | venv-on-`/opt`, `cd /tmp`, numpy 1.26.3, EXR env — good. Then `nohup` install. Does not install Blender OpenCV. |
| `_paint_cache_sense.py` | Safe. `du` blobs before download. Run this, not a new `hf download`. |
| `_paint_watch.py` | Counts real `*6view.png`. Safe watcher. 90 min deadline. |
| `_paint_st.py` / any watcher that greps the word `6view` out of a shell script | False `HAVE_6VIEW`. |
| `_mesh_keep_going.py` | Restarts `/workspace/run_rest.sh` on a **dead host** via `_mesh_pod.py`. Meshes already local — **do not run.** |
| `_mesh_fix_eigen.py` | Re-apts Eigen even if the header exists. Only if `GATE_MESH_INSTALL` fails on Eigen. |
| `trellis2_manual_remesh.py` | No UVs. Not a paint mesh. |
| `_pod_mvpaint_infer.py` / 24 GB-safe paint | Dead end. Official UNet needs 40 GB. |
| `_pod_install_trellis2.sh` | Old `flash-attn \|\| xformers` fallback. Use `gpu_box/trellis2_setup.sh` only. |
| `_paint_kick.py`, `_paint_kick2.py`, `_paint_kick3.py`, `_paint_go.py`, `_paint_now.py`, `_paint_live.py`, `_mesh_poll_*.py`, `_paint_pip2.py` | One-shot session debris. Hosts, paths, and half-fixes. Do not chain them. |
| `_bake_full.py` / `_unwrap_est.py` on the 40 GB box | Encodes “skip crush / estimate xatlas” — **wrong machine**. Local only. |
| `LEGAL_LIABILITY.md` as the current mesh picker | Still says TRELLIS was **not selected**. Current mesh is TRELLIS.2 + isolated CuMesh. File is still the Hunyuan-ban + SF3D $1M record. Do not “correct” it by running Hunyuan. |

Canonical code (not one-shot helpers):

- `tools/boss_sprite_pipeline/gpu_box/trellis2_setup.sh`
- `tools/boss_sprite_pipeline/gpu_box/trellis2_patch.py`
- `tools/boss_sprite_pipeline/gpu_box/trellis2_run.py`
- `tools/boss_sprite_pipeline/gpu_box/_pod_mem_monitor.sh`
- `tools/boss_sprite_pipeline/gpu_box/trellis2_manual_remesh.py` (geometry crash-test only)
- This file.

---

# 5. Measured timings

Do not invent new ETAs. Quote this table.

| Event | Measured / recorded |
|---|---|
| Fox CPU render (README) | ~10 min |
| SF3D first mesh | seconds–minutes; `raw_desert_sf3d.glb` 546,156 bytes; ~6 GB peak VRAM |
| TRELLIS `1024_cascade` generate | minutes–tens of minutes on 24 GB; GPU ~3 GB during generate |
| Isolated CuMesh remesh + `to_glb remesh=False` | minutes; official UV still ~2 min |
| Manual remesh crash-test (256, no UV) | seconds; 235,695 verts; `demon_from_front_manual_remesh.glb` 8,510,464 bytes |
| Hole-fill on raw extract then in-process remesh death | 1,617,464 → 1,617,482 verts (+18); ~3,398,970 faces |
| Remesh monitor | 2 s samples; RSS ~24 GB of 256 GB; ~170 GB available; 300+ threads → 1; dmesg no OOM |
| Successful isolated remesh of 1024 extract | ~465k verts / 940k faces |
| Round-2 remesh GLBs on disk | ~45–48 MB (see §6) |
| `remesh=False` checkpoint | `demon_from_front_noremesh.glb` 27 MB, ~391k verts |
| MV-Painter pipeline 7/7 from warm `/opt/hf` | ~5 min (first component looks stuck on tqdm `\r`) |
| Custom UNet ckpt volume → VRAM (geesefs) | **~20–30 min** (local SSD: a couple of minutes) |
| Mid-load snapshot | 6.5 GB RAM, 2 GB VRAM, no `*_6view.png` yet |
| Target VRAM once loaded | climb toward ~27 GB |
| GPU 75-step paint | **~38 seconds** (not 15 min) |
| Blender ortho, small mesh | ~30 s |
| Blender ortho, ~1M remesh GLB ~47 MB | many minutes (+ glTF death until `debug_value` patched) |
| Overlay Blender/venv/`/opt/hf` rebuild on new pod | 5–10 min |
| Killing infer to “fix Blender” | another 20–30 min geesefs UNet read |
| xatlas unwrap on full remesh on A6000 | **1 hour 10 minutes** CPU; GPU idle; 1.3 GB RSS; then bake 1.4 GB VRAM |
| Six meshes in one live process | 1× UNet load + 6× (Blender + ~38 s) |
| First-session cloud cost (early estimate) | RTX 3090 $0.11–$0.22/hr; 2–5 h ≈ $0.50–$2; A5000 Community $0.16/hr |
| Secure Cloud fallback | ~$0.25–$0.50/hr |
| Failed container creates | $0.00 |
| Overlay ENOSPC numbers | expected **25327.64 MB**, free **14480.68 MB**; overlay 30G / 17G used / 14G free; cache already 13G |
| Volume usage when blobs present | **38G used**, almost all MV-Painter cache (**36G**), including **24G** `v29_25000.ckpt` |
| HDRI | ~66 MB |
| Extra unet safetensors (do not link) | ~15 GB |

---

# 6. This round’s files / stems

**Stems (six). Same name for JPG, PNG, GLB.**

| Stem | Concept JPG | Paint PNG (same stem) | Remesh GLB (checkpoint) |
|---|---|---|---|
| `gpt2_front_paint` | `concept/round2/gpt2_front_paint.jpg` (124,698) | `concept/round2_png/gpt2_front_paint.png` (910,488) | `variants/gpt2_front_paint/mesh.glb` (**47,518,728**) |
| `gpt2_front_ink` | `concept/round2/gpt2_front_ink.jpg` (140,642) | `concept/round2_png/gpt2_front_ink.png` (1,017,046) | `variants/gpt2_front_ink/mesh.glb` (**47,387,500**) |
| `gpt2_front_sculpt` | `concept/round2/gpt2_front_sculpt.jpg` (139,881) | `concept/round2_png/gpt2_front_sculpt.png` (1,065,235) | `variants/gpt2_front_sculpt/mesh.glb` (**45,702,676**) |
| `nano2_concept_art` | `concept/round2/nano2_concept_art.jpg` (738,586) | `concept/round2_png/nano2_concept_art.png` (3,709,399) | `variants/nano2_concept_art/mesh.glb` (**47,201,284**) |
| `nano2_2d_illustration` | `concept/round2/nano2_2d_illustration.jpg` (602,224) | `concept/round2_png/nano2_2d_illustration.png` (2,610,487) | `variants/nano2_2d_illustration/mesh.glb` (**47,323,308**) |
| `nano2_3d_render` | `concept/round2/nano2_3d_render.jpg` (845,384) | `concept/round2_png/nano2_3d_render.png` (3,941,734) | `variants/nano2_3d_render/mesh.glb` (**44,977,296**) |

All paths under `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\`. Manifest: `concept/round2/manifest.json` (Downloads 2026-09-18 19:44; gpt-image-2 vs nano-banana-2 notes).

**Older / do not confuse with the checkpoint**

| File | Bytes | What it is |
|---|---|---|
| `mesh/raw_desert_sf3d.glb` | 546,156 | SF3D pancake from desert painting |
| `mesh/raw.glb` / `raw_standing_prev.glb` | 1,192,196 / 1,195,676 | Earlier SF3D standing |
| `mesh/demon_from_front_manual_remesh.glb` | 8,510,464 | CuMesh crash-test, **no UVs** |
| `mesh/demon_from_front.glb` | 48,363,060 | Earlier TRELLIS remesh (pre-round2) |
| `mesh/trellis2_from_front_png.glb` | 24,959,800 | PNG-reexported TRELLIS |
| `mesh/trellis2_textured_png.glb` | 19,156,232 | TRELLIS PBR we **do not ship** as paint (`--skip-texture` now) |
| `mesh/demon_painted.glb` | 5,130,760 | Early paint on crushed mesh |
| `mesh/demon_painted_full.glb` | 38,870,500 | Paint bake on fuller mesh (still not round2) |
| `mesh/demon_6view.png` | (present) | Earlier 6-view, not round2 batch |

**Pod paths (when a future box exists)**

24 GB: `/workspace/vendor/TRELLIS.2`, `/workspace/vendor/trellis2-venv`, `/workspace/gpu_box/`, `/workspace/in/<stem>.png`, `/workspace/out/<stem>_from_front.glb`, `/workspace/.cache/huggingface/token`, `/usr/include/eigen3/Eigen/Dense`.

40 GB volume: `/workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs` (~36 GB). Overlay: `/opt/hf` snapshot `85a9cb12b444a73ba922ac44fd198e8de12f8a9d`, `/opt/blender/blender`, `/opt/mvpaint-venv`, `/opt/render_temp/<uid>/depth/000.exr`. Ckpt: `unet_w_controlnet/v29_25000.ckpt`. Code: `/workspace/MV-Painter/MVPainter/infer_multiview.py`. Inputs: `/workspace/mvpaint_in/glbs/<stem>.glb`, `imgs/<stem>.png`. Out: `/workspace/mvpaint_out/*_6view.png`.

**Env (mesh)**  
`--skip-texture` `ATTN_BACKEND=sdpa` `SPARSE_ATTN_BACKEND=flash_attn` `HF_HUB_ENABLE_HF_TRANSFER=0` `TORCH_CUDA_ARCH_LIST=8.6` `MAX_JOBS=2` `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`

**Env (paint)**  
`--geo_rotation -90 --no_rembg` `HF_HOME=/opt/hf` `HF_HUB_ENABLE_HF_TRANSFER=0` `OPENCV_IO_ENABLE_OPENEXR=1` `PYTHONUNBUFFERED=1`

---

## Contrast (why this copy is not a numbered pipeline)

Typical runbooks list steps 1–N and hide failures in footnotes. This copy **refuses generate** until a `GATE_*` token exists, then treats **log lines as the index**. Happy-path sequences are last on purpose: the last two 40 GB deaths were agents who started infer with a subset of Blender checks.

`LEGAL_LIABILITY.md` still describes an older pick (SF3D; TRELLIS v1 rejected). The live factory is **TRELLIS.2 + isolated CuMesh** for mesh and **MV-Painter Apache-2.0** for paint. Hunyuan mesh and Hunyuan-Paint stay banned in Europe.

**Do not start pods from this CHECK.** Six remeshes are on disk. The 40 GB box is already stopped.
