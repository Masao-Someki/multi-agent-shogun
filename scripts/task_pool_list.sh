#!/usr/bin/env bash
# Task pool: list (see scripts/task_pool.py). Usage: bash scripts/task_pool_list.sh ...
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$SCRIPT_DIR/.venv/bin/python3"
[ -x "$PY" ] || PY=python3
exec "$PY" "$SCRIPT_DIR/scripts/task_pool.py" list "$@"
