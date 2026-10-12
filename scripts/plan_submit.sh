#!/usr/bin/env bash
# Set plan_status: submitted in the Ashigaru's task YAML and send plan_submitted to Kumigashira, in one run.
# Usage: bash scripts/plan_submit.sh <ashigaruN>
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$SCRIPT_DIR/.venv/bin/python3"
[ -x "$PY" ] || PY=python3
exec "$PY" "$SCRIPT_DIR/scripts/task_pool.py" plan_submit "$@"
