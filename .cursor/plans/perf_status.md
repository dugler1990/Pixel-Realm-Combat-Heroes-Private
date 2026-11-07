# Speed work: where we are

Updated 2026-11-02.

**Goal:** the ice map runs smoothly at 200+ entities.

**Rules:** every speed-up also simplifies the code (no dead code, no second path), is measured
before and after on a fixed scene, and is logged in `Code/NOTES_performance.md`.

## Done (on main)

- HUD fills batch with the sprites: `36f7ba4`, test fix `28b04dd`. `fill` + `draw_rect`
  went from 6.4 to 0.7 ms per frame (profiled, ice map play).

## In progress: `perf_hits_and_atlas.plan.md`, branch `perf/hits-and-atlas`

1. Done. Draw calls are counted in `_flush_batch`. Baseline (ice map, 200, benchmark): avg 835.6 ms, p95 1247 ms, 648.5 draw calls/frame. Profiled per `custom_draw` (30, includes warmup): 613 sprites, 843 `_flush_batch`, 344 `_resident_texture`, `find_hits` 218 ms.
2. Done in code. `find_hits` filters by rect first. Unprofiled ice-200 row: avg 1020.7 ms, p95 1737 ms, 599.9 draw calls/frame. The profiled half was closed.
3. Done in code. The atlas packs an ImageCache surface the first time it is drawn. `build_atlas` is gone. GPU test passed: two cached sprites and a fill are one draw call. No further 200-sprite game run.
4. Done in code. RTS sprites load through `ImageCache`. No further 200-sprite game run. `tests/rts`: one failure, `test_gather_paths_around_wall`, which also fails on the commit before this change.

**Play check still open:** ice map past 200 entities, profiler on, compare `_resident_texture` and `_flush_batch` per frame with the 2026-11-02 profile (133 and 336). The 200-sprite benchmark runs were stopped.

## Later

Belt HUD text (~4 ms), enemy targeting (~6 ms), sprite updates (~14 ms).

## Profile reference

Ice map play, 2026-11-02, profiler on, ms per frame: sprite drawing 18.8, sprite updates
14.2, HUD ~12 (now ~6), targeting 6, `find_hits` 5.1, `check_effects` 3.1, smoke 2.6.
