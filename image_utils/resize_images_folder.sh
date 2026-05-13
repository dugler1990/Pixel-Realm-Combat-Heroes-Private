#!/bin/bash
# Recursively resize all PNGs under ROOT (default: current directory) to 64x64 — same as resize_images.sh (64x64! ignores aspect ratio).
ROOT="${1:-.}"

find "$ROOT" -type f -iname "*.png" -exec bash -c '
for f in "$@"; do
  echo "Resizing $f to 64x64 pixels..."
  convert "$f" -resize 64x64\! "$f"
done
' _ {} +

echo "All images have been resized."
