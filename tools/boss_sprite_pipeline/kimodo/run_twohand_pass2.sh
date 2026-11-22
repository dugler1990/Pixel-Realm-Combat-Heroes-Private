#!/usr/bin/env bash
# Second pass for the two-handed clips (pod): pin both hands to one grip from each clip's best first-pass sample,
# regenerate with the same prompt and duration, then measure the hand gap. Picks: <cell>:<sample>.
set -uo pipefail
cd /workspace/kimodo_tools
export HF_HOME=/workspace/hf HF_TOKEN=$(cat /workspace/hf/token)
. /workspace/kimodo-venv/bin/activate
mkdir -p /workspace/cons
rm -rf /workspace/runs/*_2h
PICKS="${PICKS:-th_overhead:01 th_side:00 th_idle:01 th_walk:00}"
for c in $PICKS; do
  n=${c%%:*}; s=${c##*:}
  python build_twohand_cons.py /workspace/runs/$n/${n}_$s.npz /workspace/cons/${n}_2h.json 2>&1 | grep -E 'TWOHAND|Error'
done
python - <<'PY'
import json, os
cells = {c['name']: c for c in json.load(open('cells_weapons.json'))}
out = []
for p in os.environ.get('PICKS', 'th_overhead:01 th_side:00 th_idle:01 th_walk:00').split():
    n = p.split(':')[0]
    c = dict(cells[n]); c['name'] = n + '_2h'; c['constraints'] = '/workspace/cons/%s_2h.json' % n; c['samples'] = 2
    out.append(c)
json.dump(out, open('cells_weapons_2h.json', 'w'), indent=1)
print('CELLS', len(out))
PY
python driver.py cells_weapons_2h.json Kimodo-SOMA-RP-v1
python hand_gap_npz.py /workspace/runs/th_overhead_2h /workspace/runs/th_side_2h /workspace/runs/th_idle_2h /workspace/runs/th_walk_2h 2>&1 | grep HAND_GAP
echo PASS2_DONE
