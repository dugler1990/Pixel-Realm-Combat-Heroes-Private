# Boss 3D generation

Two docs, in order:

1. **[`CHECKLIST.md`](CHECKLIST.md)** — the one-screen "do this, in this order, stop where it says stop."
2. **[`PROCESS.md`](PROCESS.md)** — the full runbook: every command, every known bug, every fix.

Do **not** use this file as the procedure. It exists so old links still resolve. If anything here
disagrees with `PROCESS.md`, **`PROCESS.md` wins.**

## The 30-second version

- **Mesh (TRELLIS.2 + CuMesh remesh):** 24 GB-class pod, `--skip-texture`. **Already done for the current six.**
- **Paint (MV-Painter `infer_multiview` → `*_6view.png`):** 40 GB+ pod. Disk either way (volume + 30 GB
  container, or 80 GB container) — but venv/Blender/`render_temp` must be on the **container**. Enable
  **Public IP + TCP 22** so `scp` works. Never load the 25 GB UNet before `GATE_B9_OK`.
- **Bake (UV + back-project):** skip xatlas (the meshes carry UVs), bake the **full** mesh, install `cupy`,
  and run the stems **in parallel**. Expect total silence until each GLB appears.

✅ **Validated end-to-end 2026-09-20:** six textured GLBs, one pod, ~2 h. See `PROCESS.md` §10.

Legal: **no Hunyuan3D and no Hunyuan-Paint** (licence excludes the EU/UK, including the outputs). Mesh = TRELLIS.2, paint = MV-Painter.

This round: `concept/round2/*.jpg` → `variants/<stem>/mesh.glb` (six on disk) → `*_6view.png` → baked `<stem>.glb`.
