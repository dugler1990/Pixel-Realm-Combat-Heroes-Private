#!/usr/bin/env bash
# Broad CPU profile of the WHOLE multiplayer setup with py-spy.
#
# Multiplayer is 3+ processes (one Server/server.py + one Code/Main2.py per
# client), and the server does its real work on background threads while its main
# thread blocks in accept() -- so `python -m cProfile` can't see it. py-spy is a
# sampling profiler that attaches to a running PID and samples ALL threads, no
# code changes. This records every live MP process at once into one flamegraph
# each (profiles/<role>-<pid>.svg).
#
# One-time setup:
#   pip install --user py-spy                       # ~/.local/bin/py-spy
#   sudo sysctl -w kernel.yama.ptrace_scope=0        # let py-spy attach w/o root (resets on reboot)
#
# Usage (start the server + clients and play first, THEN):
#   DUR=30 tools/profile_mp.sh        # 30s flamegraph per process -> profiles/*.svg
#   DUR=20 RATE=200 tools/profile_mp.sh
#
# Ad-hoc, no script needed:
#   py-spy top  --pid <pid>           # live top, watch it as you play
#   py-spy dump --pid <pid>           # instant all-thread stack snapshot
set -uo pipefail

DUR="${DUR:-30}"          # seconds to record
RATE="${RATE:-120}"       # samples/sec
OUT="${OUT:-profiles}"    # output dir (relative to repo root)

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="$REPO/$OUT"
mkdir -p "$OUTDIR"

if ! command -v py-spy >/dev/null 2>&1; then
  echo "py-spy not found -- run: pip install --user py-spy  (and put ~/.local/bin on PATH)" >&2
  exit 1
fi

record() {  # role, pid
  local role="$1" pid="$2" f="$OUTDIR/$1-$2.svg"
  echo "[profile_mp] recording $role (pid $pid) ${DUR}s -> $f"
  # --idle keeps blocked/waiting threads in the graph (so a busy sim thread is
  # distinguishable from threads merely blocked on recv -- CPU-bound vs waiting).
  py-spy record -o "$f" --pid "$pid" --duration "$DUR" --rate "$RATE" --idle --threads &
}

found=0
spid="$(pgrep -f '[s]erver.py' | head -1 || true)"
[[ -n "${spid:-}" ]] && { record server "$spid"; found=1; }

i=0
for cpid in $(pgrep -f '[M]ain2.py' || true); do
  record "client$i" "$cpid"; found=1; i=$((i + 1))
done

if [[ "$found" -eq 0 ]]; then
  echo "[profile_mp] no server.py / Main2.py processes found -- start the game first." >&2
  exit 1
fi

wait
echo "[profile_mp] done. Open these in a browser:"
ls -1 "$OUTDIR"/*.svg 2>/dev/null
