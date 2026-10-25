---
name: GPU fluid meteor smoke
overview: "Replace sprite-plume smoke with a camera-local Stable Fluids GPU sim (Pavel/WebGL-quality soft density), composited in two soft passes for 2.5D rise/occlusion—not stacked opaque slabs."
todos:
  - id: retire-sprite-smoke
    content: "Disable meteor SmokeSystem emit/draw; keep file until fluid ships"
    status: pending
  - id: fluid-core
    content: "Add GPU fluid module + render_backend FBOs/shaders (splat, advect, curl, pressure, dye)"
    status: pending
  - id: composite-25d
    content: "Soft ground + up-screen rise composite; draw before roofs/canopies"
    status: pending
  - id: wire-level
    content: "Level step with weather wind; MeteorStrike splat on impact; CPU no-op"
    status: pending
  - id: tune-verify
    content: "Tune dissipation/curl/buoyancy vs desert+demon; verify shower cost"
    status: pending
isProject: false
---

# GPU fluid meteor smoke (detailed)

## Goal / bar

Soft, continuous, curling smoke like:

- https://paveldogreat.github.io/WebGL-Fluid-Simulation/
- https://www.runcell.dev/tool/smoke-simulation

**Not:** rotating plume sprites, solid cutouts, or two opaque color blocks.

Fire/residual VFX can stay as sprites. Smoke becomes a **density field**.

## Locked design

### Simulation (GPU, camera-local)

| Field | Resolution (v1) | Notes |
|--------|-----------------|--------|
| Velocity | 128×128 | RG float (vx, vy) |
| Dye / density | 256×256 | R (or RGB grey) float/half |
| Pressure / divergence / curl | match velocity | ping-pong temps |

**Coordinate space:** sim covers the **current camera view** (same footprint as the framebuffer world region). World splat = map impact → UV using `visible_sprites.offset` + screen size. When the camera moves, either (a) clear/decay aggressively so trails don’t stick wrong, or (b) v1 simply **dissipate fast enough** that camera motion smear is acceptable. Prefer (b) for first ship; optional scroll-advect later.

**Per-frame solver** (Stable Fluids / GPU Gems style, same family as Pavel):

1. Apply forces: weather wind (uniform bias) + buoyancy (up-screen = −Y in pygame) where density is high  
2. Vorticity confinement (curl) for billow  
3. Divergence → Jacobi pressure → project velocity  
4. Advect velocity; advect dye  
5. Dye dissipation  

**Sources:**

- Meteor **impact** (and light drip during residual): Gaussian splat of density + small upward velocity at impact UV  
- `Weather.calculate_wind_force()` once/frame → add to velocity field (scaled)

### Presentation (2.5D — soft, not slabs)

One density texture, **two soft composites** of the *same* field:

1. **Ground haze** — fullscreen/world quad over the view, sample dye at ground UV, soft alpha (`smoothstep`), grey tint, `SRC_ALPHA` blend. Sits with floor effects / early in post-sprite stack.  
2. **Rise pass** — same dye; fragment shader offsets sample **up-screen** proportional to density (or a short vertical blur/stretch) and fades alpha with height. Reads as rising smoke without a second opaque layer.

Draw order in [`YsortCameraGroup.custom_draw`](Code/YsortCameraGroup.py) / level:

```text
… y-sorted sprites (incl. meteor fire) …
fluid ground haze
fluid rise pass
building roofs
overhead canopies
… weather overlay / lighting …
```

Roofs/canopies therefore cover elevated smoke. No per-demon soft-particle depth in v1 (accept in-front/behind by pass only).

### Explicit non-goals (v1)

- Full 3D voxel / multi-slice volume  
- Depth-test against mesh demon  
- Cliff height masks (add later if terrace bleed shows)  
- Keeping sprite `SmokeSystem` as the main look  

## Code map

### New: `Code/gpu_fluid_smoke.py` (or `Code/fluid_smoke.py`)

Thin CPU API owning sim parameters and splat queue:

- `queue_splat(world_x, world_y, amount, radius_px)`  
- `step(dt, weather, camera_offset, view_size)` → calls backend  
- Tunables: dissipation, curl, wind_scale, buoyancy, splat_force  

### Extend: [`Code/render_backend.py`](Code/render_backend.py) (`GPUBackend`)

- `_init_fluid_pipeline()`: FBOs, float/half-float textures (detect `GL_RGBA16F` / fall back `RGBA8` with reduced quality), fullscreen triangle VAO, shader programs for splat / advect / curl / divergence / pressure / gradientSubtract / display.  
- `fluid_step(dt, wind_xy, splats)`  
- `fluid_draw_ground()` / `fluid_draw_rise()`  
- Resize/recreate on backend resize if needed  
- [`CPUBackend`](Code/render_backend.py): no-op stubs (server / cpu path)

Reuse patterns from existing light FBO (`_light_fbo`, bind/unbind, flush batch before FBO switches).

### Hook: [`Code/meteor_strike.py`](Code/meteor_strike.py)

On impact enter: **remove** `smoke_fx.emit(...)`. Call `level.fluid_smoke.queue_splat(ground_pos, ...)` (and optional light residual splats while in residual/linger).

### Hook: [`Code/Level4_tmxdev.py`](Code/Level4_tmxdev.py)

- Construct `fluid_smoke` instead of (or beside, disabled) `SmokeSystem`  
- After `weather.update`: `fluid_smoke.step(dt, weather, offset, size)`  
- Replace `_draw_smoke_fx` with ground+rise draws at the correct point (after `custom_draw` sprites… ideally **inside** custom_draw before roofs). Prefer a callback/`backend` draw from camera group, or split `custom_draw` hook — cleanest: add optional `post_sprites_fx` callable on the camera group, or draw rise/ground from level **only if** we move roof pass — **locked choice:** extend `YsortCameraGroup.custom_draw` to call `level.draw_fluid_smoke_mid()` between sprites and roofs when `level` provides it.

### Retire: [`Code/smoke_fx.py`](Code/smoke_fx.py) sprite path

Stop constructing / updating / drawing sprite smoke. Delete or gate behind `FLUID_SMOKE=1` once fluid is stable. Do not leave both systems on (double smoke).

## Implementation phases

### Phase 0 — Clear the bad path
- Disable meteor → `smoke_fx.emit`  
- Disable `_draw_smoke_fx` / updates  
- Gameplay unchanged; fire VFX only  

### Phase 1 — Fluid toy in-engine
- FBO + shaders; mouse or debug key splat optional  
- Fullscreen composite only (no 2.5D rise yet)  
- Verify look matches demos (soft curl, fade) on desert  

### Phase 2 — Game wiring
- Meteor splat + weather wind  
- Fast enough dissipation for camera move  
- Cap splat queue per frame  

### Phase 3 — 2.5D composite
- Ground + rise passes; insert before roofs/overhead  
- Tune rise offset / alpha so it doesn’t read as a second hard slab  

### Phase 4 — Tune / ship gate
- Shower stress: many meteors, watch frame time vs current ~30 FPS  
- If cost high: drop Jacobi iterations, lower res (96/192), or step fluid every other frame  

## Key shader notes

- Ping-pong: never read/write same texture  
- Semi-Lagrangian advect (backward trace)  
- Jacobi pressure: start **20–30** iterations; cut if needed  
- Display: `alpha = smoothstep(edge0, edge1, density)`; colour cool grey; optional very soft lighting from density gradient (Pavel-style) — keep subtle on desert  

## Risks

| Risk | Mitigation |
|------|------------|
| Looks like a flat stain | Rise pass + buoyancy; don’t skip Phase 3 |
| Rise pass looks like a second slab | Same texture, continuous fade/offset in shader — no discrete “layer colour” |
| Float texture unsupported | Detect + RGBA8 fallback / document GPU requirement |
| Camera scroll trails | Higher dye dissipation; later: scroll field with camera |
| Frame cost | Low sim res, alternate-frame step, fewer Jacobi iters |

## Verify

1. Single impact: soft plume curls, rises up-screen, fades — no cardboard, no black gutters.  
2. Wind from weather visibly streams the field.  
3. Standing under canopy/roof: elevated smoke obscured when overhead draws.  
4. Meteor shower: merges into haze; no FPS cliff vs pre-smoke baseline.  
5. CPU/server backend: no crash (no-ops).

## Reference look (external)

- https://paveldogreat.github.io/WebGL-Fluid-Simulation/  
- https://www.runcell.dev/tool/smoke-simulation  
- GPU Gems: Fast Fluid Dynamics Simulation on the GPU (Jos Stam lineage)
