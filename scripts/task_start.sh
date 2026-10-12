#!/bin/bash
# wrapper for scripts/task_start.py
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$SCRIPT_DIR/.venv/bin/python3"
[ -x "$PY" ] || PY=python3
exec "$PY" "$SCRIPT_DIR/scripts/task_start.py" "$@"
