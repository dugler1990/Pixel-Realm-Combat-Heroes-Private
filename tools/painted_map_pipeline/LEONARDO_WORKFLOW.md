# Leonardo AI — Expanse Export Polish

Polish exported `PaintedGround` grid PNGs with **Nano Banana 2** (Leonardo v2 API) using image reference.

## API key

Set your Leonardo API key as an **environment variable** (not in the JSON config file):

```bash
export LEONARDO_API_KEY='your-key-here'
```

Add that to your shell profile (`~/.bashrc`, `~/.zshrc`) or run it in the terminal before polishing.

The config key `api_key_env` defaults to `LEONARDO_API_KEY`. To use a different variable name:

```json
"api_key_env": "MY_LEONARDO_KEY"
```

Get a key from [Leonardo.Ai API settings](https://app.leonardo.ai/settings).

## Prerequisites

- `LEONARDO_API_KEY` exported in your shell
- Exported 4K grid folder, e.g. `levels/Frostreach/expanse/export/painted_4k/`

## Workflow

```text
map.tmx PaintedGround
  → export_painted_grid.py (--chunk-width 5056 --chunk-height 3392)
  → painted_4k/
  → polish_export_grid.py (leonardo.config.example.json)
  → painted_4k_leonardo/
```

### 1. Export chunks at Leonardo 4K size (3:2)

```bash
python -m tools.painted_map_pipeline.export_painted_grid \
  --map levels/Frostreach/expanse/map.tmx \
  --output levels/Frostreach/expanse/export/painted_4k \
  --chunk-width 5056 \
  --chunk-height 3392
```

Grid columns/rows are computed from the PaintedGround rect (~7×7 for Frostreach expanse).

### 2. Polish with Nano Banana 2

```bash
export LEONARDO_API_KEY='your-key-here'

python -m tools.painted_map_pipeline.polish_export_grid \
  --input-dir levels/Frostreach/expanse/export/painted_4k \
  --output-dir levels/Frostreach/expanse/export/painted_4k_leonardo \
  --config tools/painted_map_pipeline/leonardo.config.example.json \
  --prompt-file tools/painted_map_pipeline/frostreach_polish_prompt.txt
```

Dry-run (no API calls):

```bash
python -m tools.painted_map_pipeline.polish_export_grid \
  --input-dir levels/Frostreach/expanse/export/painted_4k \
  --output-dir levels/Frostreach/expanse/export/painted_4k_leonardo \
  --dry-run
```

Single chunk:

```bash
python -m tools.painted_map_pipeline.polish_export_grid \
  --input-dir levels/Frostreach/expanse/export/painted_4k \
  --output-dir levels/Frostreach/expanse/export/painted_4k_leonardo \
  --chunk-id chunk_00_00
```

### 3. Insert into map.tmx

```bash
python -m tools.painted_map_pipeline.insert_polished_grid \
  --grid-manifest levels/Frostreach/expanse/export/painted_4k/grid_manifest.json \
  --polished-dir levels/Frostreach/expanse/export/painted_4k_leonardo \
  --tmx levels/Frostreach/expanse/map.tmx
```

Edge cells are exported as full **5056×3392** tiles with **black padding** outside the map (`--no-pad-to-chunk-size` disables this). Re-polish padded edges with `--edge-prompt-file` (interior chunks can use `--preserve-existing`).

## What it does

1. Reads `grid_manifest.json` (or globs `chunk_*.png`) from the input folder
2. Resizes each chunk reference to **5056×3392** and compresses to **≤10MB JPEG** for upload
3. Generates with **Nano Banana 2** at **5056×3392** (4K 3:2 pair) with **HIGH** image reference
4. Writes output at native generation size (**no upscale** when `preserve_native_resolution` is true)
5. Writes polished PNGs plus per-chunk `context/image_result.json` and `leonardo_summary.json`

Original exports are never modified.

## Config

Copy [`leonardo.config.example.json`](leonardo.config.example.json) and adjust:

| Key | Purpose |
|-----|---------|
| `api_key_env` | Env var name for your API key (default `LEONARDO_API_KEY`) |
| `api_version` | `v2` for Nano Banana 2 |
| `model` | `nano-banana-2` |
| `width` / `height` | **5056×3392** (4K 3:2 — must be a valid Leonardo pair) |
| `reference_strength` | `LOW` / `MID` / `HIGH` (layout lock — start with `HIGH`) |
| `prompt_enhance` | `OFF` (keep your strict layout prompt) |
| `style_ids` | Preset style UUIDs (`Game Concept` by default) |
| `preserve_native_resolution` | `true` — do not upscale to old manifest sizes |
| `max_upload_bytes` | **10485760** (10MB upload cap) |
| `reference_jpeg_quality` | Starting JPEG quality for reference upload (default 90) |
| `preserve_existing` | Skip chunks that already have output PNGs |

## Legacy v1 (Lucid Origin @ 1536)

For older experiments only, use v1 keys: `base_url` v1, `model_id`, `preprocessor_id` 430, `max_gen_size` 1536, and set `preserve_native_resolution` to `false`.
