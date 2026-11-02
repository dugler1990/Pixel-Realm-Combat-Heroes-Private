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
