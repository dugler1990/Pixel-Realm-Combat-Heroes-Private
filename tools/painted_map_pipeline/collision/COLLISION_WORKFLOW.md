# Collision trial workflow

## Leonardo direct only (recommended)

Painted chunk → Leonardo flat segmentation. **No mechanical preprocessing.**

```bash
export LEONARDO_API_KEY='...'

python -m tools.painted_map_pipeline.collision.run_leonardo_direct \
  --chunk chunk_06_06 \
  --preview-map
```

Output: `levels/Frostreach/expanse/export/collision_trial/chunk_06_06/leonardo_direct/`

Re-parse an existing API result without spending credits:

```bash
python -m tools.painted_map_pipeline.collision.run_leonardo_direct \
  --chunk chunk_06_06 --from-raw --preview-map
```

## What changed

- Mechanical **128px block grid removed** (back to 64px for optional local preview only — never sent to AI)
- Leonardo parses at **native generation size**, then upscales masks (not blurry LANCZOS on flat colors)
- Prompt asks for **smooth organic walkable regions**, not blocky grids
- Default test runner is **Leonardo direct only** (no hint mode unless `--all`)

## Optional mechanical preview

```bash
python -m tools.painted_map_pipeline.collision.run_collision_tests \
  --chunk chunk_06_06 --mechanical-only --preview-map
```

## Merge when happy

```bash
python -m tools.painted_map_pipeline.collision.merge_fragment \
  --map levels/Frostreach/expanse/map.tmx \
  --fragment levels/Frostreach/expanse/export/collision_trial/chunk_06_06/leonardo_direct/collision_layer.fragment.xml
```

## Roboflow Custom Workflow (obstacle polygons)

Calls your saved Roboflow workflow (`custom-workflow` on workspace `douglass-workspace-y1brz`) — same pipeline as the UI. Full-resolution PNG in, polygon overlay + coordinates out.

```bash
export ROBOFLOW_API_KEY='...'
pip install inference-sdk

# Probe one chunk (inspect response shape first)
python -m tools.painted_map_pipeline.collision.sam3.run_workflow_chunk \
  --chunk chunk_06_06 --probe

# One chunk (full output)
python -m tools.painted_map_pipeline.collision.sam3.run_workflow_chunk --chunk chunk_06_06

# All 49 chunks, sequential
python -m tools.painted_map_pipeline.collision.sam3.run_workflow_all

# Force rerun (ignore existing polygons.json)
python -m tools.painted_map_pipeline.collision.sam3.run_workflow_all --no-preserve-existing

# Build map.tmx (PaintedGround + Objects)
python -m tools.painted_map_pipeline.collision.sam3.build_sam3_map
```

**Full rebuild** (`build_sam3_map`) wipes the map shell first — use only for from-scratch rebuilds.

### Layer naming (object groups)

| Layer name | Role |
|------------|------|
| `PaintedGround` | Visual painted chunks only |
| `Objects` | Blocking geometry (SAM3 polygons or image objects) |
| `Object Layer 1` | Same as `Objects` (legacy tmx map) |
| `ObstaclePolygons` / `PaintedCollision` | Aliases → `Objects` |
| `Heat Effect Layer`, `Slipery Layer`, `*Effect*` | Gameplay effect zones |
| `spawner`, `grass1`, `Interactables`, RTS layers | Unchanged special roles |

### Coordinate contract (SAM3 merge)

- Polygon placement uses **`world_rect` top-left** from the insert manifest (chunk PNG origin).
- Do **not** infer placement from PaintedGround gid Y in the TMX — those use Tiled bottom-anchor Y.

### First-time reconstruction (expanse)

If `map.tmx` already has `PaintedGround` and bad obstacle data, **merge only**:

```bash
python -m tools.painted_map_pipeline.collision.sam3.merge_polygon_obstacles \
  --map levels/Frostreach/expanse/map.tmx \
  --manifest levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json \
  --sam3-root levels/Frostreach/expanse/export/sam3_obstacle \
  --layer-name Objects
```

Removes legacy `ObstaclePolygons` / old `Objects` and writes a fresh `Objects` layer. Sanity check: tree at image y≈33 in `chunk_00_00` → TMX y≈111 (`78+33`), not ~3500.

Legacy aliases still work: `run_sam3_chunk`, `run_sam3_all`.

Output per chunk: `levels/Frostreach/expanse/export/sam3_obstacle/chunk_XX_YY/` (`workflow_response.json`, `polygons.json`, `overlay_preview.png`).

Config: [`sam3/sam3.config.example.json`](sam3/sam3.config.example.json) — `workspace_name`, `workflow_id`, `input_name`. SAM3 keywords/threshold live in the Roboflow UI workflow, not here.
