#!/usr/bin/env bats
# agent_is_busy_check on narrow (32-column) codex panes. No real tmux: tmux and timeout are shell functions.

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export MOCK_CAPTURE_PANE=""
    tmux() {
        case "$*" in
            *display-message*) echo "%1"; return 0 ;;
            *capture-pane*) printf '%s\n' "$MOCK_CAPTURE_PANE"; return 0 ;;
            *show-options*) echo "codex"; return 0 ;;
        esac
        return 0
    }
    timeout() { shift; "$@"; }
    source "$PROJECT_ROOT/lib/agent_status.sh"
}


@test "T-NARROW-001 busy: truncated Working line at 32 columns" {
    MOCK_CAPTURE_PANE=$'• Working (2m 50s • esc to inter…\n\n\n› Ask Codex to do anything\n\n  shogun-worker high · ~/mul…'
    run agent_is_busy_check "%1" codex
    [ "$status" -eq 0 ]
}

@test "T-NARROW-002 busy: Working line wrapped at 32 columns" {
    MOCK_CAPTURE_PANE=$'• Working (2m 50s • esc to\ninterrupt) · 1 background\n\n\n› Ask Codex to do anything\n\n  shogun-worker high · ~/mul…'
    run agent_is_busy_check "%1" codex
    [ "$status" -eq 0 ]
}


@test "T-NARROW-003 idle: Worked line and the input prompt" {
    MOCK_CAPTURE_PANE=$'• Worked for 2m 19s\n\n› Ask Codex to do anything\n\n  shogun-worker high · ~/mul…'
    run agent_is_busy_check "%1" codex
    [ "$status" -eq 1 ]
}

@test "T-NARROW-004 idle: an old Working line far above is ignored" {
    MOCK_CAPTURE_PANE=$'• Working (1m • esc to interrupt)\na\nb\nc\nd\ne\nf\ng\nh\ni\nj\n• Worked for 1m\n\n› Ask Codex to do anything\n\n  shogun-worker high · ~/mul…'
    run agent_is_busy_check "%1" codex
    [ "$status" -eq 1 ]
}
