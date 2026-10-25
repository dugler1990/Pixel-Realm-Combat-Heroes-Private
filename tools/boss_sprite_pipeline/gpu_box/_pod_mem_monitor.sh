#!/usr/bin/env bash
# Sample host RAM, GPU, and the trellis2_run.py process until it exits.
export PATH=/usr/sbin:/usr/bin:/bin:/usr/local/cuda/bin
PIDFILE=/workspace/trellis2.pid
echo "MONITOR_START $(date -Is)"
for i in $(seq 1 3600); do
  if [ ! -f "$PIDFILE" ]; then
    echo "NO_PIDFILE $(date -Is)"
    break
  fi
  pid=$(cat "$PIDFILE")
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "PROC_GONE $(date -Is) pid=$pid"
    if [ -n "$pid" ]; then
      wait "$pid" 2>/dev/null || true
    fi
    echo "PYTHON_EXIT unknown (process already reaped)"
    break
  fi
  echo "=== $(date -Is) sample=$i pid=$pid ==="
  awk '/MemTotal:|MemAvailable:|MemFree:|Cached:|SwapFree:/ {print}' /proc/meminfo
  nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
  awk '/VmRSS:|VmSize:|VmPeak:|Threads:|voluntary_ctxt/' /proc/"$pid"/status 2>/dev/null || echo "status_gone"
  echo
  sleep 2
done
echo "MONITOR_END $(date -Is)"
dmesg -T 2>/dev/null | grep -iE 'killed process|out of memory|oom-kill|segfault' | tail -n 20 || true
ls -lh /workspace/out 2>/dev/null || true
