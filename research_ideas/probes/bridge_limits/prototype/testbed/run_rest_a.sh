#!/usr/bin/env bash
# Remaining phase A runs, two chains in parallel on separate anvil port pairs (2026-10-16).
# Usage: bash run_rest_a.sh  (from the testbed directory)
set -u
PY="${PYTHON:-python}"
export PATH="$HOME/.foundry/bin:$PATH"
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")"
(
  for r in E25_d2_k12 E25_d2_k2_reorg_a E15_d2_k64; do
    "$PY" run_a.py "$r" --ports 18711 18712 > "logs/$r.stdout" 2>&1 || echo "FAILED $r" >> logs/rest_a_failures.txt
  done
) &
(
  for r in E25_d2_k2 E25_d2_k2_reorg_b E15_d12_k64; do
    "$PY" run_a.py "$r" --ports 18721 18722 > "logs/$r.stdout" 2>&1 || echo "FAILED $r" >> logs/rest_a_failures.txt
  done
) &
wait
echo "all phase A runs finished"
