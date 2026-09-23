#!/usr/bin/env bash
# Persistent, role-scoped session pool for Claude Code and Codex.
#
# Each role/CLI pair has exactly one locally stored session identifier.  The
# state directory is intentionally runtime-only: it can contain private local
# identifiers and must never be committed.

SESSION_POOL_DIR="${SESSION_POOL_DIR:-${CLI_ADAPTER_PROJECT_ROOT}/runtime/session_pool}"
SESSION_POOL_LOG="${SESSION_POOL_LOG:-${CLI_ADAPTER_PROJECT_ROOT}/logs/session_pool.log}"

session_pool_path() {
    local agent_id="$1"
    local cli_type="$2"
    printf '%s/%s.%s.id\n' "$SESSION_POOL_DIR" "$agent_id" "$cli_type"
}

session_pool_read_id() {
    local path
    path=$(session_pool_path "$1" "$2")
    [ -f "$path" ] || return 1
    local session_id
    session_id=$(tr -d '[:space:]' < "$path")
    [[ "$session_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || return 1
    printf '%s\n' "$session_id"
}

session_pool_write_id() {
    local agent_id="$1"
    local cli_type="$2"
    local session_id="$3"
    [[ "$session_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || return 1

    mkdir -p "$SESSION_POOL_DIR"
    chmod 700 "$SESSION_POOL_DIR" 2>/dev/null || true
    local path tmp
    path=$(session_pool_path "$agent_id" "$cli_type")
    tmp="${path}.tmp.$$"
    umask 077
    printf '%s\n' "$session_id" > "$tmp"
    mv "$tmp" "$path"
}

session_pool_new_uuid() {
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen | tr '[:upper:]' '[:lower:]'
    else
        "$CLI_ADAPTER_PROJECT_ROOT/.venv/bin/python3" -c 'import uuid; print(uuid.uuid4())'
    fi
}

session_pool_session_exists() {
    local cli_type="$1"
    local session_id="$2"
    case "$cli_type" in
        claude)
            find "$HOME/.claude/projects" -type f -name "${session_id}.jsonl" -print -quit 2>/dev/null | grep -q .
            ;;
        codex)
            rg -l --fixed-strings -- "\"session_id\":\"${session_id}\"" "${CODEX_HOME:-$HOME/.codex}/sessions" 2>/dev/null | head -n 1 | grep -q .
            ;;
        *)
            return 1
            ;;
    esac
}

session_pool_log() {
    mkdir -p "$(dirname "$SESSION_POOL_LOG")"
    printf '[%s] %s\n' "$(date -Iseconds)" "$*" >> "$SESSION_POOL_LOG"
}

# Codex creates its UUID internally.  The initial prompt contains an opaque
# marker, so this process can find the exact new rollout even if other Codex
# sessions are active on the same machine.
session_pool_capture_codex_id() {
    local agent_id="$1"
    local marker="$2"
    local codex_dir="${CODEX_HOME:-$HOME/.codex}"
    local session_file session_id attempt

    for attempt in $(seq 1 60); do
        session_file=$(rg -l --fixed-strings -- "$marker" "$codex_dir/sessions" 2>/dev/null | head -n 1 || true)
        if [ -n "$session_file" ]; then
            session_id=$(sed -n 's/.*"session_id":"\([^"]*\)".*/\1/p' "$session_file" | head -n 1)
            if [[ "$session_id" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
                session_pool_write_id "$agent_id" codex "$session_id"
                session_pool_log "saved Codex session for ${agent_id}: ${session_id}"
                return 0
            fi
        fi
        sleep 1
    done

    session_pool_log "could not capture Codex session for ${agent_id}; next launch will create a new one"
    return 1
}

# Print a CLI command for the role.  A session is never shared between roles
# or between providers; ashigaru1 and ashigaru2 therefore have different IDs.
build_pooled_cli_command() {
    local agent_id="$1"
    local cli_type
    cli_type=$(get_cli_type "$agent_id")
    local session_id base marker

    if session_id=$(session_pool_read_id "$agent_id" "$cli_type") \
        && session_pool_session_exists "$cli_type" "$session_id"; then
        base=$(CLI_ADAPTER_SKIP_STARTUP_PROMPT=true build_cli_command "$agent_id")
        case "$cli_type" in
            claude)
                printf '%s\n' "${base/claude /claude --resume ${session_id} }"
                ;;
            codex)
                printf '%s\n' "${base/codex /codex resume ${session_id} }"
                ;;
            *)
                printf '%s\n' "$base"
                ;;
        esac
        session_pool_log "resuming ${cli_type} session for ${agent_id}: ${session_id}"
        return 0
    fi

    session_pool_log "creating a new ${cli_type} session for ${agent_id}"

    case "$cli_type" in
        claude)
            session_id=$(session_pool_new_uuid)
            session_pool_write_id "$agent_id" claude "$session_id"
            base=$(CLI_ADAPTER_SKIP_STARTUP_PROMPT=true build_cli_command "$agent_id")
            printf '%s\n' "$base --session-id ${session_id}"
            session_pool_log "created Claude session for ${agent_id}: ${session_id}"
            ;;
        codex)
            marker="session-pool-${agent_id}-$(session_pool_new_uuid)"
            base=$(SESSION_POOL_MARKER="$marker" build_cli_command "$agent_id")
            session_pool_capture_codex_id "$agent_id" "$marker" >/dev/null 2>&1 &
            printf '%s\n' "$base"
            session_pool_log "creating Codex session for ${agent_id}; capture pending"
            ;;
        *)
            build_cli_command "$agent_id"
            ;;
    esac
}

# The pool deliberately retains worker context.  A new assignment is delivered
# as an inbox nudge and task YAML update, rather than a slash-command reset.
session_pool_preserves_context() {
    return 0
}
