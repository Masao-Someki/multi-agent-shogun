#!/usr/bin/env bash
# pane_state_painter.sh — colour each multiagent pane title by whether the agent is working.
#
# Every few seconds this sets the pane option @work_state to "busy" or "idle"
# from the live spinner at the bottom of the pane (see pane_is_working).  The
# multiagent pane-border-format reads @work_state: busy titles are green,
# idle ones grey.  It only sets pane options; it never sends keys.
# When this file changes on disk, the running painter restarts itself with the
# new version, so an edit takes effect without stopping it by hand.
#
# Usage: bash scripts/pane_state_painter.sh   (polls every 10 seconds)

INTERVAL=10  # seconds; fixed so a restart with an old argument keeps it light
SESSION="multiagent"

SELF="${BASH_SOURCE[0]}"
SELF_STAMP=$(ls -l "$SELF" 2>/dev/null)

# pane_is_working <pane_id> — 0 when the bottom of the pane shows a live
# spinner: Codex "• Working (12s • esc to interrupt)" or "• Waiting for
# background terminal (1m 14s • esc…)" (a command such as pytest still runs),
# Claude Code "✻ Thinking… (12s)" or "⏺ Running 1 shell command…".  Blank
# lines are dropped first, because a Codex pane keeps blank rows below its
# status line; narrow panes cut the line short, so match its start.
pane_is_working() {
    tmux capture-pane -t "$1" -p 2>/dev/null \
        | grep -v '^[[:space:]]*$' | tail -n 8 \
        | grep -qE 'esc to interrupt|Working \(|Waiting for background|background terminal running|… \(|Running [0-9]+ .*…'
}

while tmux has-session -t "$SESSION" 2>/dev/null; do
    while read -r pane_id; do
        if pane_is_working "$pane_id"; then
            state="busy"
        else
            state="idle"
        fi
        if [ "$(tmux show-options -p -v -t "$pane_id" @work_state 2>/dev/null)" != "$state" ]; then
            tmux set-option -p -t "$pane_id" @work_state "$state" 2>/dev/null || true
        fi
    done < <(tmux list-panes -t "$SESSION" -F '#{pane_id}' 2>/dev/null)
    sleep "$INTERVAL"
    if [ "$(ls -l "$SELF" 2>/dev/null)" != "$SELF_STAMP" ]; then
        exec bash "$SELF" "$INTERVAL"
    fi
done
