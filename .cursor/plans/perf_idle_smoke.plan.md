---
name: perf idle smoke
overview: "Stop the fluid solver and its draw on frames where no smoke is fading. Anything that queues a splat starts the cloud. The solver then runs until the cloud is FADE_STOP as thick as it was at the last puff, and then stops. Branch fix/smoke-idle."
todos:
  - id: test
    content: "Add tests/test_idle_smoke.py. An empty queue must not call _gl_step or _try_init. A puff runs for fade_steps frames, including the puff frame, then stops. A puff during the fade restarts that count. An off-screen puff does not start it. Draws follow _show."
    status: completed
  - id: gate
    content: "FADE_STOP = 0.02 on GpuFluidSmoke. fade_steps is computed from that and den_dissipation. step returns before GL init and _gl_step when no steps are left. draw_ground and draw_rise return unless _show."
    status: completed
  - id: measure
    content: "Run the idle-smoke test. A later ice-map profile should show step and draw_fluid_smoke_mid near 0 ms when nothing has produced smoke."
    status: pending
isProject: false
---

# Speed: do not simulate smoke when nothing is smoking

## Why

`ice_200_atlas.prof`, per `custom_draw` (3122 frames): `gpu_fluid_smoke.step` is 2.67 ms, almost all of it `_gl_step` (26 `_blit` calls). `draw_fluid_smoke_mid` is another 0.27 ms. Both run when no puff has been queued.

The cloud gets thinner every solver frame: thickness is multiplied by `den_dissipation` (0.968). That never reaches zero, so the solver would keep running forever after the first puff. This change stops it once the cloud is a configured fraction of the thickness it had at the last puff.

That stop is a visible change. The cloud matches the current one while it is thick and while it fades. The last faint wisp is not drawn. Combat, damage, and movement do not read this smoke.

Count solver frames, not seconds. The fade multiplies once per `step`. At a low frame rate a wall-clock timeout would cut the cloud off while it is still thick.

## Config

On `GpuFluidSmoke`, next to `MAX_SPLATS`. This is the knob. 0.02 was chosen as a faint ghost. It is not a value the game already used, and it has not been judged in play.

```python
# Stop once the cloud is this fraction of the thickness it had at the last puff.
FADE_STOP = 0.02
```

`den_dissipation` stays where it is. In `__init__`, immediately after it is set:

```python
self.fade_steps = max(1, math.ceil(math.log(self.FADE_STOP) / math.log(self.den_dissipation)))
```

With the current 0.968, `fade_steps` is 121. `0.968 ** 120` is 0.0202, still above the setting. `0.968 ** 121` is 0.0196, the first step at or under it. Changing either number without the other cannot leave a stale step count, because the count is computed.

Do not clear the GPU buffers when the solver stops. The next puff keeps building on what is left.

## Before you start

- Branch: `fix/smoke-idle`, from current `main`.
- Do not stage other sessions' files: `tests/test_entity_pipeline.py`, `tools/entity_pipeline/figures.py`, `tools/painted_map_pipeline/leonardo_api.py`, or the untracked `.cursor/plans/` files.
- Re-read `GpuFluidSmoke.step`, `draw_ground`, and `draw_rise` by name before editing.
- One commit on the branch, then merge to `main` and push `origin/main`.

## Do not

1. Do not skip the solver on a frame that has an on-screen puff, or while `fade_steps` solver frames from that puff are still running. A new puff restarts the count.
2. Do not change dissipation, wind, splat size, or any caller's `queue_splat`.
3. Do not touch `Level4_tmxdev.py`. The gate lives on `GpuFluidSmoke`.
4. Do not init GL on an idle frame. `_try_init` stays behind the gate.
5. Do not add a clock. Menus already skip `step`, so the fade pauses with the rest of the frame.

## Step 1. `Code/gpu_fluid_smoke.py`

In `__init__`, next to `self._queue`:

```python
self._steps_left = 0
self._show = False  # True when this frame's step wrote buffers worth drawing
```

`_show` exists because the last drawn frame has already decremented `_steps_left` to 0. Draw cannot look at the counter alone.

Replace the body of `step` so the queue is drained before any GL work. Keep the splat UV conversion, the off-screen reject, the wind block, and the `_gl_step` call as they are now. The new order is:

1. `if self._failed: return`
2. The existing `dt` clamp and the view-size check (`vw < 1 or vh < 1`). These do not need GL. On a bad view, return without changing `_steps_left` or `_show`, and without clearing the queue.
3. Build `splats_uv` from `self._queue` with the current loop, then `self._queue.clear()`.
4. Arm or burn the fade:

```python
if splats_uv:
    self._steps_left = self.fade_steps
if self._steps_left <= 0:
    self._show = False
    return
self._steps_left -= 1
```

5. Only then the existing `if not self._ready: _try_init()` block. If init fails, set `_show = False` and return.
6. The existing wind / curl / buoyancy block, then `_gl_step(...)`, then `self._show = True`.

`draw_ground` and `draw_rise`: return unless `self._ready and self._show`.

An off-screen splat is still dropped by the existing UV reject, does not enter `splats_uv`, and does not arm the fade. That matches today: those splats never reached the solver.

The puff frame is one of the `fade_steps` solver frames. Dissipation runs in that same `_gl_step`, after the splat is written. `fade_steps` solver frames means `fade_steps` multiplies, which is the frame that first lands at or under `FADE_STOP`.

## Step 2. `tests/test_idle_smoke.py`

No window and no GL. Construct `GpuFluidSmoke(backend=None)`. Patch `_gl_step` and `_try_init`. `_try_init` sets `_ready = True` and returns `True`.

- `fade_steps` equals `ceil(log(FADE_STOP) / log(den_dissipation))`. `den_dissipation ** fade_steps <= FADE_STOP`, and one step earlier is still above it.
- `step(1/30, None, (0, 0), (800, 600))` with an empty queue: `_gl_step` and `_try_init` were not called, `_show` is false.
- `queue_splat((100, 100))` then `fade_steps` calls: `_gl_step` was called `fade_steps` times. `(100, 100)` is inside the 800×600 view at offset `(0, 0)`. The next `step` does not call it.
- After 10 steps of a fade, another on-screen `queue_splat` restarts it: `fade_steps` further calls run, and the one after that does not.
- `queue_splat((5000, 5000))` then one `step`: `_gl_step` and `_try_init` were not called.
- A 0×0 view does not clear the queue. The following normal `step` still runs `_gl_step`.
- After the fade has ended, `_ready` is still true, and `draw_ground()` and `draw_rise()` return without calling `_draw_display`. On a puff frame they call it.

Run:

```powershell
.\Code\sprite_venv\Scripts\python.exe -m pytest tests/test_idle_smoke.py -q
```

## Step 3. Measure

Ice map, same way as `logs/perf/ice_200_atlas.prof`. Quit once gameplay is up and no smoke has been produced. A fight is not required.

```powershell
cd C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\Code
.\sprite_venv\Scripts\python.exe -m cProfile -o ..\logs\perf\ice_200_idle_smoke.prof Main2.py
```

Per `custom_draw`, `gpu_fluid_smoke.step` and `draw_fluid_smoke_mid` should be about 0 ms. That profile does not show the fade. The test covers the fade. In play, produce smoke once. The cloud still appears and fades, and the last faint wisp is absent. It must not freeze solid and sit on the ground.

## Log

Add a row to `Code/NOTES_performance.md` only after that profile exists. Note `step` and `draw_fluid_smoke_mid` ms per `custom_draw` before (2.67 and 0.27 in `ice_200_atlas.prof`) and after.
