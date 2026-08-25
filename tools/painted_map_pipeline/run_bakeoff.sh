#!/usr/bin/env bash
# Single-chunk bake-off: compare providers/settings on the same chunk, log cost + timing.
#
#   ./tools/painted_map_pipeline/run_bakeoff.sh --leo              # Leonardo variants only
#   ./tools/painted_map_pipeline/run_bakeoff.sh --gpt              # gpt variants only
#   ./tools/painted_map_pipeline/run_bakeoff.sh --all              # both (default)
#   ./tools/painted_map_pipeline/run_bakeoff.sh --leo chunk_04_01  # pick the chunk
#
# Each variant writes to its own output dir and appends a row to export/bakeoff_log.tsv.
# Leonardo reports no per-call price, so note your credit balance before/after.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

WHICH=all
CHUNK=chunk_01_01
for arg in "$@"; do
  case "$arg" in
    --leo|--leonardo) WHICH=leo ;;
    --gpt|--openai)   WHICH=gpt ;;
    --all)            WHICH=all ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) CHUNK="$arg" ;;
  esac
done
LEVEL=levels/Frostreach/sunspine_dunes_01
GRID="$LEVEL/export/painted_grid"
PROMPT=tools/painted_map_pipeline/frostreach_desert_detail_prompt.txt
EDGE=tools/painted_map_pipeline/frostreach_desert_detail_edge_prompt.txt
LOG="$LEVEL/export/bakeoff_log.tsv"
[ -f "$LOG" ] || printf 'when\tstatus\tvariant\tchunk\tseconds\tprovider\tmodel\tquality\tout_tokens\tusd\tout_size\tnote\n' > "$LOG"

run_variant() {   # name, config, extra-json-overrides
  local name="$1" config="$2" overrides="${3:-}"
  local outdir="$LEVEL/export/bakeoff_$name"
  local cfg="$config"
  if [ -n "$overrides" ]; then                     # apply per-variant config tweaks
    cfg="/tmp/bakeoff_$name.json"
    python3 -c "
import json,sys
c=json.load(open('$config')); c.update(json.loads('''$overrides''')); json.dump(c,open('$cfg','w'),indent=1)"
  fi
  echo "=== $name ($CHUNK) ==="
  local t0=$SECONDS
  # Output is shown, not swallowed: a failure must be visible while it happens.
  python -m tools.painted_map_pipeline.polish_export_grid \
    --input-dir "$GRID" --output-dir "$outdir" --config "$cfg" \
    --prompt-file "$PROMPT" --edge-prompt-file "$EDGE" --chunk-id "$CHUNK" \
    | tail -n 3
  local secs=$((SECONDS - t0))
  python3 - "$name" "$outdir" "$CHUNK" "$secs" "$LOG" <<'PY'
import json, os, sys, datetime
name, outdir, chunk, secs, log = sys.argv[1:6]
res = os.path.join(outdir, chunk, "context", "image_result.json")
png = os.path.join(outdir, f"{chunk}.png")
d = json.load(open(res)) if os.path.exists(res) else {}
u = d.get("usage") or {}
ot = u.get("output_tokens", "")
usd = round(u["input_tokens"]/1e6*10 + u["output_tokens"]/1e6*40, 4) if u else ""
if not usd:
    # Leonardo reports the real price on the create response: {'amount': '0.0777', 'unit': 'DOLLARS'}
    cost = ((d.get("create_response") or {}).get("generate") or {}).get("cost") or {}
    if str(cost.get("unit", "")).upper() == "DOLLARS":
        usd = round(float(cost["amount"]), 4)
    elif cost.get("amount"):
        usd = f"{cost['amount']} {cost.get('unit','')}"
size = ""
if os.path.exists(png):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(png) as im: size = f"{im.size[0]}x{im.size[1]}"
ok = os.path.exists(png)
# One short human line, never a raw provider dict; full detail stays in image_result.json.
note = "" if ok else " ".join((d.get("error") or "no output image written").split())[:110]
row = [datetime.datetime.now().strftime("%H:%M:%S"), "OK" if ok else "FAILED", name, chunk,
       secs, d.get("provider", "?"), d.get("model", ""), d.get("quality", ""),
       ot, usd, size, note]
open(log, "a").write("\t".join(str(x) for x in row) + "\n")
print(("  OK    " if ok else "  FAILED ") + f"{secs}s " + (size or "") + ("  " + note if note else ""))
PY
}

if [ "$WHICH" = gpt ] || [ "$WHICH" = all ]; then
  if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "ERROR: gpt variants requested but OPENAI_API_KEY is unset." >&2; exit 1
  fi
  run_variant gpt_medium_fid tools/painted_map_pipeline/openai.gpt-image-2.json '{"quality":"medium","input_fidelity":"high"}'
  run_variant gpt_medium     tools/painted_map_pipeline/openai.gpt-image-2.json '{"quality":"medium"}'
fi
if [ "$WHICH" = leo ] || [ "$WHICH" = all ]; then
  if [ -z "${LEONARDO_API_KEY:-}" ]; then
    echo "ERROR: leonardo variants requested but LEONARDO_API_KEY is unset." >&2; exit 1
  fi
  echo "NOTE: Leonardo reports no per-call price -- check your credit balance before/after."
  run_variant leo_nb2   tools/painted_map_pipeline/leonardo.sunspine.json ''
  run_variant leo_lucid tools/painted_map_pipeline/leonardo.sunspine.json '{"api_version":"v1","base_url":"https://cloud.leonardo.ai/api/rest/v1","model_id":"7b592283-e8a7-4c5a-9ba6-d18c31f258b9"}'
fi

echo
echo "=== $LOG ==="
column -t -s$'\t' "$LOG"
