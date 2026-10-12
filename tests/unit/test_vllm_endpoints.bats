#!/usr/bin/env bats
# test_vllm_endpoints.bats — vllm-workers profile: ten Ashigaru, two pinned vLLM servers
#
# Sources the real lib/cli_adapter.sh against the real
# config/model_profiles/vllm-workers.yaml.  No pane, server or key is touched;
# the API key is a dummy and only the generated codex command line is checked.
#
# Cases:
#   T-VEP-001: two servers — odd ashigaru and tanya on VLLM_BASE_URL, even and tanya2 on VLLM_BASE_URL_2
#   T-VEP-002: one server — VLLM_BASE_URL_2 unset, every worker falls back to VLLM_BASE_URL
#   T-VEP-003: one server — VLLM_BASE_URL_2 set but empty also falls back
#   T-VEP-004: the profile lists ashigaru1..ashigaru10 in numeric order
#   T-VEP-005: the profile asks for ten Ashigaru

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export PROFILE="$PROJECT_ROOT/config/model_profiles/vllm-workers.yaml"
    [ -f "$PROFILE" ]
    export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
    export VLLM_MODEL_ID="shogun-worker"
    export VLLM_API_KEY="dummy-key"
    unset VLLM_BASE_URL_2
}

# base_url_for <agent_id> — the base_url baked into that agent's codex command
base_url_for() {
    bash -c '
        export CLI_ADAPTER_PROJECT_ROOT="$PROJECT_ROOT" CLI_ADAPTER_SETTINGS="$PROFILE"
        source "$PROJECT_ROOT/lib/cli_adapter.sh"
        build_cli_command "$1"
    ' _ "$1" | grep -oE 'base_url="[^"]*"' | head -1
}

@test "T-VEP-001: two servers — each worker is pinned to its own server" {
    export VLLM_BASE_URL_2="http://127.0.0.1:8001/v1"
    for a in ashigaru1 ashigaru3 ashigaru5 ashigaru7 ashigaru9 tanya; do
        [ "$(base_url_for "$a")" = 'base_url="http://127.0.0.1:8000/v1"' ]
    done
    for a in ashigaru2 ashigaru4 ashigaru6 ashigaru8 ashigaru10 tanya2; do
        [ "$(base_url_for "$a")" = 'base_url="http://127.0.0.1:8001/v1"' ]
    done
}

@test "T-VEP-002: one server — unset VLLM_BASE_URL_2 falls back to VLLM_BASE_URL" {
    for a in ashigaru1 ashigaru2 ashigaru10 tanya2; do
        [ "$(base_url_for "$a")" = 'base_url="http://127.0.0.1:8000/v1"' ]
    done
}

@test "T-VEP-003: one server — empty VLLM_BASE_URL_2 also falls back" {
    export VLLM_BASE_URL_2=""
    [ "$(base_url_for ashigaru2)" = 'base_url="http://127.0.0.1:8000/v1"' ]
}

@test "T-VEP-004: the profile lists ashigaru1..ashigaru10 in numeric order" {
    run bash -c '
        export CLI_ADAPTER_PROJECT_ROOT="$PROJECT_ROOT" CLI_ADAPTER_SETTINGS="$PROFILE"
        source "$PROJECT_ROOT/lib/cli_adapter.sh"
        get_ashigaru_ids
    '
    [ "$status" -eq 0 ]
    [ "$output" = "ashigaru1 ashigaru2 ashigaru3 ashigaru4 ashigaru5 ashigaru6 ashigaru7 ashigaru8 ashigaru9 ashigaru10" ]
}

@test "T-VEP-005: the profile asks for ten Ashigaru" {
    run "$PROJECT_ROOT/.venv/bin/python3" -c '
import sys, yaml
print(yaml.safe_load(open(sys.argv[1]))["formation"]["ashigaru_count"])
' "$PROFILE"
    [ "$status" -eq 0 ]
    [ "$output" = "10" ]
}
