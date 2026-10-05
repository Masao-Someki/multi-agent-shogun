#!/usr/bin/env bash
# Shared agent formation helpers.
#
# `cli.agents` historically served both as per-agent CLI overrides and as the
# runtime formation list. To keep old partial override configs working, a parsed
# list is treated as a formation only when it contains `karo`.
#
# Its YAML key order is deliberately *not* the pane order.  The departure
# script creates panes in command hierarchy order, so all readers of this
# registry must receive that same canonical order regardless of how a user
# groups per-agent CLI settings in settings.yaml.

AGENT_REGISTRY_PROJECT_ROOT="${AGENT_REGISTRY_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
AGENT_REGISTRY_SETTINGS="${AGENT_REGISTRY_SETTINGS:-${SHOGUN_SETTINGS_FILE:-${AGENT_REGISTRY_PROJECT_ROOT}/config/settings.yaml}}"

agent_registry_default_agents() {
    printf '%s\n' \
        shogun \
        karo \
        ashigaru1 \
        ashigaru2 \
        ashigaru3 \
        metsuke \
        tanya \
        gunshi
}

agent_registry_read_agents_from_settings() {
    local settings="${1:-$AGENT_REGISTRY_SETTINGS}"
    [ -f "$settings" ] || return 0

    awk '
        /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }

        /^cli:[[:space:]]*$/ {
            in_cli = 1
            in_agents = 0
            next
        }

        in_cli && /^[^[:space:]]/ {
            in_cli = 0
            in_agents = 0
        }

        in_cli && /^[[:space:]]{2}agents:[[:space:]]*$/ {
            in_agents = 1
            next
        }

        in_agents {
            if ($0 !~ /^[[:space:]]{4}/) {
                exit
            }
            if ($0 ~ /^[[:space:]]{4}[A-Za-z0-9_-]+:[[:space:]]*/) {
                line = $0
                sub(/^[[:space:]]*/, "", line)
                sub(/:.*/, "", line)
                print line
            }
        }
    ' "$settings"
}

agent_registry_has_agent() {
    local wanted="$1"
    shift || true
    local agent
    for agent in "$@"; do
        [ "$agent" = "$wanted" ] && return 0
    done
    return 1
}

agent_registry_emit_canonical_order() {
    # Read agent IDs from stdin and emit the command-layer formation order:
    # shogun (separate session), karo, ashigaru<N>, metsuke, tanya, gunshi.
    # Unknown future roles retain their settings.yaml order after these roles.
    local agents=()
    local agent

    while IFS= read -r agent; do
        [ -n "$agent" ] && agents+=("$agent")
    done

    emit_if_present() {
        local wanted="$1"
        local candidate
        for candidate in "${agents[@]}"; do
            if [ "$candidate" = "$wanted" ]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
        return 0
    }

    emit_if_present shogun
    emit_if_present karo

    # Numeric sorting keeps ashigaru2 before ashigaru10 without depending on
    # non-portable `sort -V`.
    for agent in "${agents[@]}"; do
        if [[ "$agent" =~ ^ashigaru([0-9]+)$ ]]; then
            printf '%s\t%s\n' "${BASH_REMATCH[1]}" "$agent"
        fi
    done | LC_ALL=C sort -n -k1,1 -k2,2 | while IFS=$'\t' read -r rank agent; do
        printf '%s\n' "$agent"
    done

    emit_if_present metsuke
    emit_if_present tanya
    emit_if_present gunshi

    for agent in "${agents[@]}"; do
        case "$agent" in
            shogun|karo|ashigaru[0-9]*|gunshi|metsuke|tanya) continue ;;
        esac
        printf '%s\n' "$agent"
    done
}

agent_registry_agents() {
    local parsed=()
    local agent

    while IFS= read -r agent; do
        [ -n "$agent" ] && parsed+=("$agent")
    done < <(agent_registry_read_agents_from_settings "$AGENT_REGISTRY_SETTINGS")

    if [ "${#parsed[@]}" -eq 0 ] || ! agent_registry_has_agent "karo" "${parsed[@]}"; then
        agent_registry_default_agents
        return 0
    fi

    if ! agent_registry_has_agent "shogun" "${parsed[@]}"; then
        parsed=(shogun "${parsed[@]}")
    fi
    printf '%s\n' "${parsed[@]}" | agent_registry_emit_canonical_order
}

agent_registry_multiagent_agents() {
    local agent
    while IFS= read -r agent; do
        [ "$agent" = "shogun" ] && continue
        printf '%s\n' "$agent"
    done < <(agent_registry_agents)
}

agent_registry_multiagent_pane_for_agent() {
    local wanted="$1"
    local pane_base="${2:-0}"
    local idx=0
    local agent

    while IFS= read -r agent; do
        if [ "$agent" = "$wanted" ]; then
            printf 'multiagent:agents.%s\n' "$((pane_base + idx))"
            return 0
        fi
        idx=$((idx + 1))
    done < <(agent_registry_multiagent_agents)

    return 1
}

agent_registry_pane_for_agent() {
    local agent="$1"
    local pane_base="${2:-0}"

    if [ "$agent" = "shogun" ]; then
        printf '%s\n' "shogun:main.0"
        return 0
    fi

    agent_registry_multiagent_pane_for_agent "$agent" "$pane_base"
}
