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

## Next: `perf_targeting_and_projectiles.plan.md`, branch `perf/targeting` (worktree `..\Pixel-Realm-targeting`)

Written 2026-11-07, not started. Parry skips its lookup when the chance is 0, aggro timer on
each fighter's own beat, nearest search that grows its box, hit tests matched by rect in C
(`collidelistall`, after a viability check). Also gives the benchmark three hostile teams and
the play grid (it has been measuring one team on the quadtree).

## Later

Belt HUD text (~4 ms), enemy targeting (~6 ms), sprite updates (~14 ms).

Small tweak to consider after the targeting timer and search fixes (2026-11-07):

- **Neighbours share one target search.** Fighters of the same team and the same monster type,
  standing close together, use one search and copy its result. Fighters that are retaliating
  neither copy nor hand on their pick (a 12 s window, so many fighters in a brawl). Build the
  share once per tick in the level loop, next to `entity_id_map`, not per world draw, since the
  server never draws. Guess: about 1 ms at ~40 fighters, more with bigger crowds. Not measured.
  Behaviour change: a nearby group goes for one target. Original write-up:
  `dumb_fighters_share_target.plan.md`. Its profile table is wrong: the 3.3 ms it calls
  rechecks is the searchers' grid lookups.

## Profile reference

Ice map play, 2026-11-02, profiler on, ms per frame: sprite drawing 18.8, sprite updates
14.2, HUD ~12 (now ~6), targeting 6, `find_hits` 5.1, `check_effects` 3.1, smoke 2.6.
