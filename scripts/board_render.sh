#!/usr/bin/env bash
# Render queue/board/board.md from the per-agent status files.
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$SCRIPT_DIR/.venv/bin/python3"; [ -x "$PY" ] || PY=python3
exec "$PY" "$SCRIPT_DIR/scripts/board_render.py" "$@"
