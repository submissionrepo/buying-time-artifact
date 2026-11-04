#!/usr/bin/env bash
# Phase B (wall clock) for destination block times of 2 s and 12 s, in parallel on separate ports (2026-10-16).
set -u
PY="${PYTHON:-python}"
export PATH="$HOME/.foundry/bin:$PATH"
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")"
"$PY" run_b.py 2 --reps 3 --ports 18901 18902 > logs/rt_E25_d2.stdout 2>&1 &
"$PY" run_b.py 12 --reps 3 --ports 18911 18912 > logs/rt_E25_d12.stdout 2>&1 &
wait
echo "phase B finished"
