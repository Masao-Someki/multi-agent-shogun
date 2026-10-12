#!/usr/bin/env bats
# Task start: lifecycle and pool integration.

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export T="$(mktemp -d "$BATS_TMPDIR/taskstart.XXXXXX")"
    export TASK_POOL_DIR="$T/pool" TASKS_DIR="$T/tasks" REPORTS_DIR="$T/reports" PLANS_DIR="$T/plans" CHECKS_DIR="$T/checks"
    export POOL_AGENTS="ashigaru1"
    mkdir -p "$TASK_POOL_DIR/drafts" "$TASKS_DIR" "$REPORTS_DIR" "$PLANS_DIR" "$CHECKS_DIR"
    printf '#!/usr/bin/env bash\nexit 0\n' > "$T/board.sh"
    printf '#!/usr/bin/env bash\necho "$1 $3" >> "%s/inbox.log"\n' "$T" > "$T/inbox.sh"
    export BOARD_UPDATE="$T/board.sh" INBOX_WRITE="$T/inbox.sh" QC_TARGET=metsuke
    unset TMUX_PANE

    # Throwaway git repo
    cd "$T"
    git init -q
    touch dummy
    git add dummy
    git commit -m "init" -q > /dev/null
    cd "$PROJECT_ROOT"
}

teardown() {
    rm -rf "$T"
}

draft() {
    # draft <task_id> [plan_gate]
    local tid="$1"
    local gate="${2:-false}"
    printf 'task_id: %s\nparent_cmd: cmd_x\nproject: p\nbloom_level: L1\nplan_gate: %s\nfiles: []\ndepends_on: []\ndescription: |\n  do it\n' \
        "$tid" "$gate" > "$TASK_POOL_DIR/drafts/$tid.yaml"
}

pool() {
    bash "$PROJECT_ROOT/scripts/task_pool_$1.sh" "${@:2}"
}

run_task_start() {
    bash "$PROJECT_ROOT/scripts/task_start.sh" "$@"
}

write_task() {
    # write_task <agent> <task_id> <plan_status> [plan_gate]
    local agent="$1" tid="$2" plan_status="$3" gate="${4:-true}"
    printf 'task:\n  task_id: %s\n  parent_cmd: cmd_x\n  project: p\n  bloom_level: L1\n  pool: true\n  plan_gate: %s\n  plan_status: %s\n  files: []\n  description: do it\n  status: assigned\n' \
        "$tid" "$gate" "$plan_status" > "$TASKS_DIR/$agent.yaml"
}

@test "idle when no task and the pool is empty" {
    run run_task_start ashigaru1
    [ "$status" -eq 1 ]
    [[ "$output" == *"idle: no task"* ]]
}

@test "start claims from the pool and prints the brief" {
    draft t1
    pool add "$TASK_POOL_DIR/drafts/t1.yaml"

    run run_task_start ashigaru1
    [ "$status" -eq 0 ]
    [[ "$output" == *"task t1"* ]]
    grep -q "status: in_progress" "$TASKS_DIR/ashigaru1.yaml"
}

@test "waived gives exit 0 with start work and status in_progress" {
    write_task ashigaru1 t2 waived false
    run run_task_start ashigaru1
    [ "$status" -eq 0 ]
    [[ "$output" == *"no plan gate: start work"* ]]
    grep -q "status: in_progress" "$TASKS_DIR/ashigaru1.yaml"
}

@test "pending without --plan gives exit 10" {
    write_task ashigaru1 t3 pending
    run run_task_start ashigaru1
    [ "$status" -eq 10 ]
    [[ "$output" == *"plan gate: write your plan"* ]]
}

@test "--plan stores plan, sets plan_status submitted, and logs to inbox" {
    write_task ashigaru1 t4 pending
    printf "1. do it | files: none | verify: true | expect: ok\n" > "$T/my_plan.txt"
    run run_task_start ashigaru1 --plan "$T/my_plan.txt"
    [ "$status" -eq 0 ]
    [[ "$output" == *"submitted: wait for the plan_approved message"* ]]
    grep -q "plan_status: submitted" "$TASKS_DIR/ashigaru1.yaml"
    grep -q "plan: |" "$TASKS_DIR/ashigaru1.yaml"
    grep -q "kumigashira plan_submitted" "$T/inbox.log"
}

@test "--plan file that lacks a verify line gives exit 4" {
    write_task ashigaru1 t5 pending
    printf "1. do it | files: none | expect: ok\n" > "$T/bad_plan.txt"
    run run_task_start ashigaru1 --plan "$T/bad_plan.txt"
    [ "$status" -eq 4 ]
}

@test "submitted again gives exit 11 and no second inbox line" {
    write_task ashigaru1 t6 submitted
    : > "$T/inbox.log"
    run run_task_start ashigaru1
    [ "$status" -eq 11 ]
    [ "$(cat "$T/inbox.log")" = "" ]
}

@test "approved prints approved: start work" {
    write_task ashigaru1 t7 approved
    run run_task_start ashigaru1
    [ "$status" -eq 0 ]
    [[ "$output" == *"approved: start work"* ]]
    grep -q "status: in_progress" "$TASKS_DIR/ashigaru1.yaml"
}

@test "wrong agent id gives exit 2" {
    write_task wrong_agent t8 waived false
    mkdir -p "$T/bin"
    printf '#!/bin/bash\necho "other_agent"\n' > "$T/bin/tmux"
    chmod +x "$T/bin/tmux"
    export PATH="$T/bin:$PATH"
    export TMUX_PANE="pane0"

    run run_task_start wrong_agent
    [ "$status" -eq 2 ]
    [[ "$output" == *"refused: you are other_agent, not wrong_agent"* ]]
}

@test "stray top-level key is dropped" {
    printf 'task:\n  task_id: t9\n  parent_cmd: cmd_x\n  project: p\n  bloom_level: L1\n  pool: true\n  plan_gate: false\n  plan_status: waived\n  files: []\n  description: do it\n  status: assigned\nstatus: done\n' \
        > "$TASKS_DIR/ashigaru1.yaml"
    run run_task_start ashigaru1
    [ "$status" -eq 0 ]
    grep -q "task_id: t9" "$TASKS_DIR/ashigaru1.yaml"
    run grep -c '^status:' "$TASKS_DIR/ashigaru1.yaml"
    [ "$output" -eq 0 ]
}

@test "syntax check runs bin-bash -n and bash -n on scripts/task_start.sh" {
    run bash -n "$PROJECT_ROOT/scripts/task_start.sh"
    [ "$status" -eq 0 ]
    run /bin/bash -n "$PROJECT_ROOT/scripts/task_start.sh"
    [ "$status" -eq 0 ]
}
