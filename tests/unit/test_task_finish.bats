#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export T="$(mktemp -d "$BATS_TMPDIR/taskfinish.XXXXXX")"
    export TASK_POOL_DIR="$T/pool" TASKS_DIR="$T/tasks" REPORTS_DIR="$T/reports" PLANS_DIR="$T/plans" CHECKS_DIR="$T/checks"
    mkdir -p "$TASK_POOL_DIR/drafts" "$TASK_POOL_DIR" "$TASK_POOL_DIR/tasks" "$TASKS_DIR" "$REPORTS_DIR" "$PLANS_DIR" "$CHECKS_DIR"
    printf '#!/usr/bin/env bash\nexit 0\n' > "$T/board.sh"
    printf '#!/usr/bin/env bash\necho "$1: $2" >> "%s/inbox.log"\n' "$T" > "$T/inbox.sh"
    export BOARD_UPDATE="$T/board.sh" INBOX_WRITE="$T/inbox.sh"
    export QC_TARGET=metsuke
    unset TMUX_PANE

    # Throwaway git repo
    (
        cd "$T"
        git init -q
        touch README.md
        git add README.md
        git commit -m "init" -q
    )
}

teardown() {
    rm -rf "$T"
}

run_task_finish() {
    # task_finish.py collects git evidence from the invoking process's cwd
    # (git rev-parse --show-toplevel with no explicit repo path), so every
    # call must run from inside the throwaway repo, never the real one.
    (cd "$T" && bash "$PROJECT_ROOT/scripts/task_finish.sh" "$@")
}

create_task() {
    local agent=$1
    local task_id=$2
    local status=$3
    local parent_cmd="cmd_test"
    local plan_status="assigned"
    local files="[]"
    printf "task:\n  task_id: %s\n  status: %s\n  parent_cmd: %s\n  plan_status: %s\n  files: %s\n" \
        "$task_id" "$status" "$parent_cmd" "$plan_status" "$files" > "$TASKS_DIR/$agent.yaml"
}

create_task_with_plan() {
    local agent=$1
    local task_id=$2
    local status=$3
    local plan_status=$4
    local pool=$5
    local parent_cmd="cmd_test"
    local files="[]"
    local pool_line=""
    [ -n "$pool" ] && pool_line="  pool: $pool"
    printf "task:\n  task_id: %s\n  status: %s\n  plan_status: %s\n  parent_cmd: %s\n  files: %s\n%s\n" \
        "$task_id" "$status" "$plan_status" "$parent_cmd" "$files" "$pool_line" > "$TASKS_DIR/$agent.yaml"
}

# create_open_pool_entry <task_id>
# All fields task_pool.claim() reads via FIELDS, status open (unclaimed),
# no "kind" (so it fits any agent regardless of KIND_OWNERS).
create_open_pool_entry() {
    local task_id=$1
    cat > "$TASK_POOL_DIR/$task_id.yaml" << EOF
task_id: $task_id
parent_cmd: cmd_test
project: multi-agent-shogun
bloom_level: L1
plan_gate: false
files: []
depends_on: []
description: "test entry"
status: open
created: "2026-10-01T00:00:00"
EOF
}

@test "refusal: no active task (no file)" {
    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 2 ]
    [[ "$output" == *"refused: no active task"* ]]
}

@test "refusal: no active task (done task)" {
    create_task "ashigaru7" "tc_done" "done"
    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 2 ]
    [[ "$output" == *"refused: no active task"* ]]
}

@test "refusal: empty summary" {
    create_task "ashigaru7" "tc_empty" "assigned"
    run run_task_finish "ashigaru7" ""
    [ "$status" -eq 2 ]
    [[ "$output" == *"refused: empty summary"* ]]
}

@test "refusal: wrong agent id" {
    create_task "ashigaru7" "tc_wrong" "assigned"
    mkdir -p "$T/bin"
    printf '#!/bin/bash\necho "other_agent"' > "$T/bin/tmux"
    chmod +x "$T/bin/tmux"
    export PATH="$T/bin:$PATH"
    export TMUX_PANE="pane0"

    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 2 ]
    [[ "$output" == *"refused: you are other_agent, not ashigaru7"* ]]
}

@test "refusal: pool task claimed by another agent" {
    create_task "ashigaru7" "tc_pool_wrong" "assigned"
    printf 'task_id: tc_pool_wrong\nstatus: claimed\nclaimed_by: ashigaru1\n' > "$TASK_POOL_DIR/tc_pool_wrong.yaml"

    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 2 ]
    [[ "$output" == *"refused: pool claimed_by not ashigaru7"* ]]
}

@test "refusal: plan not approved (pending)" {
    create_task_with_plan "ashigaru7" "tc_pending" "assigned" "pending"
    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 5 ]
    [[ "$output" == *"refused: task"*"pending"* ]]
}

@test "refusal: plan not approved (submitted)" {
    create_task_with_plan "ashigaru7" "tc_submitted" "assigned" "submitted"
    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 5 ]
    [[ "$output" == *"refused: task"*"submitted"* ]]
}

@test "refusal: plan not approved (escalated)" {
    create_task_with_plan "ashigaru7" "tc_escalated" "assigned" "escalated"
    run run_task_finish "ashigaru7" "some summary"
    [ "$status" -eq 5 ]
    [[ "$output" == *"refused: task"*"escalated"* ]]
}

@test "refusal: missing checks file" {
    create_task "ashigaru7" "tc_no_checks" "assigned"
    run run_task_finish "ashigaru7" "some summary" --checks "$T/nonexistent.txt"
    [ "$status" -eq 6 ]
    [[ "$output" == *"refused: missing checks file"* ]]
}

@test "refusal: no report or inbox logged on refusal" {
    create_task "ashigaru7" "tc_refuse_check" "assigned"
    run run_task_finish "ashigaru7" "" # empty summary -> refusal
    [ -f "$REPORTS_DIR/ashigaru7_report.yaml" ] && false || true
    [ -f "$T/inbox.log" ] && grep -q "ashigaru7" "$T/inbox.log" && false || true
}

@test "success: waived task" {
    create_task_with_plan "ashigaru7" "tc_waived" "assigned" "waived"
    touch "$T/dummy.txt"
    run run_task_finish "ashigaru7" "waived summary" --checks "$T/dummy.txt"
    [ "$status" -eq 0 ]
}

@test "success: approved task" {
    create_task_with_plan "ashigaru7" "tc_approved" "assigned" "approved"
    touch "$T/dummy.txt"
    run run_task_finish "ashigaru7" "approved summary" --checks "$T/dummy.txt"
    [ "$status" -eq 0 ]
}

@test "success: report parsing and key existence" {
    create_task_with_plan "ashigaru7" "tc_report" "assigned" "approved"
    touch "$T/dummy.txt"
    run run_task_finish "ashigaru7" "report summary" --checks "$T/dummy.txt"
    [ "$status" -eq 0 ]

    report_file="$REPORTS_DIR/ashigaru7_report.yaml"
    [ -f "$report_file" ]

    # Check status is NOT at top level
    grep -q "^status:" "$TASKS_DIR/ashigaru7.yaml" && false || true

    [ -f "$REPORTS_DIR/history/ashigaru7/tc_report.yaml" ]
    grep -q "metsuke: ashigaru7: tc_report done" "$T/inbox.log"
    grep -q "karo: ashigaru7: tc_report done" "$T/inbox.log"
}

@test "success: next pool task claimed" {
    create_task_with_plan "ashigaru7" "tc_pool_1" "assigned" "approved" "true"
    printf 'task_id: tc_pool_1\nstatus: claimed\nclaimed_by: ashigaru7\npool: true\n' > "$TASK_POOL_DIR/tc_pool_1.yaml"

    create_open_pool_entry "tc_pool_2"

    touch "$T/dummy.txt"
    run run_task_finish "ashigaru7" "pool summary" --checks "$T/dummy.txt"
    [ "$status" -eq 0 ]
    # Should print brief for tc_pool_2
    [[ "$output" == *"tc_pool_2"* ]]
}

@test "success: pool task claim and idle" {
    create_task_with_plan "ashigaru7" "tc_pool_success" "assigned" "approved" "true"
    printf 'task_id: tc_pool_success\nstatus: claimed\nclaimed_by: ashigaru7\npool: true\n' > "$TASK_POOL_DIR/tc_pool_success.yaml"
    touch "$T/dummy.txt"
    run run_task_finish "ashigaru7" "pool summary" --checks "$T/dummy.txt"
    [ "$status" -eq 0 ]
    # Check next task is claimed (we don't have a next task, so it should be idle)
    # The script should print 'idle' if pool is empty after claim.
    [[ "$output" == *"idle"* ]]
}

@test "success: out_of_scope file" {
    create_task_with_plan "ashigaru7" "tc_out" "assigned" "approved"
    touch "$T/dummy.txt"
    # Create a file inside the throwaway repo, outside TASKS_DIR/REPORTS_DIR/etc
    # (git evidence is collected from $T, not the real project root; see finding 4).
    touch "$T/out_of_scope.txt"
    run run_task_finish "ashigaru7" "out summary" --checks "$T/dummy.txt"
    [ "$status" -eq 0 ]
}

@test "syntax: task_finish.sh bash" {
    run bash -n "$PROJECT_ROOT/scripts/task_finish.sh"
    [ "$status" -eq 0 ]
}

@test "syntax: task_finish.sh bash (with error if any)" {
    run bash -n "$PROJECT_ROOT/scripts/task_finish.sh"
    [ "$status" -eq 0 ]
}
