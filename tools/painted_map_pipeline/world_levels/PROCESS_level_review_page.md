# Level review page + padding offset

## Method
- Launch (repo root, PowerShell):
  `Code\sprite_venv\Scripts\python.exe -m tools.painted_map_pipeline.world_levels.review_page <run_root> [--levels 01-06] [--feather N] [--prompt-file F] [--port 8766] [--no-browser]`
- Opens `http://127.0.0.1:8766/`. Port 8765 is the SAM page / SAM server.
- Same actions as `review_run`: re-place (feather / warp / cut / align / padding), checks, accept, retry (reason, image, note, r1), generate. Next = skip.
- Each level is pinned to one attempt (picker in the top bar). Re-place, the images and accept all use that attempt's files and pass `--attempt N`.
- Align view: raw `jobs/attempt_N/generated.png` with the padding (`locked_overlap.png`, alpha = `locked_overlap_mask.png`) over it.
  - Drag moves the padding. Ctrl + drag pans, the wheel zooms.
  - Arrows nudge 1 px, Shift + arrows 10 px.
  - T swaps which layer is on top; the slider sets the top layer's opacity.
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
- One offset only fixes a pure shift. If the model also scaled the picture, no single offset lines up both sides.

## Log
- 2026-11-12: built on `feat/level-review-page`. Stack copied from sam3local `feat/review-page` (stdlib server, one HTML file, Leaflet copied in, polling).
- 2026-11-12: direction check on a copy of bitter_floe_7x6 level 06 attempt 16: raw shifted (5, -3) and placed with `--padding-offset=5,-3` matched the unshifted placement on 4,196,450 / 4,196,450 new-cell px; without the offset 20,108.
- 2026-11-12: page on that copy: Align colours at (2, -1) took 15 s, 640,478 pairs, `colour_align_010.png`.
- Not yet done: dragging in a browser by hand.

## Tried and dropped
- Colour methods: see `PROCESS_world_levels.md`.
