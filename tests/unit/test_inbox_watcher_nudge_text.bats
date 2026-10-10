#!/usr/bin/env bats
# test_inbox_watcher_nudge_text.bats — build_nudge_text() unit tests
#
# Sources the REAL scripts/inbox_watcher.sh with __INBOX_WATCHER_TESTING__=1
# (only function definitions load). Everything runs against a throwaway
# directory under $BATS_TMPDIR with tmux and timeout replaced by shell
# functions, so no camp file, inbox or tmux pane is touched.
#
# Cases:
#   T-NUDGE-001: codex   → full sentence naming the agent's own inbox and task file
#   T-NUDGE-002: claude  → bare "inboxN"
#   T-NUDGE-003: opencode → bare "inboxN" (only codex gets the long form)
#   T-NUDGE-004: real get_effective_cli_type with pane @agent_cli=codex → long form,
#                and the only tmux call goes to the fake pane target
#   T-NUDGE-005: CLI unresolved (no pane value, no CLI_TYPE) → codex-safe long form

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export WATCHER_SCRIPT="$PROJECT_ROOT/scripts/inbox_watcher.sh"
    [ -f "$WATCHER_SCRIPT" ]

    export TEST_TMPDIR="$(mktemp -d "$BATS_TMPDIR/nudge_text_test.XXXXXX")"
    mkdir -p "$TEST_TMPDIR/queue/inbox"
    export MOCK_LOG="$TEST_TMPDIR/tmux_calls.log"
    : > "$MOCK_LOG"
    export MOCK_PANE_CLI=""

    # Harness: fake environment + mocks, then source the real script.
    # CLI_TYPE comes from HARNESS_CLI_TYPE (unset → claude, empty string stays empty).
    export TEST_HARNESS="$TEST_TMPDIR/harness.sh"
    cat > "$TEST_HARNESS" << HARNESS
#!/bin/bash
AGENT_ID="ashigaru1"
PANE_TARGET="test:0.0"
CLI_TYPE="\${HARNESS_CLI_TYPE-claude}"
INBOX="$TEST_TMPDIR/queue/inbox/ashigaru1.yaml"
LOCKFILE="\${INBOX}.lock"
SCRIPT_DIR="$TEST_TMPDIR"
export IDLE_FLAG_DIR="$TEST_TMPDIR"

tmux() {
    echo "tmux \$*" >> "$MOCK_LOG"
    if echo "\$*" | grep -q "show-options"; then
        echo "\${MOCK_PANE_CLI:-}"
    fi
    return 0
}
timeout() { shift; "\$@"; }

export __INBOX_WATCHER_TESTING__=1
source "$WATCHER_SCRIPT"
HARNESS
}

teardown() {
    rm -rf "$TEST_TMPDIR"
}

CODEX_SENTENCE_5="You are ashigaru1. Read queue/inbox/ashigaru1.yaml (5 unread), process them, then do queue/tasks/ashigaru1.yaml if its status is assigned."

@test "T-NUDGE-001: build_nudge_text — codex gets the full sentence with its own inbox" {
    run bash -c '
        source "$TEST_HARNESS"
        get_effective_cli_type() { echo "codex"; }
        build_nudge_text 5
    '
    [ "$status" -eq 0 ]
    [ "$output" = "$CODEX_SENTENCE_5" ]
}

@test "T-NUDGE-002: build_nudge_text — claude keeps the bare inboxN" {
    run bash -c '
        source "$TEST_HARNESS"
        get_effective_cli_type() { echo "claude"; }
        build_nudge_text 3
    '
    [ "$status" -eq 0 ]
    [ "$output" = "inbox3" ]
}

@test "T-NUDGE-003: build_nudge_text — opencode keeps the bare inboxN" {
    run bash -c '
        source "$TEST_HARNESS"
        get_effective_cli_type() { echo "opencode"; }
        build_nudge_text 4
    '
    [ "$status" -eq 0 ]
    [ "$output" = "inbox4" ]
}

@test "T-NUDGE-004: real resolver — pane @agent_cli=codex wins and only the fake pane is queried" {
    export MOCK_PANE_CLI="codex"
    export HARNESS_CLI_TYPE="claude"
    run bash -c '
        source "$TEST_HARNESS"
        build_nudge_text 5 2>/dev/null
    '
    [ "$status" -eq 0 ]
    [ "$output" = "$CODEX_SENTENCE_5" ]
    grep -q "show-options -p -t test:0.0 -v @agent_cli" "$MOCK_LOG"
    ! grep -v "test:0.0" "$MOCK_LOG" | grep -q "tmux"
}

@test "T-NUDGE-005: real resolver — unresolved CLI falls to the codex-safe long form" {
    export MOCK_PANE_CLI=""
    export HARNESS_CLI_TYPE=""
    run bash -c '
        source "$TEST_HARNESS"
        build_nudge_text 2 2>/dev/null
    '
    [ "$status" -eq 0 ]
    [ "$output" = "You are ashigaru1. Read queue/inbox/ashigaru1.yaml (2 unread), process them, then do queue/tasks/ashigaru1.yaml if its status is assigned." ]
}
