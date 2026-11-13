# World levels: generation, placement, colour

Reference docs: `../IRREGULAR_WORLD_LEVEL_WORKFLOW.md` (contract, states), `GRID_PLAN_NOTES.md` (plan, scale).
Review page: `PROCESS_level_review_page.md`.

## Method
- Run (PowerShell, repo root): `Code\sprite_venv\Scripts\python.exe -m tools.painted_map_pipeline.world_levels.review_page <run_root>` (page) or `... .review_run <run_root>` (console). One at a time per run.
- Per level: generate (API) -> place (no API) -> look -> re-place with settings -> tests (`t` / Run tests) -> accept. Accepted pixels become the neighbours' padding.
- What the model gets: one image, canvas size (Bitter Floe 3536x2064): soft upscale of the level + the accepted neighbours' padding pasted in sharp. Same size back, no resize.
- Placing (`result_ingest.ingest_result`): shift by the padding offset (warp off) -> renderer place -> colour align (optional) -> paste the real padding over it (feather N = fade across the join) -> `attempts/attempt_NNN/placement_NNN.png` or `colour_align_NNN.png`.
- Padding offset (dx, dy): how far the padding moves right/down to sit on the model's redraw of it. Dragged on the page. Fixes the colour pairs and (warp off) the placement.
- Colour align (`colour_align.py`), learned from the model's own copy of the padding against the real padding, same spots; writes the new cell only:
  - **match** (default, `--colour-method match`): swap -> brightness mix -> join fix -> snap.
  - **swap** (`--colour-method swap`, the earlier method): swap -> snap.
  - Swap: Lab colour groups (8-unit bins); each group's median shift; groups with < 20 pairs skipped; other colours get a weighted mix of the 8 nearest groups.
  - Brightness mix: new-cell lightness remapped rank for rank onto the padding's lightness values. Hue kept.
  - Join fix: Lab difference (padding minus swapped model copy) at each padding spot, smoothed (Gaussian 24 px, normalised), carried out to the nearest value, faded by exp(-distance / 200 px) from the padding.
  - Snap: every new pixel -> nearest of 256 padding colours (k-means in Lab).
- Scoring a colour method: learn on half the padding (64 px checkerboard blocks), score on the other half. Error per pixel, error per 16 px chunk (Lab), brightness spread vs padding (1 = same), brightness mix gap. Script pattern: scratch `colour_test.py` (not kept).

## Known errors
- Model drift: same input and prompt, the return moves or redraws the padding. Level 06: attempt 1 at (0,0); 6, 7, 14, 16 within 1-4 px; most others no match up to 24 px (edge correlation). Small shifts: drag the offset. Large / redrawn: regenerate.
- Pixel-for-pixel colour cannot match: the model's details are not where the padding's are. Best per-pixel Lab error on held-out padding ~23 (untouched 32).
- Swap alone greys the new cell: mismatched pairs pull each group's median to the middle. Level 06 attempt 1: spread 23.4 vs padding 26.6. Fixed by the brightness mix in match.
- Detail size differs at some joins (padding in bigger blocks than the new art). Colour cannot fix it; feather hides it.
- "job context is stale" on an attempt whose padding did not change: a refine bumps `context_revision` via the soft base only. Fixed: `_same_padding` compares the generation-mask / padding-mask / padding hashes.
- Prompt said "of this image of this image" when the padding is not a single edge strip (`describe_padding`). Fixed 2026-11-12.

## Log
- 2026-11-12: level 06 attempts 1-16: inputs byte-identical except attempt 2 (refine); prompts identical (1 and 16); sent 3536x2064, got 3536x2064.
- 2026-11-13: colour methods on level 06 attempt 1, held-out half of the padding:

  | method | px err | 16 px chunk err | spread (pad = 1) | mix gap |
  |---|---|---|---|---|
  | untouched | 32.2 | 20.2 | 1.15 | 5.7 |
  | swap | 23.5 | 14.4 | 0.92 | 2.2 |
  | swap, clean pairs only | 23.8 | 14.7 | 0.91 | 2.6 |
  | swap + brightness mix | 24.0 | 13.6 | 1.00 | 0.8 |
  | match (+ join fix) | 23.1 | 12.2 | 1.05 | 1.5 |
- 2026-11-13: through ingest, attempt 1, whole new cell: padding mean 45.7 / spread 26.6; swap 42.8 / 23.4 (19 s); match 46.1 / 26.6 (26 s). Swap + feather 40 + cut reproduces the run's `colour_align_006.png` exactly (0 px differ).
- 2026-11-13: by eye (labelled crops, top and left joins): match brighter and with more contrast, closer to the padding; join line still visible without feather.

## Tried and dropped
- Single Lab offset (`lab_offset`, previous agent): seam step 7.11 / 3.70 / 0.83 / 3.68 at strength 0.25 / 0.5 / 0.75 / 1.0. Unverified numbers. One shift for everything, so it cannot fix contrast.
- Full-palette quantile match (`full_palette`, previous agent): seam step 1.99 / 6.45 / 12.61 at 0.5 / 0.75 / 1.0. Unverified. Dropped as worse at full strength. Differs from the brightness mix: that matches L only, after the swap, hue kept.
- Paired colour map (`paired_colour_map`, previous agent): 4.74 / 1.69 / 1.88 / 4.96 at 0.5 / 0.75 / 1.0 / 1.25. Became "swap".
- Clean pairs (keep pairs whose 9x9 lightness correlation > 0.5; 113,571 of 315,780): no gain (chunk err 14.7 vs 14.4). Dropped.
