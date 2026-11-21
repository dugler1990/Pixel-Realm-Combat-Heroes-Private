# World levels: generation, placement, colour

Reference docs: `../IRREGULAR_WORLD_LEVEL_WORKFLOW.md` (contract, states), `GRID_PLAN_NOTES.md` (plan, scale).
Review page: `PROCESS_level_review_page.md`.

## Method
- Run (PowerShell, repo root): `Code\sprite_venv\Scripts\python.exe -m tools.painted_map_pipeline.world_levels.review_page <run_root>` (page) or `... .review_run <run_root>` (console). One at a time per run.
- Per level: generate (API) -> place (no API) -> look -> re-place with settings -> tests (`t` / Run tests) -> accept. Accepted pixels become the neighbours' padding.
- What the model gets: one image, canvas size (Bitter Floe 3536x2064): soft upscale of the level + the accepted neighbours' padding pasted in sharp. Same size back, no resize.
- Placing (`result_ingest.ingest_result`): shift by the padding offset (warp off) -> renderer place -> colour align (optional) -> paste the real padding over it (feather N = fade across the join) -> `attempts/attempt_NNN/placement_NNN.png` or `colour_align_NNN.png`.
- Padding offset (dx, dy): how far the padding moves right/down to sit on the model's redraw of it. Dragged on the page. Fixes the colour pairs and (warp off) the placement.
- Colour align (`colour_align.py`), learned from the model's own copy of the padding against the real padding, same spots; recolours every pixel the model drew (black gaps left). Masks only pick what colours are learned from, never where they are written, so the paste / feather / padding strips after it always see a fully recoloured image:
  - **match** (default, `--colour-method match`): swap -> brightness mix -> join fix -> snap.
  - **swap** (`--colour-method swap`, the earlier method): swap -> snap.
  - Swap: Lab colour groups (8-unit bins); each group's median shift; groups with < 20 pairs skipped; other colours get a weighted mix of the 8 nearest groups.
  - Brightness mix: new-cell lightness remapped rank for rank onto the padding's lightness values. Hue kept.
  - Join fix: Lab difference (padding minus swapped model copy) at each padding spot, smoothed (Gaussian 24 px, normalised), carried out to the nearest value, faded by exp(-distance / 200 px) from the padding.
  - Snap: every new pixel -> nearest of 256 padding colours (k-means in Lab, seeded; kept per padding for the life of the process).
  - Speed settings: join fix smoothed / filled at 1/4 size (`JOIN_SCALE`), fade full size; brightness mix ranks in 1/16 L steps (`LIGHTNESS_BINS`).
- Background vs art (`footprint.background`): dark (RGB sum <= threshold) counts as background only when joined (4-neighbour) to the canvas edge or to the black outside the shape. Dark enclosed by paint is art. Used by: footprint IoU, cut IoU, coverage, the pink overlay (world levels pass `enclosed_is_art=True`; interiors keep the old rule), and colour align (what is written, which pairs, the palette).
- Shape fit (`shape_fit.py`, page: yellow outline, pink holes, "Holes after a cut", Fit shape): holes = new-cell pixels the picture leaves unpainted after the offset shift. Best = fewest holes, 1/4-size search +-40 px then +-4 px full size, ~2 s.
- Scoring a colour method: learn on half the padding (64 px checkerboard blocks), score on the other half. Error per pixel, error per 16 px chunk (Lab), brightness spread vs padding (1 = same), brightness mix gap. Script pattern: scratch `colour_test.py` (not kept).

## Known errors
- Model drift: same input and prompt, the return moves or redraws the padding. Level 06: attempt 1 at (0,0); 6, 7, 14, 16 within 1-4 px; most others no match up to 24 px (edge correlation). Small shifts: drag the offset. Large / redrawn: regenerate.
- Pixel-for-pixel colour cannot match: the model's details are not where the padding's are. Best per-pixel Lab error on held-out padding ~23 (untouched 32).
- Swap alone greys the new cell: mismatched pairs pull each group's median to the middle. Level 06 attempt 1: spread 23.4 vs padding 26.6. Fixed by the brightness mix in match.
- Line at the join that feather never removed (level 06 attempt 1, match + feather 40): align corrected only the new side; the feather faded the padding into the model's uncorrected pixels under it. Top join 1 px each side: 43.6 | 49.7. Fix 2026-11-13: correct the pixels under the padding too -> 49.9 | 49.8 (left join 33.7 | 39.1 -> 38.7 | 39.0). Also changes swap + feather output (swap no longer reproduces old feathered files). Root cause: align chose where to write from masks, and feather silently depended on that choice. Then made align write every drawn pixel (see Log).
- Black fringe inside the shape: the input is pure black outside the shape; the model copies that edge a little off (IoU 0.98-0.99), leaving black joined to the shape edge. Cut cannot fill it. Level 13: 41,468 px; 07: 19,242. Passed on as neighbours' padding (13 -> 19: 7,548). In the stitched world it sits on the coast (13, 07, 03, 18: all joined to the outer black), so the map is usable. An offset shift can drag the model's black canvas border in (19 at (-17, 5): 16,031 holes; at (0, 0): 0). Check holes on the page before Re-place.
- Dark art counted as missing: IoU, cut IoU, coverage and the pink overlay counted every dark pixel inside the shape as unpainted (21: 22,850 "missing", 0 real; 22: 19,886 -> 207; 06: 73,741 -> 12,827). Fixed 2026-11-15: `footprint.background`. Align skipped the same pixels (left them pure black); same fix.
- Alpha 254 along feathered joins: the blend was cast down (254.99998 -> 254), 9-16k px per feathered level, RGB up to 1 step darker. Invisible; reaches neighbours' padding and the model input (21: 141 px). Fixed 2026-11-15: rounded. Already-accepted levels keep theirs.
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
- 2026-11-13: feather is applied where it should be (ramp 40 px each side of the join, masks binary, no gap or overlap). Cut does not touch the join (generation mask covers all the padding).
- 2026-11-13: align writes every drawn pixel instead of new cell + under padding. Level 06 attempt 1, old vs new placement, pixel by pixel: cut + feather 40 (match and swap), cut + feather 0 -> 0 px differ; no cut + feather 40, no cut + padding none -> 58,407 px differ, all outside both new cell and padding (scrap the model drew past the level), 0 in the new cell or padding. Script: scratch `scope_compare.py` (not kept).
- 2026-11-14: align time, level 06 attempt 1 (cProfile, ingest with cut + align + feather 40): 32 s in align = palette 10.6 (k-means 7.0), brightness mix 7.8 (searchsorted 4.3, interp 2.7), join fix 7.7, rest ~5.
- 2026-11-14: after palette kept + join fix at 1/4 + brightness in 1/16 steps, old vs new placement pixel by pixel (5 settings): match cases 32,873-39,167 px differ (of 4.2 M new), Lab difference mean 0.06, 99th percentile 0, max 17-27 (single pixels flipping to the next palette colour); swap 0 px differ. Align ingest 36 s -> 8 s (palette known) / 15-22 s (first per level). Script: scratch `speed_compare.py` (not kept).
- 2026-11-15: run audit, levels 01-22 (read only): no pixel with alpha < 254 anywhere. World stitched from cores (21 levels): black in cores 13: 29,394, 06: 24,345, 07: 12,019, 03: 9,345, 18: 4,327; all joined to the outer black except 06 (20,719 inland = dark art at a cliff base, by eye), 05 / 21 (~2k inland, small dark details). Looks fine at 1/8 by eye.
- 2026-11-15: shape fit on accepted attempts (holes at used offset -> best): 06 8,880 -> 500 at (-40, 18) (search edge); 07 19,242 -> 3,680 at (9, 7); 13 42,643 -> 19,404 at (-1, 40) (search edge: land drawn too small); 18 8,578 -> 1 at (19, 0); 19 16,031 at (-17, 5), 0 at (0, 0); 20-22 ~0.
- 2026-11-15: background rule in align, held-out score (learn on half the padding blocks, attempt 1, offset 0), old -> new: 06 px 26.1 -> 25.5, chunk 13.9 -> 13.4; 21 47.3 -> 47.5, 21.8 -> 21.9; 22 49.5 -> 49.6, 31.3 -> 31.3; 19 41.2 -> 43.4 (pairs 17 px off at offset 0, not a fair test). Neutral. Enclosed dark in 06's new cell: 20,938 px left pure black before, 2 now. Whole new cell moves Lab mean 3.7 (dark pairs now learned from). Without align, only the feather strip changes (rounding, mean 1.1). Scripts: scratch `heldout.py`, `rule_compare.py` (not kept).
- 2026-11-13: by eye (labelled crops, top and left joins): match brighter and with more contrast, closer to the padding; join line still visible without feather.

## Tried and dropped
- Single Lab offset (`lab_offset`, previous agent): seam step 7.11 / 3.70 / 0.83 / 3.68 at strength 0.25 / 0.5 / 0.75 / 1.0. Unverified numbers. One shift for everything, so it cannot fix contrast.
- Full-palette quantile match (`full_palette`, previous agent): seam step 1.99 / 6.45 / 12.61 at 0.5 / 0.75 / 1.0. Unverified. Dropped as worse at full strength. Differs from the brightness mix: that matches L only, after the swap, hue kept.
- Paired colour map (`paired_colour_map`, previous agent): 4.74 / 1.69 / 1.88 / 4.96 at 0.5 / 0.75 / 1.0 / 1.25. Became "swap".
- Clean pairs (keep pairs whose 9x9 lightness correlation > 0.5; 113,571 of 315,780): no gain (chunk err 14.7 vs 14.4). Dropped.
