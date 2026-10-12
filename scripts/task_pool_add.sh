#!/usr/bin/env bash
# Task pool: add (see scripts/task_pool.py). Usage: bash scripts/task_pool_add.sh ...
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -z "${POOL_AGENTS:-}" ]; then
    # shellcheck disable=SC1091
    . "$SCRIPT_DIR/lib/agent_registry.sh"
    POOL_AGENTS="$(agent_registry_agents | grep '^ashigaru' | tr '\n' ' ')"
    export POOL_AGENTS
fi
PY="$SCRIPT_DIR/.venv/bin/python3"
[ -x "$PY" ] || PY=python3
exec "$PY" "$SCRIPT_DIR/scripts/task_pool.py" add "$@"
