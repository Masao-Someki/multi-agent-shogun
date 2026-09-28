#!/usr/bin/env bats

setup() {
    TEST_TMP="$(mktemp -d)"
    PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
}

teardown() {
    rm -rf "$TEST_TMP"
}

@test "qc_target: uses metsuke when the configured formation contains metsuke" {
    cat > "$TEST_TMP/settings.yaml" <<'YAML'
cli:
  agents:
    karo: {type: claude}
    ashigaru1: {type: claude}
    gunshi: {type: claude}
    metsuke: {type: claude}
YAML

    run env SHOGUN_SETTINGS_FILE="$TEST_TMP/settings.yaml" \
        bash "$PROJECT_ROOT/scripts/qc_target.sh"
    [ "$status" -eq 0 ]
    [ "$output" = "metsuke" ]
}

@test "qc_target: falls back to gunshi without metsuke" {
    cat > "$TEST_TMP/settings.yaml" <<'YAML'
cli:
  agents:
    karo: {type: claude}
    ashigaru1: {type: claude}
    gunshi: {type: claude}
YAML

    run env SHOGUN_SETTINGS_FILE="$TEST_TMP/settings.yaml" \
        bash "$PROJECT_ROOT/scripts/qc_target.sh"
    [ "$status" -eq 0 ]
    [ "$output" = "gunshi" ]
}
