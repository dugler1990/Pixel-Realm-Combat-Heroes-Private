#!/usr/bin/env bash
# Export chest hit/open strips from one Aseprite file into the same tree as
# levels/tmx/env_interactable_profiles.json (Graphics/EnvInteractables/chests/...).
#
# Usage:
#   bash aseprite_animation_export.sh [FILE.aseprite] [OUTPUT_BASE] [SUBPATH]
#
# Defaults (paths relative to this script’s directory):
#   FILE         -> <repo>/Chests.aseprite
#   OUTPUT_BASE  -> <repo>/Graphics/EnvInteractables/chests
#   SUBPATH      -> (empty)  → writes e.g. gold/snow/hit/000.png
#
# Override Aseprite binary: export ASEPRITE=/path/to/aseprite
#
# Example (all defaults, run from anywhere):
#   bash /path/to/repo/aseprite_animation_export.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASEPRITE="${ASEPRITE:-/home/fresh/Downloads/aseprite/aseprite/build/bin/aseprite}"

DEFAULT_FILE="${SCRIPT_DIR}/Chests.aseprite"
DEFAULT_OUT="${SCRIPT_DIR}/Graphics/EnvInteractables/chests"

FILE="${1:-$DEFAULT_FILE}"
BASE_OUT="${2:-$DEFAULT_OUT}"
SUB_PATH="${3:-}"

if [[ ! -f "$ASEPRITE" ]]; then
  echo "aseprite not found: $ASEPRITE (set ASEPRITE=...)" >&2
  exit 1
fi
if [[ ! -f "$FILE" ]]; then
  echo "Sprite file not found: $FILE" >&2
  echo "Usage: $0 [CHESTS.aseprite] [OUTPUT_BASE] [SUBPATH]" >&2
  exit 1
fi

OUTPUT_ROOT="$BASE_OUT"
if [[ -n "$SUB_PATH" ]]; then
  OUTPUT_ROOT="${BASE_OUT}/${SUB_PATH}"
fi

declare -A CHEST_HIT_RANGES=(
  [wooden]="1,4"
  [metal]="11,14"
  [gold]="21,24"
  [ice]="31,35"
)

declare -A CHEST_OPEN_RANGES=(
  [wooden]="5,10"
  [metal]="15,20"
  [gold]="25,30"
  [ice]="35,40"
)

CHESTS=(wooden metal gold ice)

mkdir -p "$OUTPUT_ROOT"

for CHEST in "${CHESTS[@]}"; do
  HIT_RANGE="${CHEST_HIT_RANGES[$CHEST]}"
  OPEN_RANGE="${CHEST_OPEN_RANGES[$CHEST]}"

  mkdir -p "${OUTPUT_ROOT}/${CHEST}/snow/hit" \
           "${OUTPUT_ROOT}/${CHEST}/default/hit" \
           "${OUTPUT_ROOT}/${CHEST}/snow/open" \
           "${OUTPUT_ROOT}/${CHEST}/default/open"

  # Filters must come before the .aseprite path (Aseprite CLI).

  # Hit - Snow
  "$ASEPRITE" -b \
    --frame-range "$HIT_RANGE" \
    --layer "Shadow" \
    --layer "Main Chest" \
    --layer "Main Snow" \
    --ignore-layer "background" \
    "$FILE" \
    --save-as "${OUTPUT_ROOT}/${CHEST}/snow/hit/{frame000}.png"

  # Hit - No snow (game path: .../default/hit)
  "$ASEPRITE" -b \
    --frame-range "$HIT_RANGE" \
    --layer "Shadow" \
    --layer "Main Chest" \
    --ignore-layer "Main Snow" \
    --ignore-layer "background" \
    "$FILE" \
    --save-as "${OUTPUT_ROOT}/${CHEST}/default/hit/{frame000}.png"

  # Open - Snow
  "$ASEPRITE" -b \
    --frame-range "$OPEN_RANGE" \
    --layer "Shadow" \
    --layer "Main Chest" \
    --layer "Main Snow" \
    --ignore-layer "background" \
    "$FILE" \
    --save-as "${OUTPUT_ROOT}/${CHEST}/snow/open/{frame000}.png"

  # Open - Default (no snow)
  "$ASEPRITE" -b \
    --frame-range "$OPEN_RANGE" \
    --layer "Shadow" \
    --layer "Main Chest" \
    --ignore-layer "Main Snow" \
    --ignore-layer "background" \
    "$FILE" \
    --save-as "${OUTPUT_ROOT}/${CHEST}/default/open/{frame000}.png"

  echo "OK $CHEST"
done

echo "Done -> $OUTPUT_ROOT"
