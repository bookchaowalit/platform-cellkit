#!/usr/bin/env bash
# The kit's test suite: the mini cell, then each finance fixture in its own pytest session
# (the harness is session-scoped per cell root). Coverage is appended across the three runs.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python}
"$PY" -m coverage erase
"$PY" -m pytest tests/kit --cov=src --cov-report= "$@"
for fixture in finance-accounts finance-transactions; do
  CELLKIT_ROOT="tests/fixtures/$fixture" "$PY" -m pytest tests/finance --cov=src --cov-append --cov-report= "$@"
done
"$PY" -m coverage report
