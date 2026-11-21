# Performance notes

Read this before writing anything that runs every frame. The rules are patterns measured to
be fast: use them without debate. The dangers each cost us frame time once. The log records
what each change measured.

## Rules

1. **Every image drawn more than once comes from ImageCache**: `ImageCache.load_image`,
   `load_scaled`, `keep_frames`, or `Support.import_folder` / `import_folder_flipped`. The GPU
   backend copies an ImageCache surface into its sprite atlas the first time it is drawn, and
   from then on it batches with every other sprite.
2. **Never make a surface per frame**: no `transform.rotate/scale/flip`, `.copy()` or
   `font.render` inside an update or draw. Build once, keep it, or cache it by a stable key.
   Text that changes: render it when it changes and call `backend.invalidate_texture` on the old one.
3. **`fill` and `draw_rect` are cheap**: they batch with the sprites (the atlas's white texel).
   A blend `flags=` value forces two flushes: use it only for full-screen overlays.
4. **"What does this touch" filters by rect first**: one `Rect.colliderect` per candidate in a
   list comprehension, before any other per-candidate work. Masks only for the survivors.
   See `hit_core.find_hits`.
5. **Direct GL draws flush first**: anything that draws outside the batch (grass, smoke,
   lights, mesh) calls `_flush_batch()` before it draws.

## Dangers

- **A sprite whose image is not an ImageCache surface** is one draw call per sprite per frame
  (~100 µs with the profiler on). Known today: rotated arrows (`Particles._face_direction`),
  chest copies (`InteractableChest`), per-instance scaled tribey snakes.
- **`id(surface)` as a cache key** is only safe for surfaces that never die. A freed surface's
  id is reused by the next one, which then draws the old image.
- **A Python loop over all entities, once per attack or once per entity, every frame.**
  At 200 entities that is tens of thousands of iterations per frame.
- **Loading from disk during play**: ~8 ms per PNG (profiled), a visible stall.

## How to measure

Fixed scene: the ice map in benchmark mode, 200 enemies from the map's own spawn mix. Each run
spawns them, warms up 10 s, measures 30 s, writes one row to `logs/perf_ice200.csv` and quits.
Counts (draw calls per frame, calls per frame) don't drift with the machine; times do, so take
a phase's before and after runs back to back. The map's own spawners keep adding enemies during
a run, so compare draw calls per sprite drawn as well as per frame.

## Log

| Date | Change | Scene | avg ms | p95 ms | draw calls / frame | Notes |
|---|---|---|---|---|---|---|
| 2026-11-02 | HUD fills batch with sprites (`36f7ba4`) | ice map, play, profiled | | | | `fill` + `draw_rect` 6.4 → 0.7 ms per frame |
| 2026-11-02 | baseline: draw calls counted on flush | ice map, 200 benchmark | 835.6 | 1247 | 648.5 | profiled per `custom_draw` (30, includes warmup): 613 sprites, 843 `_flush_batch`, 344 `_resident_texture`, `find_hits` 218 ms |
| 2026-11-02 | `find_hits` filters by rect first | ice map, 200 benchmark | 1020.7 | 1737 | 599.9 | unprofiled run only; the profiled run was closed before it finished |
| 2026-11-02 | ImageCache sprites pack into the atlas on first draw | not remeasured | | | | 200-sprite run was stopped. GPU test: two ImageCache sprites and a fill are one draw call |
| 2026-11-02 | RTS sprites load through ImageCache | not remeasured | | | | 200-sprite run was stopped. `tests/rts` has one failure, `test_gather_paths_around_wall`, which also fails on the previous commit |
| 2026-11-07 | Legion HUD, before (`c6a017e`) | ice map, 200 benchmark, grid 450 | 369.0 | 420 | 684.3 | run 2: 391.7 / 487 / 700.9 |
| 2026-11-07 | Legion HUD: kit meters, slot frames, belt (legion_ui) | ice map, 200 benchmark, grid 450 | 473.4 | 619 | 732.0 | runs 2 and 3: 453.1 / 539 / 674.1 and 349.1 / 437 / 590.4. The same code moves ~100 ms and ~140 draw calls between runs, so these rows can't resolve the HUD. Counted directly on the GPU backend: the HUD and belt are 22 blits a frame, 20 batched in the atlas, 2 own calls (the experience and level text), 0 uploaded; the old HUD sent its text, weapon and magic pictures, belt labels and lock shades as separate calls |
| 2026-11-14 | Contact point: `find_contacts` on swings, shots, dashes; projectile entry walk (`refactor/contact-point`) | micro-benchmark: 200 candidates (48x64 ellipse masks), 20 touching, best of 7 x 2000 | | | | `find_hits` 85-99 us, `find_contacts` 88-106 us per call (+3-7 %, 3 runs). `entry_point` ~20 us per projectile hit (reach 28), so it runs only for hits that land (`hit_core.EntryPoints`, asked by `strike` after its repeat and team checks). 200-enemy benchmark not run: it moves ~100 ms between runs of the same code |
| 2026-11-14 | Bodies and layers: region lookup, defence profile (`refactor/defence-layers`) | micro-benchmark, barb pack, machine ~40% busy (other agents' Blender jobs) | | | | `body_regions.mesh_slot` 61 us with the projection cached on the skin, 329 us for the first hit in a frame (pose + project + depth); `sprite_slot` 1.6 us; `build_profile` full plate 31 us (on equip only). Runs only for landed hits on bodies with worn layers (the hero); nothing per frame. Not on the hit path until chunk 5 |
| 2026-11-15 | Visual hits: mesh hero hit on his mesh's points, worn pieces in it (`refactor/visual-hits`) | micro-benchmarks, barb 56 px figure | | | | Body outline per new pose 0.47 ms (capsules 0.36), +0.75 ms first use of a frame; full plate (6.9k points) 3.7 ms first use of a frame, 1.0-1.2 ms new facing, 3-6 us cached; `hit_layers` 6-9 us. Built only while an attack is near him (`hit_rect` is a cheap reach box). `find_hits` 200 candidates 73 vs 77 us medians (noise): the hero is checked by `hit_core.reaches_past_rect` after the rect test, not via a getattr on every candidate (that cost +12-25%). Memory: <= 128 posed frames per worn set, float32 (~10 MB full plate) |
| 2026-11-17 | Physical resolve: `hit_resolve` prices a delivery before the receiver (`refactor/physical-resolve`) | micro-benchmark, 50k calls, no outline lookup | | | | Unarmoured `(natural,)` 2.1-2.7 us; three layers (plate, gambeson, hide) 2.8-3.8 us. The outline lookup stays the 6-9 us from 4b, and only for a worn body with a contact pixel. Nothing per frame |
| 2026-11-17 | Condition clock: empty `tick` and `bonus` (`refactor/conditions`) | micro-benchmark, 200k calls, empty body | | | | `tick` 0.155 us, `bonus` 0.227 us. A peek and a dict check. Nothing else per frame. Not the 200-enemy scene |
| 2026-11-18 | Elemental: one cold apply, one 4-arc bolt (`refactor/elemental`) | micro-benchmark, 20k calls, no quadtree | | | | Full cold 7.5 µs, simple cold 4.4 µs, bolt against 8 bodies 3.3 µs. A hit, not a frame. The hop asks the entity quadtree at most `arcs` times, and only after a bolt lands. Not the 200-enemy scene |
| 2026-11-18 | Temperature: one solved air interval, one blow onto a stored warmth (`refactor/elemental`) | micro-benchmark, 20k intervals and 5k blows, no pygame | | | | Air interval 7.6 µs (the solved stay, not a frame step). One blow 111 µs. A handful of multiplies on one full body when a source changes or the clock wakes. Not per frame. Not the 200-enemy scene |
