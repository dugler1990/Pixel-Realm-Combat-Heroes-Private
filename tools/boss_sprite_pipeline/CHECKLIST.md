# Boss 3D — one-screen checklist

The full reasoning, every bug, and every fix are in [`PROCESS.md`](PROCESS.md).
This card is the linear "do this, in this order, stop where it says stop."
**Do not start a step until the previous step's gate printed `..._OK`.**

Verified against the repo and MV-Painter/TRELLIS.2 upstream on **2026-09-20**.

---

## Where things stand right now

- **Mesh: DONE.** Six painted-ready meshes are already on this PC. Do **not** rent a mesh pod, do **not** re-run TRELLIS for these six. (Gate `L0`.)
- **Paint: NOT done for these six.** The paint step (`*_6view.png` → baked GLB) has produced **zero** 6-views for round 2. It *did* work once before, so the method is proven; the failures were repeated setup traps, all listed in `PROCESS.md §8`.
- **No pod is running** unless you just started one. Nothing here starts a pod.

---

## The one rule that caused the wasted week

> **Never load the 25 GB paint model (`v29_25000.ckpt`) until the Blender gate `GATE_B9_OK` has printed.**

Loading that file takes 20–30 min. Twice the day was spent loading it *into a broken Blender* and getting nothing. Blender **exits 0 even after it crashed**, so "blender ran" is never proof. Proof is: the six files `depth/000.exr … 005.exr` exist and are non-zero.

**Working or hung? Use CPU-time delta, never log silence.** `awk '{print $14}' /proc/<pid>/stat` twice, 20 s apart — if it grew ~2000, it is working. A Blender ortho takes ~2 min; `%CPU == 0` **and** flat RSS **and** no `depth/000.exr` after 60 s = dead gate, kill it.

**⚠️ `bake_pipeline` prints NOTHING until it writes the GLB** — 25 min of silence is normal. A 15-min stop threshold would have killed six healthy bakes on the validated run. Check CPU delta before killing anything.

---

## Paint run — do these in order (see PROCESS.md §4 for the exact commands)

```
[ ] P0  Rent 40 GB+ GPU. Disk: volume+30GB container OR 80GB container (both work). → GATE_GPU_OK
        MUST enable Public IP + TCP 22 -> direct ssh -> scp works (293MB in ~2min).
[ ] P1  Download weights: hf download shaomq/MVPainter  (skip the 15 GB extra).   → GATE_HF_OK
[ ] P2  Clone MV-Painter to /opt, venv, Blender 4.2.4, symlink the blender path.  → prints INSTALL_OK
        (paint does NOT need the CUDA rasterizers — those are bake-only, §5.)
[ ] P3  Apply the 5 Blender patches (debug_value, loglevel x2, addon, EXR).       → GATE_PATCH_OK
[ ] P4  Upload 6 glb + 6 png (same stem); delete any leftover *_6view.png.        → GATE_PAIR_OK
[ ] P5  Blender gate on ONE mesh: cv2 ok, gltf ok, depth 000..005.exr non-zero.   → GATE_B9_OK   ← the wall
[ ] P6  ONLY NOW start infer_multiview  (--geo_rotation -90 --no_rembg).          → watch for *_6view.png files
[ ] P7  First *_6view.png → tell user bake can start; pull all folders; shut pod.
```

The volume is fine **as long as** venv / Blender / MVPainter / `render_temp` live on the **container**.
That — not the volume itself — was the original bug. ✅ This sequence was validated end-to-end 2026-09-20:
~12 min for all six paints, ~2 h total for the whole job on one pod.

## Bake (see PROCESS.md §5)

```
[ ] K0  Pull the six 6-view folders FIRST. They are the only artifact needing a 40GB GPU.
        Once local, the pod is disposable and bake runs anywhere with CUDA.
[ ] K1  Compile the 2 CUDA rasterizers (custom_rasterizer, differentiable_renderer) → RAST_OK.
        import torch FIRST or you get a misleading "ImportError: libc10.so".
[ ] K2  pip install cupy-cuda12x   AND   numpy>=2.0,<2.6 + scipy>=1.14.
        The numpy==1.26.3 pin is PAINT-ONLY — do not "restore" it for bake.
[ ] K3  Patch: bake blender.obj (full mesh, NOT blender_low.obj/30k).
[ ] K4  Patch: mesh_uv_wrap reuses existing UVs -> confirm "UV_REUSE" at runtime (kills the 1h10 xatlas).
[ ] K5  Run the six stems IN PARALLEL, one process each (~1.3GB VRAM each). ~30 min total vs ~6x.
[ ] K6  Expect TOTAL SILENCE until each GLB appears. Do not kill it.
```

## Do NOT

- Re-run TRELLIS / rent a mesh pod for the six meshes (they exist).
- Use Hunyuan3D or Hunyuan-Paint (licence bans EU/UK — see PROCESS.md §2).
- Start `infer_multiview` before `GATE_B9_OK`.
- `pip install xformers` on the mesh pod (pulls a second torch, fills the disk).
- Run `infer_paint` / `bake_pipeline` / xatlas on the 40 GB pod.
- Trust `blender --version`, `tail -5`, a grep of a shell script, or a Python `replace` that
  printed `NOT_FOUND`. Verify with the gate command, not with a proxy.
