#!/bin/bash
# One block -> one contact sheet + one labelled reel.   make_block.sh <tag> <regex>
# Both outputs, every time: the sheet is for scanning sixty cells at once, the reel is for
# seeing whether the motion is actually any good. One without the other has been useless.
set -u
S="$(cd "$(dirname "$0")" && pwd)"
B="C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"
TAG="$1"; PAT="$2"
cd "$S" || exit 1
mkdir -p "report/$TAG" "reel/$TAG" out
"$B" -b -noaudio --python block_report.py -- kruns "report/$TAG" "$PAT" 2>&1 | grep -E "^row|^SHEET|Traceback|Error"
"$B" -b -noaudio --python cell_reel.py   -- kruns "reel/$TAG" manifest.json "$PAT" 2>&1 | grep -E "^reel|^CELLS|Traceback|Error"
python block_reel.py "reel/$TAG" "out/${TAG}.mp4" 15 2>&1 | tail -2
cp "report/$TAG/SHEET.png" "out/${TAG}_sheet.png" 2>/dev/null
echo "BLOCK_DONE $TAG"
