# Heightmap workflow (Sunspine SAM chunks)

Image-model DEM from each chunk’s `source.png`, through the existing `ImageClient` (Leonardo). Not Cursor GenerateImage. Not a second API client.

Do **not** import `Code/terrain_height.py` from this package (`Settings.py` changes cwd on import). Void thresholds are duplicated in `heightmap/align.py`; `tests/test_terrain_height.py` asserts they match.

## API key

```bash
export LEONARDO_API_KEY='your-key-here'
```

Config: `tools/painted_map_pipeline/heightmap.sunspine.json`

- `reference_strength: HIGH`, `prompt_enhance: OFF`
- **No `style_ids`** (a painterly style fights an untextured DEM)
- Gen size `5056×3448` matches source AR (~1.466). If Leonardo rejects that size, set `5056×3392` and rely on QC.

## Probe, then batch

One draw is not enough. Judge with the QC numbers in `heightmap_result.json`, not by eye. Do not run `run_all` until those scores hold. `LEONARDO_API_KEY` must be in the shell; without it the runner cannot probe.

```bash
# Attempt 1–3 on chunk_00_02 only (does not write chunk heightmap.png)
python -m tools.painted_map_pipeline.heightmap.run_chunk \
  --chunk chunk_00_02 \
  --attempt 1 \
  --manifest levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json \
  --config tools/painted_map_pipeline/heightmap.sunspine.json

python -m tools.painted_map_pipeline.heightmap.run_chunk \
  --chunk chunk_00_02 --attempt 2 \
  --manifest levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json \
  --config tools/painted_map_pipeline/heightmap.sunspine.json

python -m tools.painted_map_pipeline.heightmap.run_chunk \
  --chunk chunk_00_02 --attempt 3 \
  --manifest levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json \
  --config tools/painted_map_pipeline/heightmap.sunspine.json
```

Each attempt lands in `export/sam3_chunks/chunk_00_02/heightmap_attempts/NN/`:

- `heightmap_raw.png` — model output
- `heightmap.png` — LANCZOS-resized to `source.png`
- `heightmap_preview.png` — side-by-side; void punched for viewing only
- `heightmap_result.json` — API payload plus `qc.dx`, `qc.dy`, `qc.response`, `qc.ok`

QC fails if `|dx|` or `|dy|` > `qc_max_shift_px` (8) or `response` < `qc_min_response` (0.015). Copy the best attempt onto the chunk with `--attempt N --promote` (only if that attempt’s `qc.ok` is true).

`chunk_00_01/heightmap.png` is the existing one-shot. Default `preserve_existing` leaves it alone.

Only after 00_02 QC looks trustworthy:

```bash
python -m tools.painted_map_pipeline.heightmap.run_all \
  --manifest levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json \
  --config tools/painted_map_pipeline/heightmap.sunspine.json
```

A failed QC on one chunk does not stop the batch. Hand-edit `heightmap.png` in place if a face is wrong.

## Cheap cost bakeoff

Before paying for full-size `nano-banana-2` at 5056×3448, run the cheap variants on **one** unused chunk (`chunk_00_02`). Each lands in `export/heightmap_cost/<variant>/` with its own `heightmap.png`, preview, and API dump. `cost.tsv` plus `contact_sheet.png` sit in the folder root. This does **not** write `chunk_00_01/heightmap.png`.

```bash
export LEONARDO_API_KEY='...'   # lite / flash / small banana
export OPENAI_API_KEY='...'     # gpt-image-2 quality=low (optional)

python -m tools.painted_map_pipeline.heightmap.run_cost --dry-run

python -m tools.painted_map_pipeline.heightmap.run_cost
```

Leonardo tries `nano-banana-2-lite` at 1376×928 first, then flash, then a small `nano-banana-2`. OpenAI uses `quality=low` at 1024×704. Phoenix is off unless you pass `--include-risky`. Re-runs skip a variant folder that already has `heightmap.png`; `--force` spends again.

## Runtime

The game still loads **only** `chunk_00_01`. Other chunks’ maps sit unused until a later multi-rect bind.
