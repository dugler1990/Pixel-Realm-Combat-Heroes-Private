# boss_sprite_pipeline — PLAN

Concept image → 3D mesh → rig + actions → 8/16-direction pre-rendered sprite
frames → `Graphics/Monsters/<name>/…` → in-game 8-direction boss.

The Diablo II production pipeline, scripted. Same shape as
`tools/painted_map_pipeline`: one CLI per stage, JSON config per boss, files on
disk between stages, contact sheets as the review surface, every stage re-runnable
from its inputs.

## Constraints this plan is built around

| Fact | Consequence |
|---|---|
| GPU box already runs a local SAM3 inference server, reached via an `api_url` knob (`collision/sam3/sam3.config.example.json`) | Same pattern here: **all ML stages run on the GPU box, free, open-weights** — Hunyuan3D-2 (mesh), UniRig (rig). Hosted APIs (Tripo/Meshy/fal) exist as optional backends only; nothing in the default path costs money. |
| This laptop: Python 3.10, no NVIDIA GPU, no Blender installed | Blender via `bpy` wheel, which pins **Python 3.11** → stage 4 runs in its own `.venv-bpy` (3.11) as a subprocess. Main project venv untouched. Stages are location-agnostic (files in, files out), so the whole pipeline can also just run on the GPU box. |
| Existing loader: `Enemy.import_graphics_left_right` reads `Graphics/Monsters/<name>/{idle,move,attack}/*.png`, right-facing only, left = flip | New loader `import_graphics_8dir` triggered by a `manifest.json` in the monster folder. Existing monsters unchanged. |
| `EnemyPuppet.apply_snapshot` already relays `direction_string` | 8-dir only needs the collapse-to-left/right on `EnemyPuppet.py:83` lifted. |
| Rendering must run headless (no display) | Cycles CPU by default (no GL context needed). Eevee under `xvfb-run` is a speed knob, not a requirement. |
| Painted maps are ~oblique top-down; existing monster frames are 64px, a boss will be ~192–256px | Camera elevation and ortho scale are config knobs; Gate B decides them by compositing onto the actual level PNG. |

## Stages

```
tools/boss_sprite_pipeline/
  PLAN.md                 # this file
  README.md               # quick start once Phase 0 lands
  pipeline.py             # orchestrator: run_pipeline(config) with --from/--to stage
  config.example.json
  bosses/<name>.json      # per-boss config (mirrors painted_map_pipeline/levels)
  concept.py              # stage 0
  mesh.py                 # stage 1
  rig.py                  # stage 2
  animate.py              # stage 3
  render_frames.py        # stage 4 (runs under .venv-bpy)
  pack_frames.py          # stage 5
  backends/
    base.py               # MeshBackend / RigBackend interfaces + registry
    gpu_exec.py           # run a CLI locally or on `gpu_host` over ssh (rsync in → run → rsync out)
    hunyuan3d.py          # mesh, open weights, GPU box          (default)
    trellis.py            # mesh, open weights, GPU box          (bakeoff alternative)
    unirig.py             # rig,  open weights, GPU box          (default)
    none.py               # rig=none → static turntable, motion procedural only
    tripo.py  meshy.py    # hosted, paid — optional, not on the default path
  gpu_box/
    setup.sh              # one-off: clone + venv Hunyuan3D-2 and UniRig on the GPU box
    hunyuan_cli.py        # thin wrappers so the pipeline calls one stable CLI per tool
    unirig_cli.py
```

Working dir per boss: `generated/bosses/<name>/{concept,mesh,rig,anim,frames,pack}/`
plus `state.json` (stage timestamps, backend used, gate verdicts).

### Where things run
Every stage is a CLI reading and writing files, so it doesn't matter which
machine invokes it. Two supported setups, one config key:
- `gpu_host: null` — run the pipeline **on the GPU box**; ML backends shell out
  to `gpu_box/*_cli.py` directly. Simplest; recommended to start.
- `gpu_host: "user@host"` — run from this laptop; `gpu_exec.py` rsyncs the
  stage input to the box, runs the same CLI over ssh, rsyncs the output back.
  Same code path, one indirection.
Outputs (`generated/bosses/`) move between laptops the way the SAM3 work does
already (git / rsync); the GLBs are a few MB each.

### Stage 0 — `concept`
In: 1 concept image (e.g. the demon on the pyramid level).
Do: cut out the subject. Default: the existing SAM3 server on the GPU box with a
text prompt (`"demon"`) — same client as `collision/sam3/roboflow_workflow.py`,
just a different prompt and a mask→RGBA cutout instead of polygons. Fallback:
rembg (CPU, free).
Optional, **paid**: a 3-view turnaround (front/side/back, neutral pose, flat
lighting) with gpt-image-2 via `painted_map_pipeline/openai_api.py`. Single
dramatic concept shots bake their shadows into the mesh texture; a turnaround
fixes that. Off by default — only reach for it if Gate A shows a bad back side.
Out: `concept/front.png [side.png back.png]`, `concept/prompt.txt`.

### Stage 1 — `mesh`
In: concept images. Out: `mesh/raw.glb` + `mesh/turntable.png` (8 static
views, rendered by stage 4's renderer with no actions — doubles as **Gate A**).

| Backend | Runs on | Cost | VRAM (approx) | Notes |
|---|---|---|---|---|
| `hunyuan3d` (Hunyuan3D-2, Tencent) | GPU box | free | shape ~6 GB; + texture paint ~10–12 GB; `2mini` variant fits smaller cards | **Default.** Single- or multi-view input (`2mv` variant). Ships a Gradio/API server too, but we call the CLI. |
| `trellis` (Microsoft) | GPU box | free | ~8–16 GB | Bakeoff alternative; different failure modes on thin parts (wings). |
| `tripo` / `meshy` | hosted | paid credits | – | Optional. Only if both open models fail Gate A. |

Which model produces the best *winged biped* is a bakeoff, not a guess: same
concept image through both open backends, one turntable contact sheet, pick.
Backend is one config line, as in `map_pipeline_v2/backends`. Which Hunyuan
variant to install depends on the GPU box's VRAM — see open decisions.

### Stage 2 — `rig`
In: `mesh/raw.glb`. Out: `rig/rigged.glb` (+ `rig/bones.json`: detected bone
names, which ones we classified as wing/spine/head).
Backends: `unirig` (default — open weights, GPU box, arbitrary meshes incl.
winged creatures; emits skeleton + skin weights as FBX/GLB), `none`, and the
paid `tripo`/`meshy` rig endpoints as optional extras. With `none` the boss is a
static turntable and all motion comes from stage 3's procedural layer — this is
the guaranteed fallback if auto-rig mangles the wings.

### Stage 3 — `animate`
In: `rig/rigged.glb`. Out: `anim/boss.blend` with actions named exactly
`idle, move, attack, hurt, death` (+ any `special_*`).
Three sources, composable, all free:
1. **Procedural in bpy** on the UniRig bones — **default**. Per action, a small
   recipe of sines and eased keyframes: idle = hover bob + breathing (spine
   scale) + slow flap; move = faster flap + forward tilt + bob; attack = root
   lunge + arm-bone swing with anticipation; hurt = recoil; death = fall + sink.
   Scriptable, no external data, and it is real geometry moving — this is not the
   "flat image skewing" that looks like cardboard. Bone roles (wing/spine/arm/
   root) are classified from `rig/bones.json` by position; recipes are keyed by
   role so a second winged boss reuses them unchanged. If the rig has no wing
   bones, fallback: select wing verts by bbox region (|x| beyond 35% of width),
   add a hinge bone, proximity-weighted — good enough for a flap.
2. **Mixamo clip retarget** via bone-name map in bpy. Free with an Adobe login
   but no API: one manual download of a clip folder, then scripted forever.
   Upgrade path when procedural bodies look too mechanical; UniRig's skeleton
   needs a per-body-plan bone map JSON, written once.
3. **Vendor presets** (Tripo/Meshy, paid): optional, only if 1 + 2 aren't
   enough for a particular boss.

### Stage 4 — `render_frames` (bpy, `.venv-bpy`)
In: `anim/boss.blend` (or `rig/rigged.glb` for `none`). Out:
`frames/<action>/<dir>/<NNNN>.png` (RGBA, transparent) + `frames/manifest.json`.
- Normalise: fit mesh to `target_height_units`, origin at foot centre.
- Camera: orthographic, `elevation_deg` (knob, default 45), `ortho_scale` fixed
  across **all** actions and directions so pixel scale is identical everywhere;
  `directions` = 8 (knob: 16). Direction keys: `e ne n nw w sw s se`.
- Lighting: one key + fill + optional ground-shadow catcher (shadow-only plane)
  so the sprite carries its own contact shadow like the concept image.
- Shading knob: `raw` | `toon` (Freestyle outline + colour-ramp shader). Gate B
  bakeoff decides which sits better on the painted map.
- Engine: Cycles CPU, low samples + denoise; `eevee` knob under `xvfb-run`.
- Frame sampling: `fps_out` per action (e.g. idle 8, move 12, attack 15).
- Manifest: pixel-per-unit, anchor (foot pixel), frame counts, fps, source
  hashes — everything the engine and the packer need without re-deriving.

### Stage 5 — `pack_frames`
In: `frames/`. Out: `Graphics/Monsters/<name>/<action>/<dir>/Sprite-NNNN.png`
(trimmed to one common bbox per action so anchors stay put), `manifest.json`
copied alongside, `pack/contact_sheet.png` for review. Atlas sheets can come
later; the GPU backend already atlases at load.

### Stage 6 — engine (small, in `Code/`)
- `Enemy.import_graphics_8dir(name)`: reads manifest, loads `<action>/<dir>/`.
  Chosen automatically when `manifest.json` exists; else current loader.
- `Enemy.get_direction_as_string()`: 8-way from `self.direction` angle with
  hysteresis (~10°) so the sprite doesn't flicker on sector boundaries.
- `EnemyPuppet.apply_snapshot`: stop collapsing `direction_string` to ±1 on x
  when the monster is 8-dir; feed it straight through.
- `scale_animations` works as-is (dict-of-dict aware already).
- Motion polish *on top of* real frames (hover offset, shadow scale, hit-flash)
  is a separate later ticket — not in this plan.

## Gates (review by contact sheet, decide with data)

- **Gate A** (after stage 1): 8-view turntable. Does the mesh read as the
  concept? Back side hallucinated badly → add turnaround at stage 0, rerun.
- **Gate B** (after stage 4, one action, one direction): frame composited onto
  the actual level PNG at game scale, `raw` vs `toon` side by side, at 2–3
  elevations. This is the "does 3D-on-painted look right" decision. If neither
  sits right, last resort is per-frame img2img repaint (consistency risk; test on
  4 frames before committing).
- **Gate C** (after stage 6): boss walking a circle on the level in-game, all
  8 directions, one attack. Screenshot strip.

## Phases (order of work)

- **Phase 0 — spine, no API keys. DONE (2026-09-12).** `.venv-bpy` (3.11 +
  bpy 4.5 LTS), `render_frames.py` + `pack_frames.py` on Khronos `Fox.glb`,
  `CombatUnit.import_graphics_8dir` + compass facing + manifest anchor,
  `tests/test_boss_sprite_8dir.py` green, engine-drawn strip in
  `logs/boss_sprite_8dir_strip.png`. Both `raw` and `toon` shading render.
  Found on the way: bpy `matrix_world` is stale until `view_layer.update()`;
  Cycles' denoised shadow-catcher leaves a ≤8/255 alpha veil (packer floors it);
  ShaderToRGB is EEVEE-only (toon uses the Cycles Toon BSDF); the factory
  scene's default Freestyle LineSet has no linestyle and crashes the render.
- **Phase 1 — GPU box + mesh.** `gpu_box/setup.sh` installs Hunyuan3D-2 (+
  TRELLIS) and UniRig next to the SAM3 server. Stage 0 (SAM3 cutout) + stage 1
  on the demon image through both open backends. Gate A.
- **Phase 2 — rig + procedural actions.** UniRig, bone-role classification,
  the procedural action recipes. Gate B with raw/toon. `none`-rig fallback path
  verified on the same boss.
- **Phase 3 — motion upgrade (only if needed).** Mixamo retarget for body
  actions that look mechanical.
- **Phase 4 — second boss** from a fresh concept image with no code changes.
  That's the "pipeline, not a one-off" test.

## Risks and the mitigation already in the plan

| Risk | Mitigation |
|---|---|
| Single-image mesh has a hallucinated back / baked lighting | Bakeoff Hunyuan vs TRELLIS at Gate A; paid turnaround at stage 0 only if that fails |
| GPU box VRAM too small for Hunyuan3D-2 full (shape + texture) | `2mini` variant; or shape-only + texture via Blender projection of the concept image (`bpy`, free) |
| Auto-rig mangles wings | `rig=none` + procedural flap on vertex regions; still a moving 8-dir boss |
| Procedural body actions look mechanical | Mixamo retarget (free, one manual download) in Phase 3 |
| Rendered 3D looks pasted onto the painted map | `toon` shading knob + Gate B composite bakeoff before any boss is finalised |
| bpy wheel pins Python 3.11; project is 3.10 | Separate `.venv-bpy`, stage 4 is a subprocess. Fallback: Blender binary tarball `blender -b -P` |
| CPU render time (8 dirs × 5 actions × ~12 frames ≈ 500 frames) | 256px + low samples + denoise is seconds/frame; Eevee under xvfb if it matters |
| Open-model install churn on the GPU box (CUDA/torch pins differ per repo) | One venv per tool under `gpu_box/`, pinned in `setup.sh`; the pipeline only ever calls the thin `*_cli.py` wrappers |

## What costs money
Nothing on the default path. Hunyuan3D-2, TRELLIS, UniRig, Blender/bpy, SAM3
(already running), Mixamo clips (Adobe login, no charge) are all free. The only
paid knobs are opt-in: gpt-image-2 turnaround at stage 0, Tripo/Meshy backends.

## Open decisions (need your call)

1. GPU box specs — GPU model / VRAM, and whether this laptop can ssh to it.
   Decides the Hunyuan variant (`2` vs `2mini`) and `gpu_host` vs running the
   pipeline on the box. Recommendation: run it on the box to start.
2. Directions: 8 (D2 monsters) or 16 (D2 players). Recommendation: 8, knob for 16.
3. Boss render size: 192 or 256 px tall at 1× game scale. Gate B decides.
