#!/usr/bin/env bats
# Task pool: mark, reconcile, pool_ready and plan_submit.

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export T="$(mktemp -d "$BATS_TMPDIR/poolm.XXXXXX")"
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
    printf 'task_id: %s\nparent_cmd: cmd_x\nproject: p\nbloom_level: L1\nplan_gate: %s\nfiles: [%s.py]\ndepends_on: []\ndescription: |\n  do it\n' \
        "$1" "${2:-false}" "$1" > "$TASK_POOL_DIR/drafts/$1.yaml"
}

pool() {
    bash "$PROJECT_ROOT/scripts/task_pool_$1.sh" "${@:2}"
}

@test "T-POOLM-001 mark done closes the entry and the task YAML" {
    draft t_a; pool add "$TASK_POOL_DIR/drafts/t_a.yaml"; pool claim ashigaru1
    run pool mark t_a done
    [ "$status" -eq 0 ]
    grep -q '^status: done$' "$TASK_POOL_DIR/t_a.yaml"
    grep -q '^  status: done$' "$TASKS_DIR/ashigaru1.yaml"
}

@test "T-POOLM-002 mark done refuses an entry that is not claimed" {
    draft t_a; pool add "$TASK_POOL_DIR/drafts/t_a.yaml"
    run pool mark t_a done
    [ "$status" -eq 2 ]
}

@test "T-POOLM-003 reopen clears claimed_by and bumps attempt" {
    draft t_a; pool add "$TASK_POOL_DIR/drafts/t_a.yaml"; pool claim ashigaru1
    run pool mark t_a reopen
    [ "$status" -eq 0 ]
    grep -q '^status: open$' "$TASK_POOL_DIR/t_a.yaml"
    grep -q "^claimed_by: ''$" "$TASK_POOL_DIR/t_a.yaml"
    grep -q '^attempt: 2$' "$TASK_POOL_DIR/t_a.yaml"
}

@test "T-POOLM-004 reconcile reopens a claim whose task YAML moved on" {
    draft t_a; pool add "$TASK_POOL_DIR/drafts/t_a.yaml"; pool claim ashigaru1
    printf 'task:\n  task_id: other\n  status: assigned\n' > "$TASKS_DIR/ashigaru1.yaml"
    run pool mark --reconcile
    [ "$status" -eq 0 ]
    grep -q '^status: open$' "$TASK_POOL_DIR/t_a.yaml"
}

@test "T-POOLM-005 pool_ready goes only to idle ashigaru" {
    printf 'task:\n  task_id: busy\n  status: assigned\n' > "$TASKS_DIR/ashigaru2.yaml"
    draft t_a; run pool add "$TASK_POOL_DIR/drafts/t_a.yaml"
    [ "$status" -eq 0 ]
    [ "$(cat "$T/inbox.log")" = "ashigaru1 pool_ready" ]
}

@test "T-POOLM-006 plan_submit sets submitted and sends one plan_submitted" {
    draft t_a true; pool add "$TASK_POOL_DIR/drafts/t_a.yaml"; pool claim ashigaru1
    printf '  plan:\n  - step: 1\n    do: x\n' >> "$TASKS_DIR/ashigaru1.yaml"
    : > "$T/inbox.log"
    run bash "$PROJECT_ROOT/scripts/plan_submit.sh" ashigaru1
    [ "$status" -eq 0 ]
    grep -q '^  plan_status: submitted$' "$TASKS_DIR/ashigaru1.yaml"
    [ "$(cat "$T/inbox.log")" = "kumigashira plan_submitted" ]
}

@test "T-POOLM-007 mark done refuses a task claimed by another ashigaru" {
    draft t_a; draft t_b
    pool add "$TASK_POOL_DIR/drafts/t_a.yaml" "$TASK_POOL_DIR/drafts/t_b.yaml"
    pool claim ashigaru1; pool claim ashigaru2
    run pool mark t_b done ashigaru1
    [ "$status" -ne 0 ]
    grep -q '^status: claimed$' "$TASK_POOL_DIR/t_b.yaml"
    grep -q '^  status: assigned$' "$TASKS_DIR/ashigaru2.yaml"
}
