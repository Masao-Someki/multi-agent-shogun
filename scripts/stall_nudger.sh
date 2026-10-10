#!/usr/bin/env bash
# stall_nudger.sh — nudge a worker that said what it would do next but stopped
# calling tools, instead of ending its turn with real work.
#
# Usage: bash scripts/stall_nudger.sh
#
# Env vars:
#   STALL_NUDGER_ONCE       - if "1", run a single pass then exit (for tests)
#   STALL_NUDGER_IDLE_SECS  - seconds a watched agent must stay idle before it
#                             counts as stalled (default 60)
#   STALL_NUDGER_GAP_SECS   - minimum seconds between nudges to the same agent
#                             (default 180)
#   STALL_NUDGER_STATE_DIR  - directory for per-agent state files
#                             (default /tmp/shogun_stall_nudger)
#   STALL_NUDGER_ROOT       - repo root (default: this script's parent dir)
#
# Only touches the inbox via scripts/inbox_write.sh. Never sends /clear, /new,
# Escape, or tmux send-keys directly, and never kills anything.

set -euo pipefail

STALL_NUDGER_ROOT="${STALL_NUDGER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$STALL_NUDGER_ROOT"

STALL_NUDGER_IDLE_SECS="${STALL_NUDGER_IDLE_SECS:-60}"
STALL_NUDGER_GAP_SECS="${STALL_NUDGER_GAP_SECS:-180}"
STALL_NUDGER_STATE_DIR="${STALL_NUDGER_STATE_DIR:-/tmp/shogun_stall_nudger}"
STALL_NUDGER_LOOP_SECS="${STALL_NUDGER_LOOP_SECS:-15}"
STALL_NUDGER_MAX_NUDGES="${STALL_NUDGER_MAX_NUDGES:-5}"

mkdir -p "$STALL_NUDGER_STATE_DIR"

# shellcheck source=lib/agent_registry.sh
source "$STALL_NUDGER_ROOT/lib/agent_registry.sh"
# shellcheck source=lib/agent_status.sh
source "$STALL_NUDGER_ROOT/lib/agent_status.sh"

LOG_FILE="$STALL_NUDGER_ROOT/logs/stall_nudger.log"
mkdir -p "$STALL_NUDGER_ROOT/logs"

# stall_nudger_pane_idle <pane>
# Wraps agent_is_busy_check so tests can override just this function.
# Returns: 0=idle, 1=busy or missing.
# Maps agent_is_busy_check's codes (0=busy, 1=idle, 2=pane missing): rc 1 -> 0;
# rc 0 or rc 2 -> 1.
stall_nudger_pane_idle() {
    local pane="$1"
    local rc=0
    agent_is_busy_check "$pane" || rc=$?
    [ "$rc" -eq 1 ] && return 0
    return 1
}

# stall_nudger_watched_agents
# Every ashigaru and tanya from the formation (skip karo/gunshi/metsuke/shogun).
stall_nudger_watched_agents() {
    local agent
    while IFS= read -r agent; do
        [ -z "$agent" ] && continue
        case "$agent" in
            ashigaru[0-9]*|tanya) printf '%s\n' "$agent" ;;
        esac
    done < <(agent_registry_agents)
}

# stall_nudger_task_status <agent>
# Prints the task YAML's status value, or empty if unreadable/absent.
# Only reads the "status:" key directly under "task:" (2-space indent), never
# a line that happens to start with "status:" inside the description block.
stall_nudger_task_status() {
    local agent="$1"
    local task_file="$STALL_NUDGER_ROOT/queue/tasks/${agent}.yaml"
    [ -f "$task_file" ] || return 0
    grep -m1 -E '^  status:[[:space:]]*' "$task_file" \
        | sed -E 's/^  status:[[:space:]]*"?([A-Za-z_]+)"?.*/\1/'
}

# stall_nudger_task_id <agent>
# Prints the task YAML's task_id value, or empty if unreadable/absent.
# Only reads the "task_id:" key directly under "task:" (2-space indent), never
# a line that happens to start with "task_id:" inside the description block.
stall_nudger_task_id() {
    local agent="$1"
    local task_file="$STALL_NUDGER_ROOT/queue/tasks/${agent}.yaml"
    [ -f "$task_file" ] || return 0
    grep -m1 -E '^  task_id:[[:space:]]*' "$task_file" \
        | sed -E 's/^  task_id:[[:space:]]*"?([A-Za-z0-9_.-]+)"?.*/\1/'
}

# stall_nudger_has_unread_mail <agent>
# True (rc=0) if queue/inbox/<agent>.yaml has an entry with read: false.
stall_nudger_has_unread_mail() {
    local agent="$1"
    local inbox_file="$STALL_NUDGER_ROOT/queue/inbox/${agent}.yaml"
    [ -f "$inbox_file" ] || return 1
    grep -q 'read: false' "$inbox_file"
}

_state_file() {
    local agent="$1"
    printf '%s/%s.state\n' "$STALL_NUDGER_STATE_DIR" "$agent"
}

# State file format (5 lines): task_id, status, first_idle_epoch, nudge_count, last_nudge_epoch
_read_state() {
    local agent="$1"
    local f
    f=$(_state_file "$agent")
    if [ -f "$f" ]; then
        cat "$f"
    fi
}

_write_state() {
    local agent="$1" task_id="$2" status="$3" first_idle="$4" nudge_count="$5" last_nudge="$6"
    local f
    f=$(_state_file "$agent")
    {
        printf 'task_id=%s\n' "$task_id"
        printf 'status=%s\n' "$status"
        printf 'first_idle=%s\n' "$first_idle"
        printf 'nudge_count=%s\n' "$nudge_count"
        printf 'last_nudge=%s\n' "$last_nudge"
    } > "$f"
}

_state_get() {
    local state="$1" key="$2"
    printf '%s\n' "$state" | sed -n "s/^${key}=//p" | head -1
}

stall_nudger_process_agent() {
    local agent="$1"
    local now
    now=$(date +%s)

    local status task_id
    status=$(stall_nudger_task_status "$agent")
    task_id=$(stall_nudger_task_id "$agent")

    local state prev_task_id prev_status prev_first_idle prev_nudge_count prev_last_nudge
    state=$(_read_state "$agent")
    prev_task_id=$(_state_get "$state" "task_id")
    prev_status=$(_state_get "$state" "status")
    prev_first_idle=$(_state_get "$state" "first_idle")
    prev_nudge_count=$(_state_get "$state" "nudge_count")
    prev_last_nudge=$(_state_get "$state" "last_nudge")
    [ -n "$prev_first_idle" ] || prev_first_idle=0
    [ -n "$prev_nudge_count" ] || prev_nudge_count=0
    [ -n "$prev_last_nudge" ] || prev_last_nudge=0

    # Reset counters when the task_id or status changes.
    if [ "$task_id" != "$prev_task_id" ] || [ "$status" != "$prev_status" ]; then
        prev_first_idle=0
        prev_nudge_count=0
        prev_last_nudge=0
    fi

    # a. must be assigned or in_progress
    if [ "$status" != "assigned" ] && [ "$status" != "in_progress" ]; then
        rm -f "$(_state_file "$agent")"
        return 0
    fi

    # Stop nudging once this task_id already hit the limit.
    if [ "$prev_nudge_count" -ge "$STALL_NUDGER_MAX_NUDGES" ]; then
        _write_state "$agent" "$task_id" "$status" "$prev_first_idle" "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    # b. pane must be idle (stall_nudger_pane_idle: 0=idle, 1=busy or missing)
    local pane
    if ! pane=$(agent_registry_pane_for_agent "$agent"); then
        _write_state "$agent" "$task_id" "$status" 0 "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    if ! stall_nudger_pane_idle "$pane"; then
        _write_state "$agent" "$task_id" "$status" 0 "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    # d. unread mail belongs to inbox_watcher, not us.
    if stall_nudger_has_unread_mail "$agent"; then
        _write_state "$agent" "$task_id" "$status" 0 "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    # c. must have been idle for >= STALL_NUDGER_IDLE_SECS without a break
    local first_idle="$prev_first_idle"
    if [ "$first_idle" -eq 0 ]; then
        first_idle="$now"
        _write_state "$agent" "$task_id" "$status" "$first_idle" "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    local idle_elapsed=$((now - first_idle))
    if [ "$idle_elapsed" -lt "$STALL_NUDGER_IDLE_SECS" ]; then
        _write_state "$agent" "$task_id" "$status" "$first_idle" "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    # Rate limit: at most one nudge per agent every STALL_NUDGER_GAP_SECS.
    local since_last_nudge=$((now - prev_last_nudge))
    if [ "$prev_last_nudge" -ne 0 ] && [ "$since_last_nudge" -lt "$STALL_NUDGER_GAP_SECS" ]; then
        _write_state "$agent" "$task_id" "$status" "$first_idle" "$prev_nudge_count" "$prev_last_nudge"
        return 0
    fi

    local new_nudge_count=$((prev_nudge_count + 1))

    bash "$STALL_NUDGER_ROOT/scripts/inbox_write.sh" "$agent" \
        "Keep going. You stopped after saying what you would do next. Call the tools now and finish the task in your task YAML." \
        nudge stall_nudger

    printf '%s %s %s nudge %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$agent" "$task_id" "$new_nudge_count" >> "$LOG_FILE"

    if [ "$new_nudge_count" -ge "$STALL_NUDGER_MAX_NUDGES" ]; then
        bash "$STALL_NUDGER_ROOT/scripts/inbox_write.sh" karo \
            "${agent} is still stalled on ${task_id} after ${STALL_NUDGER_MAX_NUDGES} nudges." \
            nudge stall_nudger
    fi

    _write_state "$agent" "$task_id" "$status" "$first_idle" "$new_nudge_count" "$now"
}

stall_nudger_run_pass() {
    local agent
    while IFS= read -r agent; do
        [ -z "$agent" ] && continue
        stall_nudger_process_agent "$agent"
    done < <(stall_nudger_watched_agents)
}

stall_nudger_main() {
    if [ "${STALL_NUDGER_ONCE:-0}" = "1" ]; then
        stall_nudger_run_pass
        return 0
    fi

    while true; do
        stall_nudger_run_pass
        sleep "$STALL_NUDGER_LOOP_SECS"
    done
}

if [ "${__STALL_NUDGER_TESTING__:-}" != "1" ]; then
    stall_nudger_main
fi
