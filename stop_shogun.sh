#!/usr/bin/env bash
# Stop only this checkout's Shogun formation and its background services.
# The tmux server itself is left running so unrelated sessions are preserved.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
ASSUME_YES=false

usage() {
    cat <<'EOF'
Usage: ./stop_shogun.sh [--dry-run] [--yes]

Stops this checkout's inbox watchers, watcher supervisor, ntfy listener, and
Shogun tmux sessions (shogun, multiagent, shogun-<pid>, multi-<pid>).
The tmux server and unrelated tmux sessions are preserved.

  --dry-run  Show what would be stopped without changing anything
  --yes      Skip the interactive confirmation
EOF
}

while (($#)); do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --yes|-y) ASSUME_YES=true ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

declare -a SESSION_NAMES=()
declare -a SERVICE_ROOTS=()

if command -v tmux >/dev/null 2>&1; then
    while IFS= read -r session; do
        case "$session" in
            shogun|multiagent|shogun-[0-9]*|multi-[0-9]*)
                SESSION_NAMES+=("$session")
                ;;
        esac
    done < <(tmux list-sessions -F '#{session_name}' 2>/dev/null || true)
fi

find_service_roots() {
    local path process_id command_line
    local -a service_paths=(
        "$SCRIPT_DIR/scripts/inbox_watcher.sh"
        "$SCRIPT_DIR/scripts/watcher_supervisor.sh"
        "$SCRIPT_DIR/scripts/ntfy_listener.sh"
    )

    while read -r process_id command_line; do
        [[ "$process_id" =~ ^[0-9]+$ ]] || continue
        [[ "$process_id" == "$$" || "$process_id" == "$PPID" ]] && continue
        [[ "$command_line" == *"$SCRIPT_DIR/stop_shogun.sh"* ]] && continue
        for path in "${service_paths[@]}"; do
            if [[ "$command_line" == *"$path"* ]]; then
                SERVICE_ROOTS+=("$process_id")
                break
            fi
        done
    done < <(ps -axo pid=,command= 2>/dev/null || ps -eo pid=,args= 2>/dev/null || true)
}

print_plan() {
    printf 'Shogun tmux sessions:\n'
    if ((${#SESSION_NAMES[@]})); then
        printf '  %s\n' "${SESSION_NAMES[@]}"
    else
        printf '  none\n'
    fi
    printf 'Shogun background service PIDs:\n'
    if ((${#SERVICE_ROOTS[@]})); then
        printf '  %s\n' "${SERVICE_ROOTS[@]}"
    else
        printf '  none\n'
    fi
}

find_service_roots
print_plan

if [[ "$DRY_RUN" == true ]]; then
    exit 0
fi

if [[ "$ASSUME_YES" != true ]]; then
    read -r -p 'Stop these Shogun sessions and services? [y/N] ' answer
    case "$answer" in
        y|Y|yes|YES) ;;
        *) echo 'Cancelled.'; exit 0 ;;
    esac
fi

descendants_of() {
    local parent="$1" child
    while IFS= read -r child; do
        [[ "$child" =~ ^[0-9]+$ ]] || continue
        descendants_of "$child"
        printf '%s\n' "$child"
    done < <(pgrep -P "$parent" 2>/dev/null || true)
}

declare -a STOP_PIDS=()
for root_pid in "${SERVICE_ROOTS[@]}"; do
    while IFS= read -r child_pid; do
        [[ "$child_pid" =~ ^[0-9]+$ ]] && STOP_PIDS+=("$child_pid")
    done < <(descendants_of "$root_pid")
    STOP_PIDS+=("$root_pid")
done

# Deduplicate PIDs; a detached watcher may also be found as a process root.
declare -a UNIQUE_PIDS=()
for process_id in "${STOP_PIDS[@]}"; do
    seen=false
    for existing_pid in "${UNIQUE_PIDS[@]:-}"; do
        if [[ "$existing_pid" == "$process_id" ]]; then
            seen=true
            break
        fi
    done
    [[ "$seen" == true ]] || UNIQUE_PIDS+=("$process_id")
done

if ((${#UNIQUE_PIDS[@]})); then
    echo 'Stopping Shogun background services...'
    kill -TERM "${UNIQUE_PIDS[@]}" 2>/dev/null || true

    for _ in {1..50}; do
        remaining=false
        for process_id in "${UNIQUE_PIDS[@]}"; do
            if kill -0 "$process_id" 2>/dev/null; then
                remaining=true
                break
            fi
        done
        [[ "$remaining" == true ]] || break
        sleep 0.1
    done

    for process_id in "${UNIQUE_PIDS[@]}"; do
        if kill -0 "$process_id" 2>/dev/null; then
            echo "Force-stopping unresponsive service PID $process_id"
            kill -KILL "$process_id" 2>/dev/null || true
        fi
    done
fi

for session in "${SESSION_NAMES[@]}"; do
    echo "Stopping tmux session: $session"
    tmux kill-session -t "$session" 2>/dev/null || true
done

echo 'Shogun sessions and background services stopped.'
