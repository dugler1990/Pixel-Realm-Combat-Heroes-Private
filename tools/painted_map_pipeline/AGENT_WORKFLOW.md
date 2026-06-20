# Agent Painted Chunk Workflow

This pipeline keeps the image-generation step explicit: code prepares chunk context and reinserts finished images, while an agent or person generates the painted image.

For the full world-map -> region -> outline TMX -> final painted level process, read `LEVEL_ART_WORKFLOW.md` first.

## 1. Prepare Context

Run the normal pipeline in `copy` or `manifest` mode to render the rough TMX, slice chunks, and create context packs:

```bash
python -m tools.painted_map_pipeline.pipeline tools/painted_map_pipeline/frostreach_ice_wall_gate.json
```

Use `"preserve_existing": true` under `image_generation` when rerunning, so existing agent-made `painted.png` files are not replaced by rough copies.

The config separates world/map scale from AI working scale:

```json
"world_chunk_size": [5500, 5500],
"generation_max_size": 1536
```

`world_chunk_size` controls how much of the final TMX map a chunk covers. `generation_max_size` caps generated context images when using the automated prep flow. For the accepted Frostreach clean run, the final chunk images were written at full `5500 x 5500` size so Tiled previews the final `map.tmx` directly.

## 2. Generate One Chunk

For a chosen chunk, read:

```text
generated/painted/frostreach_ice_wall_gate_clean/chunks/<chunk_id>/context/prompt.txt
generated/painted/frostreach_ice_wall_gate_clean/chunks/<chunk_id>/source.png
generated/painted/frostreach_ice_wall_gate_clean/chunks/<chunk_id>/context/chunk_locator.png
generated/painted/frostreach_ice_wall_gate_clean/chunks/<chunk_id>/context/asset_contact_sheet.png
```

Use those files as references for image generation. `local_neighborhood.png` can be enabled for debugging, but it is off by default because neighbor images already provide the continuity context.

`source.png` is a reduced working-scale representation of the exact chunk layout. Neighbor images are for shared-edge continuity only. They should not cause the generated chunk to copy a neighbor's full composition.

Neighbor files are named by direction and status:

```text
neighbor_west_painted.png
neighbor_north_source.png
```

`painted` means a real agent/manual generated output exists. `source` means that neighbor is still rough context.

## 3. Apply The Generated Image

```bash
python -m tools.painted_map_pipeline.apply_painted_chunk \
  --config tools/painted_map_pipeline/frostreach_ice_wall_gate.json \
  --chunk-id chunk_01_00 \
  --generated-image /absolute/path/to/generated.png \
  --insert
```

This writes:

```text
generated/painted/frostreach_ice_wall_gate_clean/chunks/<chunk_id>/painted.png
generated/painted/frostreach_ice_wall_gate_clean/chunks/<chunk_id>/context/image_result.json
levels/Frostreach/ice_wall_gate/map.tmx
levels/Frostreach/ice_wall_gate/painted_chunks.tsx
```

## 4. Refresh Context Before The Next Chunk

After applying a generated chunk, refresh the context packs before generating an adjacent chunk:

```bash
python -m tools.painted_map_pipeline.refresh_context \
  tools/painted_map_pipeline/frostreach_ice_wall_gate.json \
  --chunk-id chunk_02_00
```

Keep `"preserve_existing": true` enabled for full pipeline reruns. The lightweight refresh updates neighbor files so newly painted chunks become `neighbor_<direction>_painted.png` for adjacent chunks without rerendering, reslicing, copying placeholders, or rebuilding the TMX. Use repeated `--chunk-id` flags to refresh only the next chunks you plan to generate.

Do not batch-generate many chunks from stale context. Work outward from a good seed chunk:

```text
chunk_01_00
chunk_00_00, chunk_02_00
chunk_00_01, chunk_01_01, chunk_02_01
```

If two generated chunks look nearly identical despite different source chunks, do not apply them. That means the generator ignored the source/neighbor context and the prompt or references need adjustment.

The `PaintedGround` layer in `map.tmx` is an object layer containing image objects, not a native Tiled image layer. The game loader treats it as visual-only ground; collision, effects, grass, and spawners still come from the normal TMX layers.

## 5. Validate

Open `map.tmx` in Tiled or run a `pytmx` load check. Also check `generated/painted/frostreach_ice_wall_gate_clean/assembled_preview.png` before calling a run complete. For gameplay validation, launch the Frostreach test level and confirm the painted chunk displays while movement/collision still follows the authored gameplay layers.
