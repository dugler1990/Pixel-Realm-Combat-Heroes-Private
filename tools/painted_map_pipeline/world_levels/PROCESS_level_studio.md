# Level studio

## Method
- Launch (repo root, PowerShell):
  `Code\sprite_venv\Scripts\python.exe -m tools.painted_map_pipeline.world_levels.studio_page [--port 8766] [--no-browser]`
- Opens `http://127.0.0.1:8766/`. Port 8765 is SAM, 8767 is outfits. The top bar links to them; this server does not run them.
- The cell-review command is unchanged:
  `python -m tools.painted_map_pipeline.world_levels.review_page <run_root>`
- One command at a time, shared with the review page on this server. The page and `review_run` still must not be used on the same run at once.
- Steps, in order:
  1. Source. A run under `generated/world_levels/` and a level that has `accepted/image.png`. Names come from that run's plan, else `levels/Frostreach/proposed_25_level_areas.csv`. The world-map PNG is a locator. The image that is recomposed is the accepted region.
  2. Compose. `compose_level` on that image, same pixel size, gpt-image-2, quality low / medium / high. The prompt is ASCII and is what keeps the outline. Player height defaults to 8, and the scale note uses that height. Accept copies one attempt to `composed/composed.png`. Model and quality are sent for that call only; `config.json` is not rewritten.
  3. Scale and grid. Source is `composed/composed.png` when it exists, otherwise the accepted image.
     - Scale preset: 33 by 18 tiles, tile 681, which is 22473 by 12258. `bootstrap_level` writes `generated/world_levels/<name>/scale/`. The `map.tmx` in that folder is the bootstrap shell, not the playable level.
     - Snap. The slow step, a few minutes on a full-size map. Writes `background_snapped.png` and the landmass polygon.
     - Grid preset: 7 by 6. Writes `plan.csv`, `plan_overlay.png`, and the canvas size.
     - Prepare. Writes `config.json` (scale 1, explicit canvas, gpt-image-2, warp) and runs `prepare_run`. Nothing is prepared until this button. The cell pass sharpens; its style prompt says not to invent.
  4. Cell review. Opens the existing review page at `/review` on that run. Steps link returns here.
- `OPENAI_API_KEY` is read from the environment. The page shows whether it is set, never the value.
- Tests: `Code\sprite_venv\Scripts\python.exe -m pytest tests/painted_map_pipeline/test_studio.py`
- A real compose is a button press. The tests do not call the API.

## Known errors
- Prompt with a non-ASCII character: the image call rejects it. Retype the prompt in ASCII.
- Scale into a folder that is already a generation run (it has accepted levels and no `studio.json`): refused. Pick a new folder name.
- Snap before Scale, grid before Snap, prepare before the grid: each says which step is missing.
- Page and `review_run` on the same prepared run: both write `run.json`. Use one.

## Log
- 2026-11-17: built on `feat/level-studio`, from `feat/level-review-fit`. Compose, scale, snap, grid and prepare are buttons on one server. The review screen is the existing page.
- 2026-11-17: `test_studio.py` 5 passed (fake image, no API call). `test_compose.py` and `test_review_web.py` still pass: 26 together.
