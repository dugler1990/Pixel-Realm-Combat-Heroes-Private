# Level review page + padding offset

## Method
- Launch (repo root, PowerShell):
  `Code\sprite_venv\Scripts\python.exe -m tools.painted_map_pipeline.world_levels.review_page <run_root> [--levels 01-06] [--feather N] [--prompt-file F] [--port 8766] [--no-browser]`
- Opens `http://127.0.0.1:8766/`. Port 8765 is the SAM page / SAM server.
- Re-place and accept run inside the page's own Python (pipeline loaded once, at start). After a change to pipeline code: restart the page. HTML change: Ctrl+F5. Generate still runs as its own process.
- Same actions as `review_run`: re-place (feather / warp / cut / align / padding), checks, accept, retry (reason, image, note, r1), generate. Next = skip.
- Build map: stitches every accepted level in the run (not only the one on screen) to `<run_root>/assembled_world.png`. A level not accepted is filled from the source map and named in the message. No TMX, no game tables. Same stitch as `orchestrate assemble` without `--level-dir`.
- Add to menu: folder name, card name, open slot on the 3×4 grid (`LEVEL_AT` in `Code/LevelSelection.py`; commented cells are free). Builds the playable map from `assembled_world.png` (stitches first if that file is missing) and registers it. Tile size 150. A folder already on the menu keeps its slot and the button rebuilds that map. Writes `levels/Frostreach/<folder>`, `Code/level_layouts.py`, `Code/LevelSelection.py`, and `Graphics/Level/<row+1>_<col+1>.png` in the folder the page was started from.
- Upscale tab: paste the RunPod Connect SSH line (`ssh user@host -p PORT -i key`). Connect installs HYPIR-SD2 on that pod when `weights/HYPIR_sd2.pth` is missing (`pod_upscale.py`). Send runs one 2× pass on the level on screen: accepted image, else the latest `generated.png`. Writes `levels/<id>/upscale/hypir.png` and `hypir_native.png` (2× scaled back to the source size). Disconnect drops the session only. The pod is stopped in RunPod. Plan: `PLAN_upscale_tab.md`.
- Each level is pinned to one attempt (picker in the top bar). Re-place, the images and accept all use that attempt's files and pass `--attempt N`.
- Align view: raw `jobs/attempt_N/generated.png` with the padding (`locked_overlap.png`, alpha = `locked_overlap_mask.png`) over it.
  - Drag moves the padding. Ctrl + drag pans, the wheel zooms.
  - Arrows nudge 1 px, Shift + arrows 10 px.
  - T swaps which layer is on top; the slider sets the top layer's opacity.
  - Drag: padding / picture (button or P). Picture = drag the generation into the level's shape. Same offset either way (picture moved by (x, y) = padding by (-x, -y)).
  - Yellow line = the level's shape (what a cut keeps). Pink = holes a cut would leave at this offset (drawn 2 px thicker). "Holes after a cut" = count + cut IoU, refreshed 0.25 s after a move.
  - Fit shape = jump to the offset with the fewest holes (shape only). At the 40 px limit the land is a different size: a shift will not fix it.
- Align colours = re-place with `--align-colours --padding-offset=DX,DY`. The dropdown next to the tickbox picks the colour method: match (default) or swap (old). Methods: `PROCESS_world_levels.md`.
- Offset (dx, dy) = how far the padding moved, right/down, to sit on the generation.
  - Warp off: ingest moves the generation by (-dx, -dy) (`frame.shift_image`, edges repeated) before cut, the colour pairs and the paste.
  - Warp on: only the colour-pairing copy moves; the warp places.
  - The pairing copy's opened band is black, so near-black pairs drop it (`CONTENT_MIN_RGB_SUM`).
  - Frame renderer: a non-zero offset is refused (it undoes its own drift, raw is frame-sized).
  - Recorded as `placement_padding_offset` in job.json and `padding_offset` in ingest output.
- CLI: write a negative DX as `--padding-offset=-3,2` (one token; argparse reads `-3,2` as an option).
- Tests: `Code\sprite_venv\Scripts\python.exe -m pytest tests/painted_map_pipeline/test_review_web.py tests/painted_map_pipeline/test_colour_align.py tests/painted_map_pipeline/test_world_levels.py`

## Known errors
- Page and `review_run` on the same run at once: both write run.json / job.json. Use one at a time.
- "job context is stale": the attempt's padding, padding mask or shape differs from the level's now (a neighbour accepted since). Generate a new attempt.
  - Was also refused when only the soft base changed: a refine (r) sends a placed image as base, the next run the plain one, each bumping `context_revision`. Level 06 attempt 1 (rev 6, level rev 8) has byte-identical padding / mask / shape hashes. Fix: `_same_padding` in result_ingest lets it through when those three hashes match the manifest. Check: on a copy, attempt 1 placed; feather 24 vs 0 changed 242,067 px.
- "Feather does nothing": it only applies on Re-place and only shows in the Result view (Align shows the raw). Fix: changing feather / a toggle turns Re-place amber; a re-place switches to Result. Check: feather 24 vs 0 on level 06 attempt 16 changed 240,696 px.
- Align colours repeated the old swap on level 06 attempt 1 (`colour_align_007.png`, method swap, same as 006): the dropdown was preset to swap for placements aligned before the methods existed. Fix: the Align colours button always uses match; unlabelled old placements preset match; swap only via dropdown + Re-place.
- Slow re-place, even cut only (2026-11-14, level 06 attempt 1): each press started a new Python that reloaded numpy / scipy / cv2. Warm 4.4 s (1 s loading, 3 s placing); first press after idle 83 s (78 s reading library files off disk). Fix: run in the page's process, loaded at start. Now: cut 3.3 s, cut + feather 3.8 s, align first per level 14.6 s, align again 8.1 s (page object on a copy, real pipeline).
- One offset only fixes a pure shift. If the model also scaled the picture, no single offset lines up both sides.

## Log
- 2026-11-12: built on `feat/level-review-page`. Stack copied from sam3local `feat/review-page` (stdlib server, one HTML file, Leaflet copied in, polling).
- 2026-11-12: direction check on a copy of bitter_floe_7x6 level 06 attempt 16: raw shifted (5, -3) and placed with `--padding-offset=5,-3` matched the unshifted placement on 4,196,450 / 4,196,450 new-cell px; without the offset 20,108.
- 2026-11-12: page on that copy: Align colours at (2, -1) took 15 s, 640,478 pairs, `colour_align_010.png`.
- 2026-11-15: Build map button. Writes `assembled_world.png` only. Test: `test_build_map_writes_the_stitched_png_and_names_what_is_missing` (fake stitch, 4x3 png, missing level named).
- 2026-11-15: Add to menu. `taken_slots` reads `LEVEL_AT` (the grid dict was renamed; it had been returning no slots). Tests: open slot used, taken slot refused, existing slot kept, stitch-if-missing, `ensure_name` once.
- 2026-11-16: Bitter Floe spawn was the default (2250, 3750), which is black. `player_spawn` in its map.tmx at (11179, 6688), on the ice (600 px window, 0 near-black). Other levels keep tile (15, 25).
- Not yet done: dragging in a browser by hand.

## Tried and dropped
- Colour methods: see `PROCESS_world_levels.md`.
