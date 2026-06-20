# Level Art Workflow

This workflow separates broad design references, playable TMX layout, generated art attempts, and the final playable map.

## Stages

1. World / realm reference
   - A broad map image establishes continents, biomes, borders, and landmarks.
   - Store these references under a stable project path when they are accepted.
   - Do not load this directly in game.

2. Region brief
   - Pick a specific region from the world reference.
   - Record the region name, intended exits, landmarks, biome, and gameplay goals in the level manifest.

3. Simple outline TMX
   - Author a simple gameplay-first TMX.
   - For Frostreach Ice Wall Gate this is:
     `levels/Frostreach/ice_wall_gate/siple_map_outlin.tmx`
   - This file is the source of truth for gameplay layout and generated art context.

4. Painted chunk run
   - Render the outline TMX.
   - Split the rendered map into fixed world rectangles.
   - Generate one polished image per rectangle.
   - Keep all run artifacts under `generated/painted/<level_slug>/`.
   - Keep visual previews such as `assembled_preview.png` with the run.

5. Final playable TMX
   - The playable level TMX should be named:
     `levels/<region>/<level>/map.tmx`
   - The final TMX contains a visual-only `PaintedGround` object layer.
   - Gameplay layers remain authored in the outline/source TMX and are copied into the final TMX.

## File Naming Rules

- `siple_map_outlin.tmx`: simple source/layout TMX. Keep this stable for reruns.
- `map.tmx`: final playable TMX loaded by the game.
- `map_painted.tmx`: temporary/debug output only; do not treat as canonical.
- `painted_chunks.tsx`: generated tileset for the final painted images.
- `generated/painted/<level_slug>/chunks/<chunk_id>/source.png`: context/source crop.
- `generated/painted/<level_slug>/chunks/<chunk_id>/painted.png`: accepted generated image for that chunk.
- `generated/painted/<level_slug>/assembled_preview.png`: visual proof of the assembled chunks.

## Current Frostreach Command

```bash
python -m tools.painted_map_pipeline.pipeline \
  tools/painted_map_pipeline/frostreach_ice_wall_gate.json
```

For the current accepted clean run, rerun insertion without regenerating images:

```bash
python - <<'PY'
from tools.painted_map_pipeline.insert_chunks import insert_painted_chunks
insert_painted_chunks(
    'levels/Frostreach/ice_wall_gate/siple_map_outlin.tmx',
    'generated/painted/frostreach_ice_wall_gate_clean/chunks/chunks_manifest.json',
    'levels/Frostreach/ice_wall_gate/map.tmx',
)
PY
```

## Validation Rule

Do not call a run complete unless:

- The assembled preview shows the full map covered by the expected chunk grid.
- The final `map.tmx` opens in Tiled with all chunks aligned.
- `pytmx` loads the `PaintedGround` layer with the expected image count.
- The level manifest points at the source outline, final TMX, generated output folder, and region/world references.

## Second Polish Pass

The same process can be run again using the current painted output as context:

1. Treat the accepted painted chunks or assembled preview as the new visual reference.
2. Generate improved versions of the same chunk rectangles.
3. Save the new attempt under a new output folder, for example:
   `generated/painted/frostreach_ice_wall_gate_polish_02/`
4. Reinsert accepted chunks into `map.tmx`.
5. Keep the previous run folder for comparison until the new pass is accepted.

## Seam Repair Pass

Use a seam repair pass when the six generated chunks are broadly acceptable but roads, rivers, cliffs, or texture details do not line up at chunk boundaries.

Fix semantic continuity first. A broken road, river, bridge, or cliff edge is not a texture problem; it is a feature that must be redrawn so the visible endpoints connect. Texture polish should only happen after those features read correctly.

### Issue-First Seam Repair

Before generating or applying any fix patch, inventory the visible seam problems in a pass-level issue registry.

```bash
python -m tools.painted_map_pipeline.seam_issues init \
  --manifest generated/painted/frostreach_ice_wall_gate_clean/chunks/chunks_manifest.json \
  --pass-dir generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_04
```

Add agent-assessed or user-defined issues:

```bash
python -m tools.painted_map_pipeline.seam_issues add \
  --pass-dir generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_04 \
  --issue-id road_001 \
  --feature-type road \
  --priority high \
  --boundary x=5500 \
  --rect 4300,3000,2400,1700 \
  --connections west_to_east \
  --problem "Grey road reaches the seam but does not continue into the neighboring chunk." \
  --expected-fix "Reconnect the grey road across the vertical seam as one walkable route."
```

Review the annotated map:

```bash
python -m tools.painted_map_pipeline.seam_issues render-review \
  --pass-dir generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_04
```

Create a patch for one issue:

```bash
python -m tools.painted_map_pipeline.seam_issues make-patch \
  --pass-dir generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_04 \
  --issue-id road_001
```

Update issue status as work progresses:

```bash
python -m tools.painted_map_pipeline.seam_issues status \
  --pass-dir generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_04 \
  --issue-id road_001 \
  --status accepted
```

Each pass keeps:

```text
assembled_before.png
issues.json
issue_review.png
pass_summary.md
patches/<issue_id>_attempt_XX/
backups/
outputs/
```

Issue statuses:

```text
open
context_ready
fix_generated
applied
accepted
rejected
needs_retry
```

Process one issue at a time. Do not apply fixes until the issue is logged, the patch crop is reviewed, and the patch-local comparison looks correct.

### Build Diagnostic Preview

```bash
python -m tools.painted_map_pipeline.assemble_preview \
  --manifest generated/painted/frostreach_ice_wall_gate_clean/chunks/chunks_manifest.json \
  --output generated/painted/frostreach_ice_wall_gate_clean/assembled_preview.png \
  --max-width 1800 \
  --grid \
  --labels
```

### Create Seam Contexts

```bash
python -m tools.painted_map_pipeline.make_seam_contexts \
  --manifest generated/painted/frostreach_ice_wall_gate_clean/chunks/chunks_manifest.json \
  --output generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_01 \
  --patch-size 1536
```

For the current `3 x 2` Frostreach grid this creates five patch folders:

```text
vertical_col_0_1
vertical_col_1_2
horizontal_row_0_1
intersection_0_1_row_0_1
intersection_1_2_row_0_1
```

Each patch folder contains:

```text
source.png
source_annotated.png
context_full.png
prompt.txt
metadata.json
```

The agent should use `source.png` as the exact patch to fix, `source_annotated.png` for must-connect endpoints, and `context_full.png` only to understand where the patch sits in the full map.

### Create A Targeted Semantic Patch

For obvious road or walkway breaks, prefer a targeted patch over a full seam strip:

```bash
python -m tools.painted_map_pipeline.make_seam_contexts \
  --manifest generated/painted/frostreach_ice_wall_gate_clean/chunks/chunks_manifest.json \
  --output generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_02 \
  --only-targets \
  --target "id=central_road_y_5500,center=8250:5500,size=2200x1800,goal=connect_walkway,connections=north_to_south,notes=Reconnect the grey walkable road across the horizontal chunk seam"
```

Useful repair goals:

- `connect_walkway`: reconnect roads, bridges, paths, stairs, or other traversable ground.
- `connect_ice_river`: reconnect water/ice flow or shoreline shapes.
- `align_cliff`: reconnect cliff/wall/height edges.
- `blend_texture`: use only after the semantic feature already connects.

### Apply A Fixed Patch

After the agent generates a fixed patch image:

```bash
python -m tools.painted_map_pipeline.apply_seam_patch \
  --manifest generated/painted/frostreach_ice_wall_gate_clean/chunks/chunks_manifest.json \
  --patch-dir generated/painted/frostreach_ice_wall_gate_clean/seam_passes/pass_01/patches/intersection_0_1_row_0_1 \
  --fixed-image /path/to/fixed.png \
  --tmx levels/Frostreach/ice_wall_gate/siple_map_outlin.tmx \
  --output-tmx levels/Frostreach/ice_wall_gate/map.tmx
```

The apply step:

- Backs up current `map.tmx`, `painted_chunks.tsx`, and affected chunk PNGs into the pass folder.
- Writes patched chunk outputs under `outputs/chunks/`.
- Promotes accepted patched chunks back to the canonical `chunks/<chunk_id>/painted.png` files.
- Writes patch-local `before.png`, `fixed.png`, `after.png`, and `comparison.png`.
- Rebuilds `assembled_after.png`.
- Rebuilds canonical `map.tmx`.

By default, the fixed image must exactly match the patch size. If an image tool produced the wrong dimensions, regenerate it. Use `--allow-resize-fixed` only for a deliberate test because resizing can distort precision repairs.

`map.tmx` stays the current playable map, while each `seam_passes/pass_XX/` folder preserves before/after state for recovery and comparison.
