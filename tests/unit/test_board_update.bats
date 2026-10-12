#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export BOARD_DIR="$(mktemp -d "$BATS_TMPDIR/board.XXXXXX")"
}

teardown() {
    rm -rf "$BOARD_DIR"
}

update() {
    bash "$PROJECT_ROOT/scripts/board_update.sh" --no-render "$@"
}

@test "T-BOARD-001 creates the agent file with the given keys" {
    run update ashigaru1 task_id=t1 step=1/3
    [ "$status" -eq 0 ]
    grep -q '^task_id: t1$' "$BOARD_DIR/ashigaru1.yaml"
    grep -q '^step: 1/3$' "$BOARD_DIR/ashigaru1.yaml"
}

@test "T-BOARD-002 updating one key keeps the others" {
    update ashigaru1 task_id=t1 step=1/3
    run update ashigaru1 step=2/3
    [ "$status" -eq 0 ]
    grep -q '^task_id: t1$' "$BOARD_DIR/ashigaru1.yaml"
    grep -q '^step: 2/3$' "$BOARD_DIR/ashigaru1.yaml"
    [ "$(grep -c '^step: ' "$BOARD_DIR/ashigaru1.yaml")" -eq 1 ]
}

@test "T-BOARD-003 sets updated" {
    run update karo note=x
    [ "$status" -eq 0 ]
    grep -q '^updated: 20' "$BOARD_DIR/karo.yaml"
}

@test "T-BOARD-004 an empty value clears the key" {
    update ashigaru1 note=x
    run update ashigaru1 note=
    [ "$status" -eq 0 ]
    run grep -c '^note: ' "$BOARD_DIR/ashigaru1.yaml"
    [ "$output" = "0" ]
}

@test "T-BOARD-005 rejects an unknown agent" {
    run update nobody note=x
    [ "$status" -eq 2 ]
    [[ "$output" == *"unknown agent"* ]]
}

@test "T-BOARD-006 rejects an unknown key" {
    run update ashigaru1 color=red
    [ "$status" -eq 2 ]
    [[ "$output" == *"unknown key"* ]]
}

@test "T-BOARD-007 removes its lock dir" {
    run update ashigaru1 note=x
    [ "$status" -eq 0 ]
    [ ! -d "$BOARD_DIR/ashigaru1.yaml.lock.d" ]
}

@test "T-BOARD-008 --no-render writes no board.md" {
    run update ashigaru1 note=x
    [ "$status" -eq 0 ]
    [ ! -f "$BOARD_DIR/board.md" ]
}


@test "T-BOARD-009 accepts ashigaru10" {
    run update ashigaru10 note=x
    [ "$status" -eq 0 ]
    grep -q '^note: x$' "$BOARD_DIR/ashigaru10.yaml"
}
