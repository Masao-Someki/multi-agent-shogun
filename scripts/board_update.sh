#!/usr/bin/env bash
# Update one agent's row on the command-layer board, then render board.md.
# Usage: bash scripts/board_update.sh [--no-render] <agent_id> key=value [key=value ...]
# Keys: task_id cmd plan_status step note question qc.  "key=" clears a key.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOARD_DIR="${BOARD_DIR:-$SCRIPT_DIR/queue/board}"
RENDER=1
if [ "${1:-}" = "--no-render" ]; then
    RENDER=0
    shift
fi
if [ $# -lt 2 ]; then
    echo "usage: board_update.sh [--no-render] <agent_id> key=value ..." >&2
    exit 2
fi
AGENT="$1"
shift
case "$AGENT" in
    shogun|karo|metsuke|kumigashira|gunshi|tanya|tanya2|ashigaru[1-9]|ashigaru10) ;;
    *) echo "board_update: unknown agent: $AGENT" >&2; exit 2 ;;
esac
for pair in "$@"; do
    case "${pair%%=*}" in
        task_id|cmd|plan_status|step|note|question|qc) ;;
        *) echo "board_update: unknown key: ${pair%%=*}" >&2; exit 2 ;;
    esac
done

mkdir -p "$BOARD_DIR"
FILE="$BOARD_DIR/$AGENT.yaml"
LOCK_DIR="$FILE.lock.d"
LOCKFILE="$FILE.lock"

_acquire_lock() {
    local i=0
    while ! mkdir "$LOCK_DIR" 2>/dev/null; do
        sleep 0.1
        i=$((i + 1))
        [ $i -ge 50 ] && return 1
    done
    if command -v flock >/dev/null 2>&1; then
        exec 200>"$LOCKFILE"
        flock -w 5 200 || { rmdir "$LOCK_DIR" 2>/dev/null; return 1; }
    fi
}

_release_lock() {
    if command -v flock >/dev/null 2>&1; then
        exec 200>&-
    fi
    rmdir "$LOCK_DIR" 2>/dev/null || true
}

_acquire_lock || { echo "board_update: lock timeout for $AGENT" >&2; exit 1; }
trap _release_lock EXIT
touch "$FILE"
cp "$FILE" "$FILE.tmp"
for pair in "$@" "updated=$(date +%FT%T)"; do
    key="${pair%%=*}"
    value="${pair#*=}"
    grep -v "^$key: " "$FILE.tmp" > "$FILE.tmp2" || true
    if [ -n "$value" ]; then
        printf '%s: %s\n' "$key" "$value" >> "$FILE.tmp2"
    fi
    mv "$FILE.tmp2" "$FILE.tmp"
done
mv "$FILE.tmp" "$FILE"
_release_lock
trap - EXIT

if [ "$RENDER" = 1 ]; then
    PY="$SCRIPT_DIR/.venv/bin/python3"
    [ -x "$PY" ] || PY=python3
    "$PY" "$SCRIPT_DIR/scripts/board_render.py" "$BOARD_DIR"
fi
