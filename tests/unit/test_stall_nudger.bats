#!/usr/bin/env bats
# test_stall_nudger.bats — unit tests for scripts/stall_nudger.sh
#
# The real script is sourced (with __STALL_NUDGER_TESTING__=1 so its main
# loop does not run) into a sandboxed temp root, so its real logic runs.
# Three seams are overridden as plain shell functions per test:
#   agent_registry_agents, agent_registry_pane_for_agent, stall_nudger_pane_idle
# stall_nudger_pane_idle's contract (from the script): 0=idle, 1=busy or missing.
# A fake scripts/inbox_write.sh under the sandbox root records every call.

PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

setup() {
    TEST_DIR="$(mktemp -d)"
    export STALL_NUDGER_ROOT="$TEST_DIR"
    export STALL_NUDGER_STATE_DIR="$TEST_DIR/state"
    export STALL_NUDGER_IDLE_SECS=60
    export STALL_NUDGER_GAP_SECS=180
    export STALL_NUDGER_MAX_NUDGES=5
    export __STALL_NUDGER_TESTING__=1

    mkdir -p "$TEST_DIR/scripts" "$TEST_DIR/lib" "$TEST_DIR/logs"
    mkdir -p "$TEST_DIR/queue/tasks" "$TEST_DIR/queue/inbox"

    cp "$PROJECT_ROOT/scripts/stall_nudger.sh" "$TEST_DIR/scripts/stall_nudger.sh"
    cp "$PROJECT_ROOT/lib/agent_registry.sh" "$TEST_DIR/lib/agent_registry.sh"
    cp "$PROJECT_ROOT/lib/agent_status.sh" "$TEST_DIR/lib/agent_status.sh"

    # Fake inbox_write.sh — records every call's arguments, one per line.
    cat > "$TEST_DIR/scripts/inbox_write.sh" << 'MOCK'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STALL_NUDGER_ROOT/inbox_calls.log"
MOCK
    chmod +x "$TEST_DIR/scripts/inbox_write.sh"

    source "$TEST_DIR/scripts/stall_nudger.sh"

    # Default seams; individual tests override what they need.
    agent_registry_agents() { printf '%s\n' ashigaru1 karo gunshi metsuke tanya; }
    agent_registry_pane_for_agent() { printf '%s\n' "multiagent:agents.0"; }
    stall_nudger_pane_idle() { return 0; }
}

teardown() {
    rm -rf "$TEST_DIR"
}

# _write_task <agent> <status> [task_id]
_write_task() {
    local agent="$1" status="$2" task_id="${3:-task_001}"
    cat > "$STALL_NUDGER_ROOT/queue/tasks/${agent}.yaml" << EOF
task:
  task_id: ${task_id}
  status: ${status}
EOF
}

# _write_inbox <agent> <unread: true|false>
# unread=true writes an entry with read: false (there is unread mail);
# unread=false writes read: true (no unread mail).
_write_inbox() {
    local agent="$1" unread="$2"
    local read_value="true"
    [ "$unread" = "true" ] && read_value="false"
    printf 'messages:\n- read: %s\n' "$read_value" \
        > "$STALL_NUDGER_ROOT/queue/inbox/${agent}.yaml"
}

# _seed_state <agent> <task_id> <status> <first_idle> <nudge_count> <last_nudge>
_seed_state() {
    local agent="$1" task_id="$2" status="$3"
    local first_idle="$4" nudge_count="$5" last_nudge="$6"
    mkdir -p "$STALL_NUDGER_STATE_DIR"
    printf 'task_id=%s\nstatus=%s\nfirst_idle=%s\nnudge_count=%s\nlast_nudge=%s\n' \
        "$task_id" "$status" "$first_idle" "$nudge_count" "$last_nudge" \
        > "$STALL_NUDGER_STATE_DIR/${agent}.state"
}

# _seed_idle_past <agent> <task_id> <status> <nudge_count> <last_nudge>
# first_idle is far enough in the past that the idle-duration check already
# passes, so tests do not need to sleep in real time.
_seed_idle_past() {
    local agent="$1" task_id="$2" status="$3" nudge_count="$4" last_nudge="$5"
    local past
    past=$(( $(date +%s) - STALL_NUDGER_IDLE_SECS - 10 ))
    _seed_state "$agent" "$task_id" "$status" "$past" "$nudge_count" "$last_nudge"
}

@test "1. Nudge: status assigned, pane idle, idle time over limit, no unread inbox" {
    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 false
    _seed_idle_past ashigaru1 task_001 assigned 0 0

    stall_nudger_process_agent ashigaru1

    grep -q '^ashigaru1 ' "$STALL_NUDGER_ROOT/inbox_calls.log"
    grep -q '^nudge_count=1$' "$STALL_NUDGER_STATE_DIR/ashigaru1.state"
}

@test "2. No nudge: inbox has 'read: false'" {
    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 true
    _seed_idle_past ashigaru1 task_001 assigned 0 0

    stall_nudger_process_agent ashigaru1

    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]
}

@test "3. No nudge: task status done" {
    _write_task ashigaru1 "done" task_001
    _write_inbox ashigaru1 false
    _seed_idle_past ashigaru1 task_001 "done" 0 0

    stall_nudger_process_agent ashigaru1

    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]
    [ ! -f "$STALL_NUDGER_STATE_DIR/ashigaru1.state" ]
}

@test "4. No nudge: pane busy" {
    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 false
    _seed_idle_past ashigaru1 task_001 assigned 0 0
    stall_nudger_pane_idle() { return 1; }

    stall_nudger_process_agent ashigaru1

    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]
}

@test "5. No nudge: idle time under the limit" {
    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 false
    _seed_state ashigaru1 task_001 assigned "$(date +%s)" 0 0

    stall_nudger_process_agent ashigaru1

    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]
}

@test "6. No nudge: a nudge was sent less than GAP seconds ago" {
    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 false
    _seed_idle_past ashigaru1 task_001 assigned 1 "$(( $(date +%s) - 1 ))"

    stall_nudger_process_agent ashigaru1

    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]
}

@test "7. Never nudges karo, gunshi or metsuke even if their task is assigned" {
    for a in karo gunshi metsuke; do
        _write_task "$a" assigned task_x
        _write_inbox "$a" false
        _seed_idle_past "$a" task_x assigned 0 0
    done

    stall_nudger_run_pass

    if [ -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]; then
        run grep -E '^(karo|gunshi|metsuke) ' "$STALL_NUDGER_ROOT/inbox_calls.log"
        [ "$status" -ne 0 ]
    fi
}

@test "8. After 5 nudges on one task_id: no 6th nudge, and karo gets one message" {
    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 false
    _seed_idle_past ashigaru1 task_001 assigned 4 0

    stall_nudger_process_agent ashigaru1

    [ "$(grep -c '^ashigaru1 ' "$STALL_NUDGER_ROOT/inbox_calls.log")" -eq 1 ]
    [ "$(grep -c '^karo ' "$STALL_NUDGER_ROOT/inbox_calls.log")" -eq 1 ]
    grep -q '^nudge_count=5$' "$STALL_NUDGER_STATE_DIR/ashigaru1.state"

    # Clear the GAP check so the limit, not the gap, blocks the 6th nudge.
    _seed_idle_past ashigaru1 task_001 assigned 5 \
        "$(( $(date +%s) - STALL_NUDGER_GAP_SECS - 10 ))"

    stall_nudger_process_agent ashigaru1

    [ "$(grep -c '^ashigaru1 ' "$STALL_NUDGER_ROOT/inbox_calls.log")" -eq 1 ]
    [ "$(grep -c '^karo ' "$STALL_NUDGER_ROOT/inbox_calls.log")" -eq 1 ]
}

@test "9. stall_nudger_pane_idle maps agent_is_busy_check's codes correctly" {
    # setup()'s default stubs out stall_nudger_pane_idle wholesale, which
    # would never exercise the mapping inside it. Re-source to restore the
    # real stall_nudger_pane_idle (and the real agent_is_busy_check), then
    # override only agent_is_busy_check, the thing it wraps.
    source "$STALL_NUDGER_ROOT/scripts/stall_nudger.sh"

    _write_task ashigaru1 assigned task_001
    _write_inbox ashigaru1 false

    # agent_is_busy_check: 0=busy -> no nudge.
    agent_is_busy_check() { return 0; }
    _seed_idle_past ashigaru1 task_001 assigned 0 0
    stall_nudger_process_agent ashigaru1
    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]

    # agent_is_busy_check: 2=pane missing -> no nudge.
    agent_is_busy_check() { return 2; }
    _seed_idle_past ashigaru1 task_001 assigned 0 0
    stall_nudger_process_agent ashigaru1
    [ ! -f "$STALL_NUDGER_ROOT/inbox_calls.log" ]

    # agent_is_busy_check: 1=idle -> exactly one nudge.
    agent_is_busy_check() { return 1; }
    _seed_idle_past ashigaru1 task_001 assigned 0 0
    stall_nudger_process_agent ashigaru1
    [ "$(grep -c '^ashigaru1 ' "$STALL_NUDGER_ROOT/inbox_calls.log")" -eq 1 ]
}
