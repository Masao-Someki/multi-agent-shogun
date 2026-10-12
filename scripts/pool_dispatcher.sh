#!/usr/bin/env bash
# pool_dispatcher.sh — hand open task-pool work to idle ashigaru, like inbox_watcher for the pool.
#
# Every few seconds, for each ashigaru whose pane is idle and whose task YAML
# holds no assigned task, it runs scripts/task_pool_claim.sh on the ashigaru's
# behalf (same lock, same depends_on and file-overlap rules) and, when a task
# was claimed, sends one task_assigned inbox message.  The ashigaru then only
# has to read its task YAML.  An ashigaru that holds an assigned task but sits
# idle (for example after a restart) gets a reminder every 10 minutes.  It is a script, not an LLM: it never edits code,
# never sends keys, and stops when the multiagent session ends.  When this file
# changes on disk the running dispatcher restarts itself with the new version.
#
# Usage: bash scripts/pool_dispatcher.sh [interval_seconds]   (default 20)

INTERVAL="${1:-20}"
SESSION="multiagent"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="${BASH_SOURCE[0]}"
SELF_STAMP=$(ls -l "$SELF" 2>/dev/null)
REMIND_SECONDS=600
STATE_DIR="$ROOT/logs/pool_dispatcher_state"
mkdir -p "$STATE_DIR"

# pane_is_working <pane_id> — same live-spinner test as pane_state_painter.sh.
pane_is_working() {
    tmux capture-pane -t "$1" -p 2>/dev/null \
        | grep -v '^[[:space:]]*$' | tail -n 8 \
        | grep -qE 'esc to interrupt|Working \(|Waiting for background|background terminal running|… \(|Running [0-9]+ .*…'
}

log() { echo "[$(date '+%F %T')] $*"; }

while tmux has-session -t "$SESSION" 2>/dev/null; do
    # The live formation, so a station's kind falls back to any ashigaru when
    # its owner (e.g. ashigaru10 in the Claude formation) is not running.
    POOL_PRESENT_AGENTS=$(tmux list-panes -t "$SESSION" -F '#{@agent_id}' 2>/dev/null | tr '\n' ' ')
    export POOL_PRESENT_AGENTS
    while read -r pane_id agent; do
        case "$agent" in ashigaru[0-9]*) ;; *) continue ;; esac
        pane_is_working "$pane_id" && continue
        # A pool task the ashigaru finished (status done) but never marked:
        # mark it done so its files and dependants are freed.
        yaml="$ROOT/queue/tasks/$agent.yaml"
        cur_id=$(grep -m1 -E '^[[:space:]]+task_id:' "$yaml" 2>/dev/null | awk '{print $2}')
        cur_st=$(grep -m1 -E '^[[:space:]]+status:' "$yaml" 2>/dev/null | awk '{print $2}')
        if [ "$cur_st" = "done" ] && [ -n "$cur_id" ] \
            && bash "$ROOT/scripts/task_pool_list.sh" claimed 2>/dev/null \
                | awk -v id="$cur_id" -v a="$agent" '$2 == id && $3 == a { f = 1 } END { exit !f }'; then
            bash "$ROOT/scripts/task_pool_mark.sh" "$cur_id" done "$agent" >/dev/null 2>&1 \
                && log "marked $cur_id done for $agent"
        fi
        # An assigned task with an idle pane (for example after a restart):
        # remind the ashigaru once every REMIND_SECONDS, unless its inbox
        # already holds unread mail or the plan waits on kumigashira.
        if [ "$cur_st" = "assigned" ]; then
            plan=$(grep -m1 -E '^[[:space:]]+plan_status:' "$yaml" 2>/dev/null | awk '{print $2}')
            stamp="$STATE_DIR/$agent.reminded"
            last=$(cat "$stamp" 2>/dev/null || echo 0)
            now=$(date +%s)
            if [ "$plan" != "submitted" ] \
                && ! grep -q 'read: false' "$ROOT/queue/inbox/$agent.yaml" 2>/dev/null \
                && [ $((now - last)) -ge "$REMIND_SECONDS" ]; then
                echo "$now" > "$stamp"
                log "reminded $agent of $cur_id"
                bash "$ROOT/scripts/inbox_write.sh" "$agent" \
                    "You are $agent. Your task $cur_id in queue/tasks/$agent.yaml is still assigned and nobody is working on it. Continue it now." \
                    task_assigned pool_dispatcher >/dev/null 2>&1 \
                    || log "inbox_write to $agent failed"
            fi
            continue
        fi
        # claim prints the task_id on the first line and, for a plan-gated
        # task, a hint about plan_submit.sh on the next one.
        out=$(bash "$ROOT/scripts/task_pool_claim.sh" "$agent" 2>/dev/null)
        rc=$?
        task_id=$(printf '%s\n' "$out" | head -n 1)
        [ "$rc" -eq 0 ] && [ -n "$task_id" ] || continue
        hint=$(printf '%s\n' "$out" | sed -n '2,$p' | tr '\n' ' ')
        log "claimed $task_id for $agent"
        bash "$ROOT/scripts/inbox_write.sh" "$agent" \
            "You are $agent. Pool task $task_id is now in queue/tasks/$agent.yaml. Do it. ${hint}When it is done, run: bash scripts/task_pool_mark.sh $task_id done $agent" \
            task_assigned pool_dispatcher >/dev/null 2>&1 \
            || log "inbox_write to $agent failed"
    done < <(tmux list-panes -t "$SESSION" -F '#{pane_id} #{@agent_id}' 2>/dev/null)
    sleep "$INTERVAL"
    if [ "$(ls -l "$SELF" 2>/dev/null)" != "$SELF_STAMP" ]; then
        exec bash "$SELF" "$INTERVAL"
    fi
done
