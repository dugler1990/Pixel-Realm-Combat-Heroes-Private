#!/usr/bin/env bash
# Compress a PNG down as small as possible (great for pixel art).
# Usage: ./compress_png.sh /path/to/map.png
set -euo pipefail

IN="${1:-/home/fresh/projects/Pixel-Realm-Combat-Heroes-public/levels/Frostreach/ice_wall_gate/map.png}"
OUT="${IN%.png}_small.png"

if [ ! -f "$IN" ]; then
  echo "File not found: $IN" >&2
  exit 1
fi

before=$(du -h "$IN" | cut -f1)
echo "Input: $IN ($before)"

# 1) pngquant — best for pixel art (palette reduction, near-lossless look)
if command -v pngquant >/dev/null 2>&1; then
  echo "Using pngquant..."
  pngquant --force --quality=40-90 --speed 1 --output "$OUT" "$IN" || \
  pngquant --force 256 --speed 1 --output "$OUT" "$IN"

# 2) oxipng — lossless, strong
elif command -v oxipng >/dev/null 2>&1; then
  echo "Using oxipng (lossless)..."
  cp "$IN" "$OUT"
  oxipng -o max --strip all "$OUT"

# 3) optipng — lossless fallback
elif command -v optipng >/dev/null 2>&1; then
  echo "Using optipng (lossless)..."
  cp "$IN" "$OUT"
  optipng -o7 -strip all "$OUT"

# 4) Pillow fallback — quantize to a palette in pure Python
else
  echo "No CLI tools found; falling back to Python/Pillow palette quantization..."
  python3 - "$IN" "$OUT" <<'PY'
import sys
from PIL import Image
inp, outp = sys.argv[1], sys.argv[2]
im = Image.open(inp)
has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
if has_alpha:
    im = im.convert("RGBA")
    # Quantize while preserving alpha
    q = im.convert("RGB").quantize(colors=256, method=Image.FASTOCTREE)
    q.save(outp, optimize=True)
else:
    im.convert("RGB").quantize(colors=256, method=Image.FASTOCTREE).save(outp, optimize=True)
PY
fi

after=$(du -h "$OUT" | cut -f1)
echo "Done -> $OUT ($after)"
