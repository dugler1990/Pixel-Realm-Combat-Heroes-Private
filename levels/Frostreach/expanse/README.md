# Frostreach Expanse (bootstrap prototype)

Playable prototype generated from the Frostreach expanse concept PNG via
`tools/painted_map_pipeline/bootstrap_from_png.py`.

- **Level select:** level 10 (grid slot 0,4 if a level thumbnail exists)
- **Map:** 10×7 tiles @ 550px (5500×3850 world px)
- **Background:** `PaintedGround` object layer (visual only)
- **Gameplay:** north ice-wall collision, water tiles, spawners, grass, slippery zones

Regenerate:

```bash
python -m tools.painted_map_pipeline.bootstrap_from_png
```

Use `--width-tiles` / `--height-tiles` for a larger map (30×20 is slow to upscale).
