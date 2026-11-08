# boss_sprite_pipeline

Concept image → 3D mesh → rig → animated → **8-direction pre-rendered sprite
frames** → `Graphics/Monsters/<name>/` → an in-game monster that faces every way
it walks. Design and rationale: [PLAN.md](PLAN.md).

## One-off setup (this laptop, no GPU needed)

```bash
# Blender as a Python module needs Python 3.11; the project venv is 3.10, so it
# gets its own venv. uv fetches 3.11 for you.
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11 tools/boss_sprite_pipeline/.venv-bpy
uv pip install --python tools/boss_sprite_pipeline/.venv-bpy/bin/python "bpy==4.5.13" pillow numpy
```

GPU box (open-weight ML stages): `bash tools/boss_sprite_pipeline/gpu_box/setup.sh`
— see the header of that script; it has not been run on the box yet.

For this EU-based commercial project, mesh generation uses Stable Fast 3D:
`bash tools/boss_sprite_pipeline/gpu_box/setup.sh stable_fast_3d`. It requires
accepting the gated model terms on Hugging Face. See
[`gpu_box/RUNPOD.md`](gpu_box/RUNPOD.md) and the repository's
[`LEGAL_LIABILITY.md`](../../LEGAL_LIABILITY.md).

## Run

```bash
# from the repo root, project python
python -m tools.boss_sprite_pipeline.pipeline tools/boss_sprite_pipeline/bosses/<boss>.json
python -m tools.boss_sprite_pipeline.pipeline ... --from render --to pack    # re-run part of it
python -m tools.boss_sprite_pipeline.pipeline ... --gpu-host user@gpubox     # ML stages over ssh
```

Stages: `concept → mesh → rig → animate → render → pack`. Each writes to
`generated/bosses/<name>/<stage>/` and `state.json`; `pack` installs into
`Graphics/Monsters/<name>/<action>/<dir>/Sprite-NNNN.png` + `manifest.json`.
The manifest is what flips the engine into N-direction mode for that monster
(`Support.load_sprite_manifest`, `CombatUnit.import_graphics_8dir`).

### Smoke test with no ML at all

`bosses/_test_fox.json` renders the Khronos sample `Fox.glb` (CC0, already
animated) through render → pack. Put the model at
`generated/bosses/_test_fox/anim/Fox.glb`, then:

```bash
python -m tools.boss_sprite_pipeline.pipeline tools/boss_sprite_pipeline/bosses/_test_fox.json --from animate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_boss_sprite_8dir.py -q
```

~336 frames, ~10 min on an 8-core CPU. The test writes
`logs/boss_sprite_8dir_strip.png` — the boss facing all 8 ways, idle and walking,
drawn by the real engine code path.

## Boss config knobs (see `config.example.json`)

| Key | Meaning |
|---|---|
| `source` | animated model relative to the workdir (`.glb/.gltf/.fbx/.blend`) |
| `forward_axis` | which way the model's face points after import (`-Y` for glTF) |
| `directions` | 8 or 16 |
| `actions.<name>.source` | clip name in the file (default = action name) |
| `actions.<name>.fps_out` | frames per second to sample **and** the in-game playback rate |
| `actions.<name>.static` | render one pose (unrigged mesh / turntable) |
| `camera.elevation_deg`, `camera.margin` | view angle; margin around the union of all poses + shadow |
| `light.*` | key sun, fixed to the screen (top-left by default), and ambient |
| `render.resolution` | square frame size before trim |
| `render.shading` | `raw` or `toon` (stepped colour ramp + Freestyle outline) |
| `render.ground_shadow` | Cycles shadow catcher → contact shadow baked into alpha |
| `render.samples`, `render.denoise`, `render.device` | Cycles cost/quality; `GPU` on the box |
| `pack.alpha_floor` | alpha below this is cleared (denoiser veil); default 10 |
| `stages.concept/mesh/rig.backend` | `sam3`/`rembg`/`none`; `stable_fast_3d`/`hunyuan3d`/`trellis`/`none`; `unirig`/`none` |
| `stages.animate.mode` | `passthrough` (clips already in the file) or `procedural` (Phase 2) |

## Gates

- **A** `generated/bosses/<name>/mesh/turntable.png` — does the mesh read as the concept?
- **B** `review.composite_on_level(...)` — one frame on the painted level at game scale.
- **C** `logs/boss_sprite_8dir_strip.png` — engine-drawn, every direction.

### Generated views: `view_gate.py`

Draws a view and checks it from the images alone before it goes to TRELLIS. Front and back are gpt-image edits
(`openai.gpt-image-2.json`, `OPENAI_API_KEY`).
`front`: the bare concept dressed in armour, no mask; it must cover his bare outline (sent as image 2), lined up
afterwards; `[rb]` draws again asking for bigger armour. Option `--masked`: his grown outline is the mask, as for
the back -- covers him by construction, but cuts the armour to the mask.
`back`: drawn as the interiors are: the front's mirrored outline as a black placeholder and as the mask, the
approved front as image 2, the raw return scored against the mask (IoU, body bands), then pasted back inside it,
so the silhouette is the mask's.
`side`: a Leonardo draw (`view_gate.json`, `LEONARDO_API_KEY`); only its size and place are checked (depth has
nothing to compare with in the images). `[r1]` draws again with the miss marked
(`tools/painted_map_pipeline/shape_gate.py`, the same overlay and retry as the level and interiors gates).
Accept writes the view cut out for TRELLIS and `gate_<view>.json`.

    python -m tools.boss_sprite_pipeline.view_gate front --input <bare.jpg> --out <dir> [--masked [--margin 0.005]]
    python -m tools.boss_sprite_pipeline.view_gate back  --front <front.jpg> --out <dir>
    python -m tools.boss_sprite_pipeline.view_gate side  --front <front.png> --back <back.png> --out <dir>

## Status

- [x] Phase 0 — bpy render + pack + engine 8-dir loader/anchor/facing, verified on Fox.glb
- [ ] Phase 1 — GPU box setup, SAM3 cutout, Hunyuan3D-2 / TRELLIS mesh, Gate A
- [ ] Phase 2 — UniRig + procedural actions (`animate.py` mode `procedural`), Gate B
- [ ] Phase 3 — Mixamo retarget (only if procedural bodies look mechanical)
- [ ] Phase 4 — second boss with no code changes
