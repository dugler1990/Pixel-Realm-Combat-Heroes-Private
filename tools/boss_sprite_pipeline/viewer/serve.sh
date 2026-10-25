#!/bin/bash
# Serve the Boss repo so the viewer can fetch any baked glb. Browsers refuse a cross-origin
# fetch from file://, so the glb has to come over HTTP even though it is right there on disk.
#
#   tools/boss_sprite_pipeline/viewer/serve.sh [port]
#
# Then open the printed URL. Any animated.glb works - pass it with ?glb=<repo-absolute path>.
set -u
PORT="${1:-8777}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
V="/tools/boss_sprite_pipeline/viewer/"
echo "root  $ROOT"
echo "open  http://localhost:$PORT$V?glb=/generated/bosses/demon/animate_best40/animated.glb"
echo
for g in "$ROOT"/generated/bosses/demon/*/animated.glb "$ROOT"/generated/bosses/demon/*/*/animated.glb; do
    [ -f "$g" ] && echo "      http://localhost:$PORT$V?glb=${g#$ROOT}"
done
echo
cd "$ROOT" && exec python -m http.server "$PORT" --bind 127.0.0.1
