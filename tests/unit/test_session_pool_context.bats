#!/usr/bin/env bats
# test_session_pool_context.bats — per-CLI context policy of the session pool
#
# Part 1 sources lib/session_pool.sh alone and checks session_pool_preserves_context.
# Part 2 sources the REAL scripts/inbox_watcher.sh (__INBOX_WATCHER_TESTING__=1)
# together with lib/session_pool.sh and checks send_context_reset per agent/CLI.
# Everything runs in a throwaway directory under $BATS_TMPDIR; tmux, timeout and
# sleep are shell functions, so no camp file, inbox or pane is touched.
#
# Cases:
#   T-POOL-001..005: helper — claude keeps, codex/opencode reset, default from CLI_TYPE
#   T-POOL-010: ashigaru1 on codex → /new then the startup prompt
#   T-POOL-011: ashigaru1 on claude → nothing sent, session kept
#   T-POOL-012: tanya on codex → /new (tanya is a worker, not command layer)
#   T-POOL-013: karo on codex → nothing sent (command-layer guard)
#   T-POOL-014: metsuke on claude → nothing sent, session kept

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export WATCHER_SCRIPT="$PROJECT_ROOT/scripts/inbox_watcher.sh"
    export POOL_SCRIPT="$PROJECT_ROOT/lib/session_pool.sh"
    [ -f "$WATCHER_SCRIPT" ]
    [ -f "$POOL_SCRIPT" ]

    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/session_pool_test.XXXXXX")"
    mkdir -p "$TEST_TMPDIR/queue/inbox"
    export MOCK_LOG="$TEST_TMPDIR/tmux_calls.log"
    : > "$MOCK_LOG"
    export MOCK_PANE_CLI=""

    # Harness: fake environment + mocks, then source pool + real watcher.
    export TEST_HARNESS="$TEST_TMPDIR/harness.sh"
    cat > "$TEST_HARNESS" << HARNESS
#!/bin/bash
AGENT_ID="\${HARNESS_AGENT_ID:-ashigaru1}"
PANE_TARGET="test:0.0"
CLI_TYPE="\${HARNESS_CLI_TYPE-claude}"
INBOX="$TEST_TMPDIR/queue/inbox/\${AGENT_ID}.yaml"
LOCKFILE="\${INBOX}.lock"
SCRIPT_DIR="$TEST_TMPDIR"
export IDLE_FLAG_DIR="$TEST_TMPDIR"
export CLI_ADAPTER_PROJECT_ROOT="$TEST_TMPDIR"

tmux() {
    echo "tmux \$*" >> "$MOCK_LOG"
    if echo "\$*" | grep -q "show-options"; then
        echo "\${MOCK_PANE_CLI:-}"
    fi
    return 0
}
timeout() { shift; "\$@"; }
sleep() { :; }

source "$POOL_SCRIPT"
export __INBOX_WATCHER_TESTING__=1
source "$WATCHER_SCRIPT"
agent_is_busy() { return 1; }
HARNESS
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

# ─── Part 1: the helper alone ───

@test "T-POOL-001: helper — claude keeps context" {
    run bash -c 'CLI_ADAPTER_PROJECT_ROOT="$TEST_TMPDIR"; source "$POOL_SCRIPT"; session_pool_preserves_context claude'
    [ "$status" -eq 0 ]
}

@test "T-POOL-002: helper — codex does not keep context" {
    run bash -c 'CLI_ADAPTER_PROJECT_ROOT="$TEST_TMPDIR"; source "$POOL_SCRIPT"; session_pool_preserves_context codex'
    [ "$status" -eq 1 ]
}

@test "T-POOL-003: helper — opencode (outside the pool) does not keep context" {
    run bash -c 'CLI_ADAPTER_PROJECT_ROOT="$TEST_TMPDIR"; source "$POOL_SCRIPT"; session_pool_preserves_context opencode'
    [ "$status" -eq 1 ]
}

@test "T-POOL-004: helper — no argument falls back to CLI_TYPE=claude" {
    run bash -c 'CLI_ADAPTER_PROJECT_ROOT="$TEST_TMPDIR"; CLI_TYPE=claude; source "$POOL_SCRIPT"; session_pool_preserves_context'
    [ "$status" -eq 0 ]
}

@test "T-POOL-005: helper — no argument falls back to CLI_TYPE=codex" {
    run bash -c 'CLI_ADAPTER_PROJECT_ROOT="$TEST_TMPDIR"; CLI_TYPE=codex; source "$POOL_SCRIPT"; session_pool_preserves_context'
    [ "$status" -eq 1 ]
}

# ─── Part 2: send_context_reset through the real watcher ───

@test "T-POOL-010: ashigaru1 on codex — /new is sent, then the startup prompt" {
    export HARNESS_AGENT_ID="ashigaru1"
    export HARNESS_CLI_TYPE="codex"
    export MOCK_PANE_CLI="codex"
    run bash -c 'source "$TEST_HARNESS"; send_context_reset'
    [ "$status" -eq 0 ]
    grep -q "send-keys -t test:0.0 /new" "$MOCK_LOG"
    grep -q "Session Start" "$MOCK_LOG"
    # /new comes before the startup prompt
    new_line=$(grep -n "send-keys -t test:0.0 /new" "$MOCK_LOG" | head -1 | cut -d: -f1)
    prompt_line=$(grep -n "Session Start" "$MOCK_LOG" | head -1 | cut -d: -f1)
    [ "$new_line" -lt "$prompt_line" ]
    ! grep -q "send-keys.*/clear" "$MOCK_LOG"
}

@test "T-POOL-011: ashigaru1 on claude — nothing is sent, session kept" {
    export HARNESS_AGENT_ID="ashigaru1"
    export HARNESS_CLI_TYPE="claude"
    export MOCK_PANE_CLI="claude"
    run bash -c 'source "$TEST_HARNESS"; send_context_reset'
    [ "$status" -eq 0 ]
    echo "$output" | grep -q "SESSION-POOL"
    ! grep -q "send-keys" "$MOCK_LOG"
}

@test "T-POOL-012: tanya on codex — /new is sent (worker, not command layer)" {
    export HARNESS_AGENT_ID="tanya"
    export HARNESS_CLI_TYPE="codex"
    export MOCK_PANE_CLI="codex"
    run bash -c 'source "$TEST_HARNESS"; send_context_reset'
    [ "$status" -eq 0 ]
    grep -q "send-keys -t test:0.0 /new" "$MOCK_LOG"
}

@test "T-POOL-013: karo on codex — nothing is sent (command-layer guard)" {
    export HARNESS_AGENT_ID="karo"
    export HARNESS_CLI_TYPE="codex"
    export MOCK_PANE_CLI="codex"
    run bash -c 'source "$TEST_HARNESS"; send_context_reset'
    [ "$status" -eq 0 ]
    echo "$output" | grep -q "command-layer"
    ! grep -q "send-keys" "$MOCK_LOG"
}

@test "T-POOL-014: metsuke on claude — nothing is sent, session kept" {
    export HARNESS_AGENT_ID="metsuke"
    export HARNESS_CLI_TYPE="claude"
    export MOCK_PANE_CLI="claude"
    run bash -c 'source "$TEST_HARNESS"; send_context_reset'
    [ "$status" -eq 0 ]
    echo "$output" | grep -q "SESSION-POOL"
    ! grep -q "send-keys" "$MOCK_LOG"
}
