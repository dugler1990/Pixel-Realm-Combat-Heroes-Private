# CHECK 05 / 10 — TRELLIS.2 + MV-PAINTER COMMAND BOOK

Independent reconstruction. Primary sources only:
`tools/boss_sprite_pipeline/gpu_box/trellis2_{setup.sh,run.py,patch.py,manual_remesh.py}`,
`LEGAL_LIABILITY.md`, Boss-root `_paint_*.py` `_mesh_*.py` `_patch_debug.py`,
transcript `2deac9fc-9bd5-40c9-ad56-00b5f647da84.jsonl`.
Every section is a copy-paste block. Comments are the traps and the exact fix.
No Hunyuan. No xatlas on 40GB. No 30k crush. No commit of `ppp`. No checkout of dirty `dev_tmxlevels`.

---

## CMD-00 BAN — Hunyuan mesh + Hunyuan paint

```powershell
# TRAP: old plan / Spaces / "just try Hunyuan-2mv" looks like the quality path.
# LAW: Tencent Hunyuan3D-2 / 2.1 / 2mv community license EXCLUDES EU, UK, South Korea.
# LAW: LEGAL_LIABILITY.md rejects Hunyuan for this EU/UK commercial project.
# LAW: transcript — do not run Hunyuan mesh OR Hunyuan paint. Do not "say the mesh was made elsewhere."
# FIX: mesh = Microsoft TRELLIS.2 image-to-3D on 24GB. paint = shaomq/MVPainter infer_multiview on 40GB+.
# FIX: TRELLIS.2 texturing pipeline is NOT the paint stage. Use --skip-texture on the 24GB box.
# NOTE: TRELLIS v1 textured-GLB path pulls NVIDIA nvdiffrast/nvdiffrec (non-commercial). That is why
#       LEGAL_LIABILITY.md rejected TRELLIS as the *ship* backend. This book still uses TRELLIS.2
#       for geometry only (--skip-texture + isolated CuMesh remesh + to_glb remesh=False, PNG not WebP).
# NOTE: Stable Fast 3D is the older 1-image fallback (Stability Community License, < USD 1M revenue).
#       Do not mix SF3D, Hunyuan, and TRELLIS.2 on the same GLB without a Gate A decision.
Write-Host "BAN_OK Hunyuan mesh+paint off. TRELLIS.2 geo + MV-Painter UNet + local bake."
```

---

## CMD-01 WORKTREE + KEY — do not switch dirty Private, do not commit ppp

```powershell
# TRAP: checkout is Pixel-Realm-Combat-Heroes-Private on dirty branch dev_tmxlevels.
# TRAP: origin/dev_3d_boss exists; switching THIS worktree destroys uncommitted TMX work.
# FIX: isolated worktree already exists: C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
# FIX: never `git switch` / `git checkout` inside the Private tree for this job.
# TRAP: ~/.ssh/id_ed25519 DOES NOT EXIST on this PC. RunPod SSH lines that cite it fail.
# FIX: private key is C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp
# TRAP: ppp is a live SSH private key sitting next to the game repo.
# FIX: do NOT git add ppp / ppp.pub. Do NOT commit. Do NOT push. Do NOT paste the key or HF token in chat.
# TRAP: scp/ssh without -tt to ssh.runpod.io hangs or drops (RunPod proxy wants a TTY).
# FIX: helpers _mesh_pod.py and _paint_pod.py already use ssh -tt. Copy that.
Set-Location C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
git -C C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private branch --show-current
# expect: dev_tmxlevels  — leave it
git branch --show-current
# expect: this is the Boss worktree (dev_3d_boss family)
Test-Path C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp
# expect: True
Get-Item C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp | Select-Object FullName,Length
# if someone stages it:
git -C C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private status --short -- ppp ppp.pub
# if it shows ?? or M — unstage, do not commit
```

---

## CMD-02 COST SPLIT — 24GB mesh / 40GB UNet / local bake

```powershell
# TRAP: one fat pod "does everything" (mesh + paint + xatlas + bake). That is how the A6000 burned an hour.
# LAW:
#   1) TRELLIS.2 1024_cascade + isolated CuMesh remesh  = 24GB-class (A5000 / 3090). Never 40GB for remesh.
#   2) MV-Painter custom UNet (~25.3GB .ckpt) must SIT IN VRAM for 75-step infer = 40GB+ only (A6000 48GB ok).
#   3) UV / xatlas / bake / Blender camera                          = THIS PC (CPU). Local NVIDIA if bake needs CUDA.
# TRAP: "never xatlas/30k on 40GB". Official infer_paint remeshes toward ~30k (blender_low) so bake is cheap.
#       That crushed 930k-face remesh to 53k. Paint looked wrong. Paid an hour of xatlas on 930k faces on A6000.
# FIX: 40GB box runs infer_multiview ONLY. --geo_rotation -90 --no_rembg. Stop the pod when *_6view.png exist.
# FIX: do NOT run infer_paint / remesh_reduce / xatlas.parametrize / bake_pipeline on the 40GB box.
# FIX: TRELLIS to_glb already wrote UVs. Local bake REUSES those UVs. Skip xatlas if the remesh already has UVs.
# FIX: full remesh (~45-48MB, ~800k-1M faces). Never decimate to 30k. Never blender_low.obj as the ship mesh.
# TIMING (measured, not guessed):
#   VRAM load of 25.3GB ckpt off geesefs volume = 20-30 min ONCE per infer process
#   GPU paint 75 steps                         = ~38 seconds (not 15 min)
#   Blender ortho of 1M remesh                 = minutes (30s on the old small mesh)
#   restart after Blender crash                = pay the 20-30 min load AGAIN
# TRAP: quoting "15 min if weights on volume" is a lie. Volume = on disk, not in VRAM.
# CHECKPOINT NOW (2026-09-19):
#   All six remesh GLBs are ALREADY on this PC (~45-48MB each).
#   The 40GB paint pod is ALREADY STOPPED. Do not start it until GATE-PAINT-BLENDER is green.
#   Do not remesh again. Next rental is paint-only.
$names = @(
  'gpt2_front_paint','gpt2_front_ink','gpt2_front_sculpt',
  'nano2_concept_art','nano2_2d_illustration','nano2_3d_render'
)
$root = 'C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants'
foreach ($n in $names) {
  $p = Join-Path $root "$n\mesh.glb"
  if (Test-Path $p) {
    '{0} {1:N1} MB' -f $n, ((Get-Item $p).Length/1MB)
  } else {
    "MISSING $p"
  }
}
# expect: six files, each ~45-48 MB, each > 1_000_000 bytes
```

---

## CMD-03 SSH MESH — 24GB TRELLIS pod (`_mesh_pod.py`)

```powershell
# TRAP: last mesh host was 4lmqwpwp84x1qs-6441135a@ssh.runpod.io — hosts DIE when the pod is stopped.
# TRAP: ssh without -tt to ssh.runpod.io. BatchMode-only also flakes on the proxy.
# FIX: ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25
# FIX: -i C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp
# TRAP: pasting the Hugging Face token in this chat. Login happens ON THE POD only.
# TRAP: connection refused = pod stopped. Get a NEW Connect SSH line from RunPod. Do not invent a host.
$KEY = 'C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp'
$HOST = 'PASTE-NEW-MESH-POD@ssh.runpod.io'   # replace; old 4lmqwpwp84x1qs is dead when stopped
ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25 -i $KEY $HOST
# once on the box, paste CMD-06+ as the remote body, or drive it via python _mesh_pod.py
```

```bash
# remote probe — same as _mesh_pod.PROBE
# TRAP: 16GB Ada is a bad bet for TRELLIS.2. Need ~24GB+ (A5000/3090).
# TRAP: image without nvcc (non-devel) cannot compile nvdiffrast/CuMesh/o-voxel.
# FIX: runpod/pytorch CUDA devel image. Need nvcc, g++, git, CUDA torch.
echo CONNECTED
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
# expect: RTX A5000 (or 3090), 24564 MiB class
df -h / /workspace
ls -d /workspace/vendor/TRELLIS.2 /workspace/vendor/trellis2-venv /workspace/gpu_box
test -s /workspace/.cache/huggingface/token && echo TOKEN_OK || echo TOKEN_MISSING
python3 - <<'PY'
import torch
print("TORCH", torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))
PY
nvcc --version | tail -1
which g++ git python3
```

---

## CMD-04 SSH PAINT — 40GB+ MV-Painter pod (`_paint_pod.py`)

```powershell
# TRAP: last paint host was luc0g32c1tmgou-64410d8b@ssh.runpod.io — 40GB POD ALREADY STOPPED.
# LAW: do not Start that dead box until GATE-PAINT-BLENDER (CMD-23) is green on a NEW deploy.
# TRAP: id_ed25519 in the RunPod Connect string. This PC does not have it. Swap in ppp.
# TRAP: attaching the paint network volume to the mesh pod AT THE SAME TIME. geesefs will eat the volume.
# FIX: one volume, one live pod. 24GB remesh OR 40GB paint, never both mounted together.
$KEY = 'C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\ppp'
$HOST = 'PASTE-NEW-PAINT-POD@ssh.runpod.io'  # replace; luc0g32c1tmgou is the stopped one
ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=25 -i $KEY $HOST
```

```bash
# remote paint probe — same spirit as _paint_probe.py
# TRAP: df -h /workspace on geesefs LIES (shows ~1 petabyte). Use du of real trees + findmnt.
# TRAP: 30GB container disk. Official ckpt is 25.3GB. 13GB pipeline + 25.3GB ckpt must coexist (~40GB models).
# FIX: A6000 (48GB VRAM) + network volume in THE SAME datacenter, 50GB+ volume (80GB slack). Not 30GB.
# FIX: volume attaches only at Deploy. You cannot bolt one onto a running pod.
echo ---GPU---
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader
# expect: A6000 / 40GB+ class. 24GB here = OOM on the UNet. Stop.
echo ---MOUNTS---
findmnt -T /workspace -o TARGET,SOURCE,FSTYPE,SIZE,USED,AVAIL || true
df -hT / /workspace /opt
# TRAP: SIZE=1.0P on /workspace is geesefs fiction. Ignore it.
echo ---HF---
du -sh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter 2>/dev/null
ls /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/snapshots/*/unet_w_controlnet/v29_25000.ckpt 2>/dev/null
# expect: ~36GB tree, ckpt ~25.3GB. If missing, you will download 25.3GB NOT 15GB.
```

---

## CMD-05 GATE TOKENS — accept pages, then login ON THE POD

```bash
# TRAP: "HF login" without opening the gated pages first. Download then 401/403.
# TRAP: agreeing is not approval. DINOv3 sat on "awaiting review from the repo authors."
# TRAP: starting TRELLIS.2 generate before token exists on THIS pod (tokens do not persist across pods).
# GATES YOU MUST ACCEPT IN A BROWSER (same HF account as the token), then wait until Files tab opens:
#   1) https://huggingface.co/microsoft/TRELLIS.2-4B
#   2) https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m
#      check https://huggingface.co/settings/gated-repos — must say accepted, not pending
# GATES YOU MUST NOT TOUCH:
#   briaai/RMBG-2.0  — skip. Concept stills already have alpha / we force RGBA. Do not request access.
#   any Hunyuan repo — banned (CMD-00)
# PUBLIC (no login if volume already has blobs):
#   shaomq/MVPainter — 25.3GB v29_25000.ckpt. Last paint pod had 36GB on the volume. Reuse. No HF login.
# TOKEN RULES:
#   fine-grained READ only. No write, no org. Do not paste token in chat.
#   write it to $HF_HOME/token AND copy to /root/.cache/huggingface/token (some libs ignore HF_HOME).
#   export HF_HUB_ENABLE_HF_TRANSFER=0   — hf_transfer blows small disks and geesefs.
export HF_HOME=/workspace/.cache/huggingface
mkdir -p "$HF_HOME" /root/.cache/huggingface
# YOU type the token on the pod, not here:
# /workspace/vendor/trellis2-venv/bin/hf auth login --token hf_YOUR_TOKEN
/workspace/vendor/trellis2-venv/bin/hf auth whoami
test -s "$HF_HOME/token" && echo TOKEN_OK || echo TOKEN_MISSING
cp -f "$HF_HOME/token" /root/.cache/huggingface/token
# GATE test: can you actually open a JSON? "whoami" is not enough.
# python: huggingface_hub.hf_hub_download('facebook/dinov3-vitl16-pretrain-lvd1689m','config.json')
# 403 pending = STOP the pod, wait for email, do not loop.
```

---

## CMD-06 MESH UPLOAD — stills + gpu_box over TTY hex (`_mesh_upload.py`)

```powershell
# TRAP: scp to ssh.runpod.io proxy. Use gzip+hex over the same -tt SSH as _mesh_upload.py / _paint_put.py.
# TRAP: Windows CRLF on .sh. First byte of trellis2_setup.sh must be 23 21 ('#!'), not 0d.
# FIX: after upload, remote `sed -i 's/\r$//' /workspace/gpu_box/trellis2_*.sh /workspace/gpu_box/trellis2_*.py`
# INPUTS (round2 JPEGs — these are what the night remesh queue used):
#   generated/bosses/demon/concept/round2/{gpt2_front_paint,gpt2_front_ink,gpt2_front_sculpt,
#     nano2_concept_art,nano2_2d_illustration,nano2_3d_render}.jpg
#   -> /workspace/in/<name>.jpg
# TRAP: JPEG has no real alpha. rembg_model=None then .to() crashes; also preprocess assumes rembg output.
# FIX: patches in CMD-11. Do not feed Hunyuan. Do not skip the rembg None-guards because "--no_rembg".
# SCRIPTS:
#   tools/boss_sprite_pipeline/gpu_box/trellis2_{setup.sh,patch.py,run.py} -> /workspace/gpu_box/
Set-Location C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
python _mesh_upload.py
# or remaining stills only:
# python _mesh_upload_rest.py
```

```bash
# remote verify after upload
ls -lh /workspace/in /workspace/gpu_box
file /workspace/gpu_box/trellis2_setup.sh
head -c 80 /workspace/gpu_box/trellis2_setup.sh | od -An -tx1 | head -1
# expect: 23 21 ...   if 0d 0a — CRLF, sed -i 's/\r$//'
sed -i 's/\r$//' /workspace/gpu_box/trellis2_setup.sh /workspace/gpu_box/trellis2_patch.py /workspace/gpu_box/trellis2_run.py
chmod +x /workspace/gpu_box/trellis2_setup.sh
```

---

## CMD-07 MESH CLONE — zip, not hung git (`_mesh_zip_clone.py`)

```bash
# TRAP: `git clone --depth 1 https://github.com/microsoft/TRELLIS.2.git` sat for hours on Community.
# FIX: kill it. curl the tarball. Fake a .git so setup.sh's `[ -d $ROOT/.git ]` is happy.
# TRAP: setup.sh then `git submodule update --init --recursive` — if zip has no .gitmodules work, still ok
#       for the files; o-voxel is copied out of the tree later.
pkill -9 -f 'git clone.*TRELLIS' || true
pkill -9 -f 'git-remote-https' || true
pkill -9 -f 'git-index-pack' || true
rm -rf /workspace/vendor/TRELLIS.2 /tmp/trellis2.tgz
mkdir -p /workspace/vendor
curl -L --fail --retry 5 --retry-delay 2 -o /tmp/trellis2.tgz \
  https://codeload.github.com/microsoft/TRELLIS.2/tar.gz/refs/heads/main
tar -xzf /tmp/trellis2.tgz -C /tmp
mv /tmp/TRELLIS.2-main /workspace/vendor/TRELLIS.2
git -C /workspace/vendor/TRELLIS.2 init
ls /workspace/vendor/TRELLIS.2/o-voxel >/dev/null && echo OVOXEL_OK
du -sh /workspace/vendor/TRELLIS.2
```

---

## CMD-08 MESH SETUP — `trellis2_setup.sh` (A5000 24GB, torch 2.8+cu128)

```bash
# TRAP: pip install xformers unconstrained. It pulls a SECOND torch and fills a 30GB disk.
# FIX: never pip install xformers. ATTN_BACKEND=sdpa, SPARSE_ATTN_BACKEND=flash_attn, prebuilt wheel only.
# TRAP: o_voxel compile without Eigen. Missing /usr/include/eigen3/Eigen/Dense. Hours of "resume".
# FIX: apt-get install libeigen3-dev THEN export CPATH and CPLUS_INCLUDE_PATH to /usr/include/eigen3
# TRAP: MAX_JOBS default. CuMesh compile RAM-kills the box.
# FIX: MAX_JOBS=2 (setup.sh) or 1 if the compile still dies. TORCH_CUDA_ARCH_LIST=8.6 on A5000.
# TRAP: HF_HUB_ENABLE_HF_TRANSFER=1 on a small overlay. Leave it 0.
# TRAP: venv without --system-site-packages loses the image torch.
# FIX: python3 -m venv /workspace/vendor/trellis2-venv --system-site-packages
# TRAP: flash-attn source build. Use the Dao-AILab wheel:
#   flash_attn-2.8.3.post1+cu{CUDA}torch{MAJOR.MINOR}cxx11abi{TRUE|FALSE}-{py}-{py}-linux_x86_64.whl
#   pip install --no-deps /tmp/flash_attn-*.whl
# TRAP: setup.sh does NOT download microsoft/TRELLIS.2-4B. Token must exist before trellis2_run.py.
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST=8.6
export MAX_JOBS=2
export HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa
export SPARSE_ATTN_BACKEND=flash_attn
export HF_HOME=/workspace/.cache/huggingface
export CPATH="${CPATH:+$CPATH:}/usr/include/eigen3"
export CPLUS_INCLUDE_PATH="${CPLUS_INCLUDE_PATH:+$CPLUS_INCLUDE_PATH:}/usr/include/eigen3"
test -f /usr/include/eigen3/Eigen/Dense || {
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libeigen3-dev
}
# if clone already done:
nohup bash /workspace/gpu_box/trellis2_setup.sh > /workspace/setup.log 2>&1 &
echo SETUP_PID=$!
# poll: grep INSTALL_OK /workspace/setup.log
# expect: INSTALL_OK <torch> NVIDIA RTX A5000
# if o-voxel died mid-way, do NOT rerun the whole clone. Use CMD-09.
```

---

## CMD-09 MESH RESUME o-voxel — Eigen + flash-attn + patches (`_mesh_resume_ovoxel.py`)

```bash
# TRAP: rerunning trellis2_setup.sh from the top after Eigen was the only miss. Wastes the compiled wheels.
# FIX: install Eigen, copy o-voxel out of the repo (setup does rm -rf then cp -a), pip --no-build-isolation,
#      fetch flash-attn wheel, pip --no-deps, then python /workspace/gpu_box/trellis2_patch.py
export PATH=/usr/local/cuda/bin:$PATH CUDA_HOME=/usr/local/cuda
export TORCH_CUDA_ARCH_LIST=8.6 MAX_JOBS=2
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3
test -f /usr/include/eigen3/Eigen/Dense || {
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libeigen3-dev
}
source /workspace/vendor/trellis2-venv/bin/activate
rm -rf /workspace/vendor/extensions/o-voxel
cp -a /workspace/vendor/TRELLIS.2/o-voxel /workspace/vendor/extensions/o-voxel
MAX_JOBS=2 pip install /workspace/vendor/extensions/o-voxel --no-build-isolation
python /workspace/gpu_box/trellis2_patch.py
python -c "import nvdiffrast, o_voxel, torch; print('INSTALL_OK', torch.__version__, torch.cuda.get_device_name(0))"
```

---

## CMD-10 MESH PATCH — rembg skip + DINOv3 Transformers 5 (`trellis2_patch.py`)

```bash
# TRAP: pipeline constructs gated briaai/RMBG-2.0. 401. Hours waiting on a gate we do not need.
# FIX: pipeline.rembg_model = None  in BOTH trellis2_image_to_3d.py AND trellis2_texturing.py
# TRAP: rembg_model=None then self.rembg_model.to(self.device)  → AttributeError. Job dies after load.
# FIX: `if self.rembg_model is not None: self.rembg_model.to(self.device)`  (i23d + texturing)
# TRAP: JPEG / no-alpha still hits preprocess that does rembg_model(input). Same crash, different line.
# FIX: if rembg_model is None: output = input.convert('RGBA') else: old rembg path
#       (_mesh_skip_rembg_restart.py). JPEGs from round2 MUST take this branch.
# TRAP: Transformers 5 moved DINOv3 encoder layers under .model. extract_features walks self.model.layer
#       and dies. facebook/dinov3-vitl16-pretrain-lvd1689m then looks "broken".
# FIX: layer_root = self.model if hasattr(self.model,'layer') else getattr(self.model,'model',self.model)
#      (trellis2_patch.py DINO_NEW). Already-patched is the string `layer_root = self.model if hasattr`.
# RUN: python /workspace/gpu_box/trellis2_patch.py
#      then apply the preprocess RGBA skip from _mesh_skip_rembg_restart.py if JPEGs are the input.
python /workspace/gpu_box/trellis2_patch.py
python3 - <<'PY'
from pathlib import Path
p = Path("/workspace/vendor/TRELLIS.2/trellis2/pipelines/trellis2_image_to_3d.py")
t = p.read_text(encoding="utf-8")
old = """            input = input.convert('RGB')
            if self.low_vram:
                self.rembg_model.to(self.device)
            output = self.rembg_model(input)
            if self.low_vram:
                self.rembg_model.cpu()
"""
new = """            if self.rembg_model is None:
                output = input.convert('RGBA')
            else:
                input = input.convert('RGB')
                if self.low_vram:
                    self.rembg_model.to(self.device)
                output = self.rembg_model(input)
                if self.low_vram:
                    self.rembg_model.cpu()
"""
if "if self.rembg_model is None:" in t and "output = input.convert('RGBA')" in t:
    print("SKIP_ALREADY")
elif old not in t:
    raise SystemExit("SKIP_PATTERN_MISSING")
else:
    p.write_text(t.replace(old, new, 1), encoding="utf-8")
    print("SKIP_PATCHED")
PY
```

---

## CMD-11 MESH GENERATE ONE — `trellis2_run.py --skip-texture`

```bash
# TRAP: running generate+texture on 24GB. Texture is MV-Painter on 40GB. Always --skip-texture.
# TRAP: remesh=True inside the generate process (same Python as 1024_cascade). CuMesh atlas.cu
#       CUDA 700 / "Building BVH" vanish / no traceback = GPU illegal access after a prior to_glb.
# FIX: generate → save_extract .pt → isolated remesh in THIS process (export_isolated_remesh):
#      fill_holes → cuBVH → remesh_narrow_band_dc(band=1, project_back=0, resolution from voxel grid)
#      → simplify 1_000_000 → to_glb(..., remesh=False, texture_size=2048, extension_webp=False)
# TRAP: official to_glb remesh=True on the 3.4M-face raw extract. Hole-fill +18 verts then death.
# FIX: remesh AFTER generate, on the extract, isolated. Or remesh a remesh=False decimated mesh
#      via trellis2_manual_remesh.py in a FRESH process (CUDA_LAUNCH_BLOCKING=1).
# TRAP: 1024_cascade OOM. Script already retries pipeline_type="512". Do not drop to a 16GB card.
# TRAP: WebP textures (EXT_texture_webp). Windows 3D Viewer rejects the GLB.
# FIX: glb.export(..., extension_webp=False) already in trellis2_run.py
# TRAP: starting without HF token / DINOv3 still pending. 20-30 min load then 401. Stop first.
# ENV (copy every restart — "subset of flags" is how nights died):
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH
export HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3
export OPENCV_IO_ENABLE_OPENEXR=1
pgrep -af trellis2_run.py && echo ALREADY && exit 0
: > /workspace/i23d.log
nohup /workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_run.py \
  --image /workspace/in/gpt2_front_paint.jpg \
  --out-dir /workspace/out \
  --name gpt2_front_paint \
  --skip-texture \
  >> /workspace/i23d.log 2>&1 &
echo STARTED $!
# expect log: LOAD_I23D → RUN pipeline_type=1024_cascade → GENERATE verts/faces
#             → BEGIN isolated remesh=True (no UV bake) → WROTE ..._from_front.glb ~45-48MB
#             → ALL_DONE
# LOAD_I23D 20-30 min of HF + VRAM is normal. Do not kill it for "idle GPU".
```

---

## CMD-12 MESH QUEUE SIX — skip existing (`_mesh_queue_rest.py`)

```bash
# TRAP: rerunning the first name. Queue must SKIP_EXISTS if /workspace/out/${name}_from_front.glb is there.
# TRAP: waiting for all six before starting paint. Start 40GB the moment the FIRST remesh is on the PC.
#       (Tonight that ship sailed: all six are already local. Paint pod is stopped.)
# NAMES (locked):
#   gpt2_front_paint (already done first)
#   gpt2_front_ink gpt2_front_sculpt nano2_concept_art nano2_2d_illustration nano2_3d_render
cat > /workspace/run_rest.sh << 'END'
#!/bin/bash
set -euxo pipefail
export CUDA_HOME=/usr/local/cuda PATH=/usr/local/cuda/bin:$PATH
export HF_HOME=/workspace/.cache/huggingface HF_HUB_ENABLE_HF_TRANSFER=0
export ATTN_BACKEND=sdpa SPARSE_ATTN_BACKEND=flash_attn
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/usr/include/eigen3 CPLUS_INCLUDE_PATH=/usr/include/eigen3
PY=/workspace/vendor/trellis2-venv/bin/python
for name in gpt2_front_ink gpt2_front_sculpt nano2_concept_art nano2_2d_illustration nano2_3d_render; do
  out=/workspace/out/${name}_from_front.glb
  if [ -f "$out" ]; then
    echo SKIP_EXISTS $name
    continue
  fi
  echo JOB $name
  $PY -u /workspace/gpu_box/trellis2_run.py --image /workspace/in/${name}.jpg --out-dir /workspace/out --name "$name" --skip-texture
done
echo REST_ALL_DONE
END
sed -i 's/\r$//' /workspace/run_rest.sh
chmod +x /workspace/run_rest.sh
pgrep -af trellis2_run.py && echo ALREADY && exit 0
nohup bash /workspace/run_rest.sh >> /workspace/i23d_rest.log 2>&1 &
# pace that actually worked: one remesh every ~5-8 min AFTER the first pipeline is hot
# LOAD_I23D spike ~18GB RAM / high CPU is the successful path, not an OOM. Host RAM was 251 Gi; peak ~23GB.
```

---

## CMD-13 MESH PULL — TTY gzip+hex (`_mesh_pull_glb.py`)

```powershell
# TRAP: scp "in parallel" as the only path. RunPod proxy often will not carry a 46MB scp.
# FIX: python _mesh_pull_glb.py /workspace/out/<name>_from_front.glb <local mesh.glb>
# FIX: markers META / STARTHEX / ENDHEX. Verify sha256. Size must be > 1_000_000.
# LOCAL:
#   C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\variants\<name>\mesh.glb
# CHECKPOINT: these six are ALREADY pulled (~45-48MB). Do not remesh to "have them again."
Set-Location C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
# python _mesh_pull_glb.py /workspace/out/gpt2_front_paint_from_front.glb `
#   generated\bosses\demon\variants\gpt2_front_paint\mesh.glb
# or: python _mesh_keep_going.py   # polls, pulls each as it lands, restarts queue if dead
Get-ChildItem generated\bosses\demon\variants\*\mesh.glb | Select-Object FullName,Length
```

---

## CMD-14 MESH WATCH — do not confuse load with death (`_mesh_job.py` / `_mesh_watch.py`)

```bash
# TRAP: GPU 0% + high CPU during LOAD_I23D → "it's stuck, restart." That restart is how hours burned.
# FIX: look for WROTE / ALL_DONE / OOM / 401 / gated / Traceback. Idle GPU during load is normal.
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
pgrep -af 'run_rest|trellis2_run' || echo DEAD
ls -lh /workspace/out/*.glb /workspace/out/*.pt
grep -nE 'Error|401|403|gated|token|OOM|Traceback|WROTE|ALL_DONE|401 Client' /workspace/i23d.log | tail -20
dmesg -T | grep -iE 'killed process|Out of memory|oom' | tail -8 || true
# if DEAD and no GLB and rembg/None.to or Eigen or token — patch THAT, do not redeploy the GPU.
```

---

## CMD-15 PAINT DEPLOY — disk arithmetic, 25.3GB ckpt not 15GB

```powershell
# TRAP: "enough disk for ~15GB weights." That was the safetensors sibling.
# LAW: official infer pulls unet_w_controlnet/v29_25000.ckpt = 25327.64 MB (~25.3GB).
# LAW: pipeline cache ~13GB + 25.3GB ckpt must sit on the SAME path at the same time (~38-40GB models).
# TRAP: 30GB container disk. HF: expected 25327.64 MB, free 14480.68 MB, ENOSPC (os error 28). GPU idle 0 MiB.
# TRAP: deleting the 13GB cache to "make room" then re-downloading 13+25. Still ~38GB. Slack ~2GB. No.
# TRAP: 50GB Iceland volume + A6000 in another datacenter. Volume only mounts in the SAME datacenter.
# TRAP: attach volume to a RUNNING pod. Impossible. Terminate, Deploy with volume selected.
# TRAP: 30GB container + 50GB volume do NOT add. HF writes both files next to each other on one path.
# FIX: Deploy RTX A6000 (48GB) WITH a 50GB+ network volume in that GPU's datacenter. 80GB if scared.
# FIX: do not squeeze 15GB safetensors as a 24GB workaround. 24GB VRAM OOMs the UNet anyway.
# FIX: 40GB pod is STOPPED. Weights (~36GB) stay on the volume. Next paint pod: attach THE SAME volume.
# FIX: container overlay ~30GB is for /opt/blender + /opt/mvpaint-venv + /opt/render_temp + /opt/hf pointers.
#      Weights stay on /workspace/.cache/huggingface. Do not copy 36GB onto overlay.
Write-Host "PAINT_DISK_LAW 25.3GB ckpt + ~13GB pipeline on the volume. 40GB+ VRAM. Overlay for Blender only."
```

---

## CMD-16 PAINT GEESEFS — chmod, symlink, 0-byte HF

```bash
# TRAP: blender binary lives on the network volume. chmod +x is a no-op on geesefs. --version fails.
# TRAP: geesefs turns .so symlinks into 0-byte files. Volume Blender "is there" (1.3GB) and will not run.
# TRAP: MV-Painter as a symlink to /opt on the overlay. Overlay dies with the pod. Next pod looks empty.
# TRAP: venv on geesefs cannot write binaries. pip "works" then the venv is broken.
# TRAP: HF snapshot files are 0-byte pointers. 36GB blobs are fine. snapshot_download thinks weights missing
#       and starts a 25.3GB re-fetch onto a 30GB overlay. ENOSPC. Overnight loop.
# TRAP: df / findmnt size on geesefs. Ignore the petabyte. du the real trees.
# FIX:
#   weights + repo + a Blender .tar.xz  → VOLUME (/workspace)
#   extract Blender + venv + render_temp + HF snapshot SYMLINKS → OVERLAY (/opt)
#   ln -sfn volume blobs → overlay snapshot files
#   HF_HOME=/opt/hf for infer so pointers are writable
#   NEVER chmod +x as the "fix" for volume blender. Copy or extract to /opt/blender.
# SNAP: 85a9cb12b444a73ba922ac44fd198e8de12f8a9d
# SKIP: extra ~15GB *.safetensors under unet_w_controlnet — we have the 25.3GB ckpt. Do not fetch them.
mkdir -p /opt/hf/hub/models--shaomq--MVPainter/refs /opt/render_temp /opt/mvpaint-venv /workspace/logs
ln -sfn /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs \
        /opt/hf/hub/models--shaomq--MVPainter/blobs
SNAP=/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d
mkdir -p "$SNAP"
echo 85a9cb12b444a73ba922ac44fd198e8de12f8a9d > /opt/hf/hub/models--shaomq--MVPainter/refs/main
# then rebuild snapshot symlinks (CMD-17). find 0-byte files FIRST:
find /workspace/.cache/huggingface/hub/models--shaomq--MVPainter -type f -size 0 | head
find /opt/hf/hub/models--shaomq--MVPainter -type f -size 0 | head
# 0-byte JSON/config = rebuild pointers. 0-byte ckpt = real damage, stop, do not infer.
```

---

## CMD-17 PAINT HF POINTER REBUILD — (`_paint_rebuild_cache.py`)

```bash
# TRAP: snapshot_download of the whole model. 25.3GB + 15GB safetensors onto overlay. Death.
# FIX: walk HF API tree, symlink each file to blobs/<oid> if blob size > 0.
#      skip path.endswith('.safetensors') and 'unet_w_controlnet' in path  (the extra 15GB).
#      fetch ONLY missing tiny json/txt (KB). Print MISSING_FETCHED.
export HF_HUB_ENABLE_HF_TRANSFER=0 HF_HOME=/opt/hf
/opt/mvpaint-venv/bin/python - << 'PY'
import json, os, urllib.request
from pathlib import Path
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
snap = Path("/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d")
blobs = Path("/opt/hf/hub/models--shaomq--MVPainter/blobs")
data = json.loads(urllib.request.urlopen(
    "https://huggingface.co/api/models/shaomq/MVPainter/tree/main?recursive=1", timeout=60).read())
missing = []
for x in data:
    if x.get("type") != "file":
        continue
    path = x["path"]
    if path.endswith(".safetensors") and "unet_w_controlnet" in path:
        continue  # we have the ckpt, not this extra 15GB
    lfs = x.get("lfs") or {}
    oid = lfs.get("oid") or x.get("oid")
    dest = snap / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = blobs / oid
    if src.is_file() and src.stat().st_size > 0:
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(os.path.relpath(src, dest.parent))
        print("LINK", path, "->", oid, src.stat().st_size)
    else:
        missing.append(path)
        url = "https://huggingface.co/shaomq/MVPainter/resolve/main/" + path
        print("FETCH", path)
        dest.write_bytes(urllib.request.urlopen(url, timeout=60).read())
        print("WROTE", path, dest.stat().st_size)
print("MISSING_FETCHED", missing)
print("model_index", (snap/"model_index.json").read_text()[:120])
# TRAP: empty model_index.json (0-byte geesefs). This print must be real JSON, not blank.
PY
# GATE: test -s of model_index.json and of the ckpt blob. whoami is not a cache gate.
ls -lh /opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d/model_index.json
ls -lh /workspace/.cache/huggingface/hub/models--shaomq--MVPainter/blobs | awk '$5+0>1000000000'
```

---

## CMD-18 PAINT BLENDER — 4.2.4 on overlay, 4.2.9 path lie

```bash
# TRAP: official infer_multiview hardcodes blender_path ='../blender-4.2.9-linux-x64/blender'
#       We install blender-4.2.4-linux-x64. Path miss → Blender never runs → missing depth EXR.
# TRAP: `test -x /workspace/MV-Painter/blender-4.2.9-linux-x64/blender` after a symlink to BROKEN volume blender.
# TRAP: `blender --version` as "ready." Version can print while glTF import is dead and cv2 is missing.
# TRAP: running volume blender in place. geesefs 0-byte .so + no +x.
# FIX:
#   curl https://download.blender.org/release/Blender4.2/blender-4.2.4-linux-x64.tar.xz
#   mv blender-4.2.4-linux-x64 /opt/blender
#   chmod +x /opt/blender/blender   # overlay, this works
#   ln -sfn /opt/blender /workspace/MV-Painter/blender-4.2.9-linux-x64
#   AND patch infer_multiview.py blender_path ='/opt/blender/blender'
#   AND pass --output_dir /opt/render_temp  (overlay, not geesefs render_temp)
#   AND replace "render_temp" string with /opt/render_temp
#   AND save a .tar.xz of /opt/blender onto the volume for the next pod (`_paint_pip.py`).
# KEEP: /workspace/pkgs/blender-4.2.4-linux-x64.tar.xz on the volume. Extract to /opt on boot. Do not run from volume.
if ! /opt/blender/blender --version >/dev/null 2>&1; then
  rm -rf /opt/blender /tmp/blender_dl
  mkdir -p /tmp/blender_dl && cd /tmp/blender_dl
  curl -L --fail --retry 5 --retry-delay 2 -o blender.tar.xz \
    https://download.blender.org/release/Blender4.2/blender-4.2.4-linux-x64.tar.xz
  tar -xf blender.tar.xz
  mv blender-4.2.4-linux-x64 /opt/blender
  rm -rf /tmp/blender_dl
fi
chmod +x /opt/blender/blender
/opt/blender/blender --version | head -2
ln -sfn /opt/blender /workspace/MV-Painter/blender-4.2.9-linux-x64
test -x /workspace/MV-Painter/blender-4.2.9-linux-x64/blender
readlink -f /workspace/MV-Painter/blender-4.2.9-linux-x64
# expect: /opt/blender   NOT /workspace/blender
mkdir -p /workspace/pkgs
test -f /workspace/pkgs/blender-4.2.4-linux-x64.tar.xz || \
  tar -C /opt -cJf /workspace/pkgs/blender-4.2.4-linux-x64.tar.xz blender
```

---

## CMD-19 PAINT OPENCV IN BLENDER PYTHON — (`_paint_fix_exr_restart.py`)

```bash
# TRAP: pip install opencv into mvpaint-venv. Blender has ITS OWN python:
#       /opt/blender/4.2/python/bin/python3.11
#       infer's Blender process `import cv2` fails. EXR normals never write. depth/000.exr missing.
# TRAP: None-guard that prints EXR_READ_FAIL then still uses normal_unit16 → UnboundLocalError.
#       Blender quits after view 0. infer_multiview does NOT check Blender RC (official). Dies later.
# FIX: install opencv-python-headless INTO Blender's python. Set OPENCV_IO_ENABLE_OPENEXR=1 in
#      blender_render_ortho.py BEFORE import cv2. Patch the None-guard to not reference unset names.
# FIX: raise on Blender nonzero RC (we patch cmds in infer_multiview). Official does subprocess.run and continues.
BPY=/opt/blender/4.2/python/bin/python3.11
if ! OPENCV_IO_ENABLE_OPENEXR=1 $BPY -c "import cv2"; then
  $BPY -m ensurepip --upgrade || true
  $BPY -m pip install -q opencv-python-headless
fi
OPENCV_IO_ENABLE_OPENEXR=1 $BPY -c "import os; os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'; import cv2; print('CV2_OK', cv2.__version__)"
/opt/blender/blender --background --python-expr "import cv2; print('BLEND_CV2', cv2.__version__)"
# GATE token: BLEND_CV2 must print. --version is not this gate.
python3 - << 'PY'
from pathlib import Path
p = Path("/workspace/MV-Painter/MVPainter/scripts/blender_render_ortho.py")
t = p.read_text()
if "OPENCV_IO_ENABLE_OPENEXR" not in t:
    t = t.replace("import cv2\n", "import os\nos.environ['OPENCV_IO_ENABLE_OPENEXR']='1'\nimport cv2\n", 1)
    print("PATCHED_ENV")
needle = "normal_unit16 = (normal * 65535).astype(np.uint16)"
if "if normal is None" not in t and needle in t:
    t = t.replace(
        needle,
        "if normal is None:\n                print('EXR_READ_FAIL', view_id)\n            else:\n                normal_unit16 = (normal * 65535).astype(np.uint16)",
    )
    print("PATCHED_NONE")
p.write_text(t)
print("ORTHO_CV_OK")
PY
```

---

## CMD-20 PAINT glTF — `debug_value=256` (`_paint_gltf_fix.py` + `_patch_debug.py`)

```bash
# TRAP: blender_render_ortho.py sets bpy.app.debug_value=256.
#       Blender 4.2.4 io_scene_gltf2.set_debug_log() only handles 0..4. 256 returns None.
#       IMPORT_SCENE_OT_gltf.loglevel expected an int, not None.
#       Import writes NOTHING. Blender STILL EXITS 0. infer loads 25GB UNet, then missing depth/000.exr.
#       This billed TWO full 20-30 min VRAM loads and produced ZERO 6-views.
# TRAP: passing loglevel=0 on bpy.ops.import_scene.gltf. Blender OVERWRITES it with set_debug_log().
# FIX A: replace debug_value=256 with debug_value=0 in blender_render_ortho.py
# FIX B: add `return logging.INFO` fallback at end of set_debug_log() in
#        /opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py
# FIX C: still pass loglevel=0 on the import calls
# GATE token: GLTF_OK from a real import of a remesh BEFORE torch.load of the ckpt.
python3 - << 'PY'
from pathlib import Path
p = Path("/workspace/MV-Painter/MVPainter/scripts/blender_render_ortho.py")
t = p.read_text()
n = t.count("bpy.app.debug_value=256")
t = t.replace("bpy.app.debug_value=256", "bpy.app.debug_value=0")
if "loglevel=0" not in t:
    t = t.replace(
        "bpy.ops.import_scene.gltf(filepath=object_path, merge_vertices=True)",
        "bpy.ops.import_scene.gltf(filepath=object_path, merge_vertices=True, loglevel=0)",
    )
p.write_text(t)
print("ORTHO_DEBUG", n)
p = Path("/opt/blender/4.2/scripts/addons_core/io_scene_gltf2/__init__.py")
t = p.read_text()
old = """def set_debug_log():
    import logging
    if bpy.app.debug_value == 0:      # Default values => Display all messages except debug ones
        return logging.INFO
    elif bpy.app.debug_value == 1:
        return logging.WARNING
    elif bpy.app.debug_value == 2:
        return logging.ERROR
    elif bpy.app.debug_value == 3:
        return logging.CRITICAL
    elif bpy.app.debug_value == 4:
        return logging.DEBUG
"""
new = old + "    return logging.INFO\n"
if old in t and old + "    return logging.INFO\n" not in t:
    p.write_text(t.replace(old, new, 1))
    print("SET_DEBUG_PATCH_OK")
else:
    print("SET_DEBUG_CHECK")
PY
/opt/blender/blender --background -Y --python-expr "import bpy; bpy.app.debug_value=0; bpy.ops.import_scene.gltf(filepath='/workspace/mvpaint_in/glbs/gpt2_front_ink.glb', merge_vertices=True, loglevel=0); print('GLTF_OK', len(bpy.data.objects))"
# GATE token: GLTF_OK <n> with n>0. No GLTF_OK = DO NOT start infer. UNet load is 20-30 min you will throw away.
```

---

## CMD-21 PAINT INFER PATCH + FLAGS — (`_paint_fix_exr_restart.py`)

```bash
# TRAP: --no_rembg does NOT stop `import rembg`. Module-level import. pip must have rembg or infer dies
#       before any mesh is seen. Same for numpy==1.26.3 (MV-Painter stack).
# TRAP: silent skip PNG. _paint_upload_ready.py prints "skip png <name>" if the PNG is missing and still
#       uploads the GLB. infer then pairs GLB↔img by stem and skips or paints the wrong still.
# FIX: refuse to upload a name unless BOTH files exist and sizes are real:
#      PNG = generated/bosses/demon/concept/round2_png/<name>.png
#      GLB = generated/bosses/demon/variants/<name>/mesh.glb  > 1_000_000 bytes
# TRAP: leftover demon_from_front.glb/png in mvpaint_in from the morning A6000 run. Pairing pollution.
# FIX: mv those to mvpaint_in/_old/ before infer (_paint_pip2.py).
# TRAP: geo_rotation default. Official path that worked is --geo_rotation -90.
# TRAP: infer on 24GB "CPU-load the 15GB safetensors." Disk filled, VRAM still OOMs. Banned.
# FLAGS (locked):
#   --input_glb_dir /workspace/mvpaint_in/glbs
#   --input_img_dir /workspace/mvpaint_in/imgs
#   --output_dir    /workspace/mvpaint_out
#   --geo_rotation  -90
#   --no_rembg
#   HF_HOME=/opt/hf   HF_HUB_ENABLE_HF_TRANSFER=0   OPENCV_IO_ENABLE_OPENEXR=1   PYTHONUNBUFFERED=1
# ALSO patch infer cmds to /opt/blender + /opt/render_temp + raise on Blender RC (whitespace-sensitive).
python3 - << 'PY'
from pathlib import Path
p = Path("/workspace/MV-Painter/MVPainter/infer_multiview.py")
t = p.read_text()
t = t.replace(
    "blender_path ='../blender-4.2.9-linux-x64/blender'",
    "blender_path ='/opt/blender/blender'",
)
old = """    cmds = [f'{blender_path}', '--background', '-Y',
            '--python',
            'scripts/blender_render_ortho.py', '--',
            '--object_path', f'{obj_path}',
            '--geo_rotation',f'{args.geo_rotation}'
            ]
    print(" ".join(cmds))
    subprocess.run(cmds)"""
new = """    cmds = [f'{blender_path}', '--background', '-Y',
            '--python',
            'scripts/blender_render_ortho.py', '--',
            '--object_path', f'{obj_path}',
            '--geo_rotation',f'{args.geo_rotation}',
            '--output_dir', '/opt/render_temp',
            ]
    print(" ".join(cmds), flush=True)
    r = subprocess.run(cmds)
    print("BLENDER_RC", r.returncode, flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"blender failed rc={r.returncode}")"""
if old not in t:
    raise SystemExit("CMDS_BLOCK_NOT_FOUND")  # whitespace drift — dump the real block, do not guess
t = t.replace(old, new, 1)
t = t.replace('"render_temp"', '"/opt/render_temp"')
t = t.replace("'render_temp'", "'/opt/render_temp'")
p.write_text(t)
print("INFER_PATCH_OK")
PY
# pip gate in the OVERLAY venv — rembg must import even with --no_rembg
/opt/mvpaint-venv/bin/python -c "import rembg,cv2,OpenEXR,diffusers,pytorch_lightning; print('PYDEPS_OK', rembg.__name__)"
```

---

## CMD-22 PAINT UPLOAD PAIRS — no silent skip (`_paint_upload_ready.py` / `_paint_put.py`)

```powershell
# TRAP: _paint_upload_ready.py `print("skip png", name)` and continues. That is the silent skip.
# TRAP: GLB skip if missing or size <= 1_000_000. A 0-byte or tiny upload looks like "uploaded."
# FIX: fail the name if either side is missing. Hex-gzip over -tt (_paint_put.py). Verify WROTE len sha256.
Set-Location C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss
$names = @(
  'gpt2_front_paint','gpt2_front_ink','gpt2_front_sculpt',
  'nano2_concept_art','nano2_2d_illustration','nano2_3d_render'
)
$pngRoot = 'generated\bosses\demon\concept\round2_png'
$glbRoot = 'generated\bosses\demon\variants'
foreach ($n in $names) {
  $png = Join-Path $pngRoot "$n.png"
  $glb = Join-Path $glbRoot "$n\mesh.glb"
  if (-not (Test-Path $png)) { throw "SILENT_SKIP_PNG_BLOCKED $png" }
  if (-not (Test-Path $glb)) { throw "MISSING_GLB $glb" }
  if ((Get-Item $glb).Length -le 1000000) { throw "TINY_GLB $glb" }
  '{0} png={1} glb={2:N1}MB' -f $n, (Get-Item $png).Length, ((Get-Item $glb).Length/1MB)
}
# only then: python _paint_upload_ready.py
# remote after: ls -lh /workspace/mvpaint_in/glbs /workspace/mvpaint_in/imgs
# stems MUST match 1:1. No leftover demon_from_front.*
```

---

## CMD-23 GATE-PAINT-BLENDER — full gate BEFORE UNet load

```bash
# LAW: yesterday died twice because infer started on a half-setup.
#      Full gate every restart. A subset is how debug_value=256 survived the second try.
# RUN THIS ENTIRE BLOCK. If any line fails, do not nohup infer. 20-30 min VRAM load is the bill.
set -e
test -x /opt/blender/blender
/opt/blender/blender --version | head -1
test -x /workspace/MV-Painter/blender-4.2.9-linux-x64/blender
readlink -f /workspace/MV-Painter/blender-4.2.9-linux-x64 | grep -q '^/opt/blender'
/opt/mvpaint-venv/bin/python -c "import rembg,cv2,OpenEXR,diffusers,pytorch_lightning; print('PYDEPS_OK')"
/opt/blender/blender --background --python-expr "import cv2; print('BLEND_CV2', cv2.__version__)"
# expect: BLEND_CV2
python3 -c "from pathlib import Path; t=Path('/workspace/MV-Painter/MVPainter/infer_multiview.py').read_text(); assert '/opt/blender/blender' in t; assert '/opt/render_temp' in t; assert 'debug_value=256' not in Path('/workspace/MV-Painter/MVPainter/scripts/blender_render_ortho.py').read_text(); print('PATCH_OK')"
/opt/blender/blender --background -Y --python-expr "import bpy; bpy.app.debug_value=0; bpy.ops.import_scene.gltf(filepath='/workspace/mvpaint_in/glbs/gpt2_front_ink.glb', merge_vertices=True, loglevel=0); print('GLTF_OK', len(bpy.data.objects))"
# expect: GLTF_OK
test -s /opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d/model_index.json
python3 -c "import json; json.load(open('/opt/hf/hub/models--shaomq--MVPainter/snapshots/85a9cb12b444a73ba922ac44fd198e8de12f8a9d/model_index.json')); print('INDEX_JSON_OK')"
ls /workspace/mvpaint_in/glbs | wc -l
ls /workspace/mvpaint_in/imgs | wc -l
# both counts == 6, stems equal
mkdir -p /opt/render_temp /workspace/mvpaint_out /workspace/logs
echo GATE_PAINT_BLENDER_GREEN
```

---

## CMD-24 PAINT START — infer_multiview only, then shut the 40GB

```bash
# TRAP: starting infer before GATE-PAINT-BLENDER. Official script ignores Blender RC. Looks alive, writes nothing.
# TRAP: also running infer_paint / xatlas / 30k remesh on this box.
# TRAP: "15 min GPU" quote. Measured paint is ~38s. The long bit is the 20-30 min geesefs→VRAM load ONCE.
#       Six meshes after a hot UNet = 6 × (Blender minutes + ~38s). Restart = pay 20-30 min again.
# TRAP: killing the process "to do Blender elsewhere" after UNet is hot. Reload costs more than five Blender passes.
# FIX: leave this process up for all six. Shut the pod when six real *_6view.png exist. Bake locally.
pkill -f infer_multiview.py || true
cat > /tmp/run_infer.sh << 'SH'
#!/bin/bash
set -euxo pipefail
cd /workspace/MV-Painter/MVPainter
export HF_HOME=/opt/hf
export HF_HUB_ENABLE_HF_TRANSFER=0
export PYTHONUNBUFFERED=1
export OPENCV_IO_ENABLE_OPENEXR=1
echo INFER_START $(date -Is)
/opt/mvpaint-venv/bin/python -u infer_multiview.py \
  --input_glb_dir /workspace/mvpaint_in/glbs \
  --input_img_dir /workspace/mvpaint_in/imgs \
  --output_dir /workspace/mvpaint_out \
  --geo_rotation -90 \
  --no_rembg
echo INFER_MULTIVIEW_DONE $(date -Is)
find /workspace/mvpaint_out -name '*_6view.png' -ls
SH
: > /workspace/logs/infer.log
nohup bash /tmp/run_infer.sh > /workspace/logs/infer.log 2>&1 &
echo STARTED_PID=$!
sleep 8
pgrep -af infer_multiview.py || echo NOT_RUNNING
tail -20 /workspace/logs/infer.log
```

---

## CMD-25 PAINT WATCH — 0-byte 6view is a skip, not a win (`_paint_watch.py`)

```bash
# TRAP: _paint_watch.py counts any *6view.png. A 0-byte file (geesefs / failed write) trips HAVE_6VIEW.
# TRAP: camera/ directories exist and look like progress. They are not a 6-view.
# TRAP: tqdm carriage returns. `tail` looks stuck on 1/7 while load is moving. Use nvidia-smi VRAM climb.
# TRAP: first monitor exited on a false alarm. Job was still in Blender ortho.
# FIX: require size > 1_000_000 (or at least > 0 and a real PNG header) AND INFER_MULTIVIEW_DONE / six files.
# FIX: if Traceback and process dead → fail. If process live and no 6view → wait. Load = 20-30 min, VRAM 0→~27GB.
python3 - << 'PY'
from pathlib import Path
hits = list(Path("/workspace/mvpaint_out").rglob("*6view.png"))
for p in hits:
    print(p, p.stat().st_size)
    if p.stat().st_size == 0:
        raise SystemExit("ZERO_BYTE_6VIEW_SKIP")
print("SIXVIEW_REAL", len([p for p in hits if p.stat().st_size > 1_000_000]))
PY
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader
pgrep -af infer_multiview.py || echo PROC_DEAD
# VRAM ~27GB + GPU 0% right after load = about to hit Blender ortho. Do not restart.
# GPU busy a few seconds after Blender = the 38s paint. Then a real 6-view.
# missing depth/000.exr or 001.exr = Blender path/OpenCV/debug_value. Do NOT reload UNet until CMD-23 is green again.
```

---

## CMD-26 LOCAL BAKE — never xatlas / never 30k / never 40GB

```powershell
# TRAP: official MV-Painter bake decimates toward ~30k verts (blender_low). That is the crushed mesh.
# TRAP: xatlas.parametrize on 930k faces on the A6000. 47-60+ min, no progress bar, GPU idle. Hunyuan users
#       hit the same cliff past ~400k faces. 1.3M faces: xatlas frozen, Blender unwrap ~1s.
# TRAP: baking on 40GB "because the UNet was there." UNet is not needed for unwrap/bake.
# FIX: pull the six *_6view.png to this PC. Shut the 40GB pod.
# FIX: remesh GLBs already have UVs from TRELLIS to_glb. REUSE. Skip xatlas.
# FIX: project/bake on the FULL remesh (~45-48MB). Local CPU Blender. Local NVIDIA if you have one.
#      If this PC has no NVIDIA, a SMALL CUDA box — not the 40GB.
# FIX: Hunyuan paint is still banned here. This is MV-Painter 6-views → local bake only.
# 40GB POD IS ALREADY STOPPED. Do not Start it to "finish bake."
Write-Host "LOCAL_BAKE reuse TRELLIS UVs. Full mesh. No xatlas. No 30k. No 40GB."
```

---

## CMD-27 PAINT PIP / EXT — overlay venv, CUDA version lie

```bash
# TRAP: image torch vs extension setup.py CUDA version check. Compile aborts.
# FIX: torch.utils.cpp_extension._check_cuda_version = lambda *a, **k: None
#      then runpy setup.py install in custom_rasterizer and differentiable_renderer (cwd those dirs).
# TRAP: pip on geesefs volume venv. Put venv on /opt/mvpaint-venv (overlay).
# PINS that were used:
#   diffusers==0.20.2 transformers==4.40.1 huggingface_hub==0.25.2
#   pytorch-lightning==2.2.4 OpenEXR==3.2.4 numpy==1.26.3 scipy==1.13.0
#   rembg  (import required — CMD-21)
#   opencv-python in venv AND opencv-python-headless in Blender python — not the same install
export PATH=/usr/local/cuda/bin:$PATH CUDA_HOME=/usr/local/cuda TORCH_CUDA_ARCH_LIST=8.6
python3 -m venv --system-site-packages /opt/mvpaint-venv
/opt/mvpaint-venv/bin/python -m pip install -U pip wheel ninja pybind11
# ... pins from _paint_kick.py ...
/opt/mvpaint-venv/bin/python - << 'PY'
import os, runpy, sys
import torch.utils.cpp_extension as ext
ext._check_cuda_version = lambda *a, **k: None
os.chdir("/workspace/MV-Painter/MVPainter/mvpainter/custom_rasterizer")
sys.argv = ["setup.py", "install"]
runpy.run_path("setup.py", run_name="__main__")
os.chdir("/workspace/MV-Painter/MVPainter/mvpainter/differentiable_renderer")
sys.argv = ["setup.py", "install"]
runpy.run_path("setup.py", run_name="__main__")
print("EXT_OK")
PY
```

---

## CMD-28 PAINT REPO — real folder, not overlay symlink

```bash
# TRAP: /workspace/MV-Painter was a symlink to /opt/MV-Painter. Pod stop deleted the code.
# FIX: curl tarball onto the volume as a real directory.
if [ ! -f /workspace/MV-Painter/MVPainter/infer_multiview.py ]; then
  rm -f /workspace/MV-Painter
  rm -rf /tmp/MV-Painter-main
  curl -L --fail --retry 5 --retry-delay 2 -o /tmp/mvp.tgz \
    https://codeload.github.com/amap-cvlab/MV-Painter/tar.gz/refs/heads/main
  tar -xzf /tmp/mvp.tgz -C /tmp
  mv /tmp/MV-Painter-main /workspace/MV-Painter
  rm -f /tmp/mvp.tgz
fi
test -f /workspace/MV-Painter/MVPainter/infer_multiview.py && echo HAS_INFER
# HDRI used by ortho: /workspace/MV-Painter/MVPainter/scripts/overcast_soil_puresky_4k.exr must exist and be non-zero
ls -lh /workspace/MV-Painter/MVPainter/scripts/overcast_soil_puresky_4k.exr
```

---

## CMD-29 FIRST-TRY ORDER — do not invent a new sequence

```powershell
# ORDER LOCKED. Skipping or swapping is how Eigen / rembg / debug_value got re-solved for hours.
# MESH (only if a remesh is actually missing — tonight they are NOT):
#   CMD-01 worktree+ppp
#   CMD-03 ssh -tt 24GB devel
#   CMD-05 GATE tokens (TRELLIS.2-4B + DINOv3 accepted, RMBG skipped)
#   CMD-06 upload stills+scripts, strip CRLF
#   CMD-07 zip clone
#   CMD-08/09 setup + Eigen + flash-attn wheel, NO xformers
#   CMD-10 rembg None + RGBA JPEG + DINOv3 layer_root
#   CMD-11 one generate --skip-texture
#   CMD-13 pull as it lands
#   CMD-12 queue the rest
# PAINT (this is the next rental):
#   CMD-02 confirm six local 45-48MB meshes
#   CMD-04 new 40GB + SAME volume, same datacenter, 50GB+
#   CMD-16/17 geesefs pointers, no 25.3GB re-fetch, no 15GB safetensors
#   CMD-18 4.2.4 → /opt/blender, symlink as 4.2.9
#   CMD-19 OpenCV in Blender python
#   CMD-20 debug_value=256 → 0 + set_debug_log fallback
#   CMD-21 rembg import + infer path/RC patches
#   CMD-22 pairs, no silent skip PNG
#   CMD-23 FULL gate (BLEND_CV2 + GLTF_OK + INDEX_JSON_OK) BEFORE infer
#   CMD-24 infer_multiview only
#   CMD-25 real 6-views (size>0)
#   stop 40GB
#   CMD-26 local bake, reuse UVs, no xatlas, no 30k
Write-Host "ORDER_OK next money is paint-only after CMD-23."
```

---

## CMD-30 CHECKPOINT / DO NOT REPEAT 2026-09-18

```powershell
# FACTS from the transcript + helpers, as of Saturday 2026-09-19:
# - Hunyuan mesh+paint banned (LEGAL_LIABILITY.md + session law).
# - Six TRELLIS.2 remeshes already local ~45-48MB:
#     generated/bosses/demon/variants/<stem>/mesh.glb
#     stems: gpt2_front_paint gpt2_front_ink gpt2_front_sculpt
#            nano2_concept_art nano2_2d_illustration nano2_3d_render
# - Path that produced them: 1024_cascade → isolated CuMesh remesh band=1 project=0
#   simplify ~1M → to_glb remesh=False --skip-texture, PNG not WebP.
# - 24GB A5000 is the remesh class. Do not remesh on 40GB.
# - 40GB paint pod ALREADY STOPPED. Volume still holds ~36GB MV-Painter weights.
# - Two 40GB deaths: (1) volume Blender / missing OpenCV in Blender python
#                    (2) debug_value=256 → loglevel=None, Blender exit 0, no EXR
#   Each death rebilled a 20-30 min UNet load. GPU never painted. 38s paint never happened that night.
# - Do not commit ppp. Do not switch dirty dev_tmxlevels. SSH is ppp + -tt.
# - Next action is NOT remesh. Next action is a NEW 40GB deploy + CMD-23 then CMD-24.
Write-Host "CHECKPOINT meshes local, 40GB stopped, paint-only next, full blender gate first."
```

---

## CMD-31 ISSUE INDEX (comment-only, grep this)

```text
# Hunyuan mesh+paint          → CMD-00 banned EU/UK/SK
# 24 / 40 / local split       → CMD-02
# xatlas / 30k on 40GB        → CMD-02 CMD-26
# geesefs chmod/symlink/0-byte→ CMD-16 CMD-17
# debug_value=256             → CMD-20
# OpenCV in Blender Python    → CMD-19
# GATE tokens                 → CMD-05 CMD-23
# 25.3GB ckpt not 15GB        → CMD-15
# 38s paint                   → CMD-02 CMD-24
# 20-30min VRAM load          → CMD-02 CMD-24 CMD-25
# silent skip PNG             → CMD-22
# 0-byte 6view skip           → CMD-25
# rembg import / None.to      → CMD-10 CMD-21
# blender 4.2.4 vs 4.2.9      → CMD-18
# meshes local ~45-48MB       → CMD-02 CMD-30
# 40GB pod already stopped    → CMD-04 CMD-30
# SSH key ppp -tt             → CMD-01 CMD-03 CMD-04
# do not commit ppp           → CMD-01
# do not switch dirty tmx     → CMD-01
# xformers second torch       → CMD-08
# Eigen / CPATH               → CMD-08 CMD-09
# DINOv3 Transformers 5       → CMD-10
# DINOv3 pending review       → CMD-05
# flash_attn wheel            → CMD-08
# CRLF on .sh                 → CMD-06
# git clone hang → zip        → CMD-07
# WebP Viewer reject          → CMD-11
# CuMesh CUDA 700 same-proc   → CMD-11
# hf_transfer / ENOSPC        → CMD-05 CMD-15
# volume+GPU datacenter       → CMD-15
# two pods one volume         → CMD-04
# Blender exit 0 no EXR       → CMD-20 CMD-21
# camera/ false progress      → CMD-25
# leftover demon_from_front   → CMD-21
# extra 15GB safetensors      → CMD-17
```
