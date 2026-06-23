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
