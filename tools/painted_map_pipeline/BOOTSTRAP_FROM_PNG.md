# Bootstrap a level from a single PNG

When you only have a concept / generated map image (no outline TMX):

```bash
python -m tools.painted_map_pipeline.bootstrap_from_png \
  --source-png /path/to/concept.png \
  --level-dir ../../levels/Frostreach/my_level \
  --width-tiles 10 \
  --height-tiles 7
```

This writes:

- `map.tmx` — playable map with `PaintedGround` + gameplay shell
- `background.png` — upscaled art
- `shell_outline.tmx` — gameplay-only source (no painted layer)

The shell includes tile terrain, north-wall obstacles, spawners, grass zones, and slippery ice areas. Open `map.tmx` in Tiled to polish collision and add RTS layers from `levels/tmx/map.tmx` as needed.

**Note:** 30×20 @ 550px upscales to 16500×11000 and is slow; start with 10×7 for iteration.
