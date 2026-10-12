#!/usr/bin/env bats
# Task pool: add and claim (scripts/task_pool.py through its shell wrappers).

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export T="$(mktemp -d "$BATS_TMPDIR/pool.XXXXXX")"
    export TASK_POOL_DIR="$T/pool" TASKS_DIR="$T/tasks" POOL_AGENTS="ashigaru1 ashigaru2"
    mkdir -p "$TASK_POOL_DIR/drafts" "$TASKS_DIR"
    printf '#!/usr/bin/env bash\nexit 0\n' > "$T/board.sh"
    printf '#!/usr/bin/env bash\necho "$1 $3" >> "%s/inbox.log"\n' "$T" > "$T/inbox.sh"
    export BOARD_UPDATE="$T/board.sh" INBOX_WRITE="$T/inbox.sh"
}

teardown() {
    rm -rf "$T"
}

draft() {
    # draft <task_id> <file> [depends_on]
    printf 'task_id: %s\nparent_cmd: cmd_x\nproject: p\nbloom_level: L1\nplan_gate: false\nfiles: [%s]\ndepends_on: [%s]\ndescription: |\n  do it\n' \
        "$1" "$2" "${3:-}" > "$TASK_POOL_DIR/drafts/$1.yaml"
}

pool() {
    bash "$PROJECT_ROOT/scripts/task_pool_$1.sh" "${@:2}"
}

@test "T-POOL-001 add creates an open entry and removes the draft" {
    draft t_a a.py
    run pool add "$TASK_POOL_DIR/drafts/t_a.yaml"
    [ "$status" -eq 0 ]
    grep -q '^status: open$' "$TASK_POOL_DIR/t_a.yaml"
    grep -q '^created: ' "$TASK_POOL_DIR/t_a.yaml"
    [ ! -f "$TASK_POOL_DIR/drafts/t_a.yaml" ]
}

@test "T-POOL-002 claim takes the oldest open task and writes the task YAML" {
    draft t_a a.py; draft t_b b.py
    pool add "$TASK_POOL_DIR/drafts/t_a.yaml" "$TASK_POOL_DIR/drafts/t_b.yaml"
    run pool claim ashigaru1
    [ "$status" -eq 0 ]
    [ "$output" = "t_a" ]
    grep -q '^  status: assigned$' "$TASKS_DIR/ashigaru1.yaml"
    grep -q '^  plan_status: waived$' "$TASKS_DIR/ashigaru1.yaml"
}

@test "T-POOL-003 claim skips a task whose depends_on is not done" {
    draft t_a a.py; draft t_b b.py t_a
    pool add "$TASK_POOL_DIR/drafts/t_a.yaml" "$TASK_POOL_DIR/drafts/t_b.yaml"
    pool claim ashigaru1
    run pool claim ashigaru2
    [ "$status" -eq 1 ]
}

@test "T-POOL-004 claim skips a task whose files overlap a claimed one" {
    draft t_a same.py; draft t_b same.py
    pool add "$TASK_POOL_DIR/drafts/t_a.yaml" "$TASK_POOL_DIR/drafts/t_b.yaml"
    pool claim ashigaru1
    run pool claim ashigaru2
    [ "$status" -eq 1 ]
}

@test "T-POOL-005 two claims at once get two different tasks" {
    draft t_a a.py; draft t_b b.py
    pool add "$TASK_POOL_DIR/drafts/t_a.yaml" "$TASK_POOL_DIR/drafts/t_b.yaml"
    pool claim ashigaru1 > "$T/c1" & pool claim ashigaru2 > "$T/c2" & wait
    [ "$(cat "$T/c1" "$T/c2" | sort | tr '\n' ' ')" = "t_a t_b " ]
}

@test "T-POOL-006 an empty pool exits 1 with no output" {
    run pool claim ashigaru1
    [ "$status" -eq 1 ]
    [ -z "$output" ]
}

@test "T-POOL-007 claim refuses while the agent still has an assigned task" {
    draft t_a a.py; draft t_b b.py
    pool add "$TASK_POOL_DIR/drafts/t_a.yaml" "$TASK_POOL_DIR/drafts/t_b.yaml"
    pool claim ashigaru1
    run pool claim ashigaru1
    [ "$status" -eq 3 ]
    [ "$output" = "t_a" ]
}
