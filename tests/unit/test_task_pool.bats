#!/usr/bin/env bats
# Task pool: add and claim (scripts/task_pool.py through its shell wrappers).

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export T="$(mktemp -d "$BATS_TMPDIR/pool.XXXXXX")"
    export TASK_POOL_DIR="$T/pool" TASKS_DIR="$T/tasks" POOL_AGENTS="ashigaru1 ashigaru2 ashigaru8 ashigaru9 ashigaru10"
    mkdir -p "$TASK_POOL_DIR/drafts" "$TASKS_DIR"
    printf '#!/usr/bin/env bash\nexit 0\n' > "$T/board.sh"
    printf '#!/usr/bin/env bash\necho "$1 $3" >> "%s/inbox.log"\n' "$T" > "$T/inbox.sh"
    export BOARD_UPDATE="$T/board.sh" INBOX_WRITE="$T/inbox.sh"
}

teardown() {
    rm -rf "$T"
}

draft() {
    # draft <task_id> <file> [depends_on] [kind]
    local tid="$1"
    local f="$2"
    local dep="${3:-}"
    local k="${4:-}"
    printf 'task_id: %s\nparent_cmd: cmd_x\nproject: p\nbloom_level: L1\nplan_gate: false\nfiles: [%s]\ndepends_on: [%s]\ndescription: |\n  do it\n' \
        "$tid" "$f" "$dep" > "$TASK_POOL_DIR/drafts/$tid.yaml"
    if [ -n "$k" ]; then
        printf 'kind: %s\n' "$k" >> "$TASK_POOL_DIR/drafts/$tid.yaml"
    fi
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

@test "T-POOL-009 kind: pytest task is claimed by ashigaru10 and refused by ashigaru1" {
    draft t_pytest a.py "" pytest
    pool add "$TASK_POOL_DIR/drafts/t_pytest.yaml"
    run pool claim ashigaru10
    [ "$status" -eq 0 ]
    [ "$output" = "t_pytest" ]

    draft t_pytest2 b.py "" pytest
    pool add "$TASK_POOL_DIR/drafts/t_pytest2.yaml"
    run pool claim ashigaru1
    [ "$status" -eq 1 ]
}

@test "T-POOL-010 ashigaru10 does not take a task without a kind" {
    draft t_no_kind a.py
    pool add "$TASK_POOL_DIR/drafts/t_no_kind.yaml"
    run pool claim ashigaru10
    [ "$status" -eq 1 ]
}

@test "T-POOL-011 kind: lint is restricted to its owner; kind: docstring has no owner" {
    draft t_lint l.py "" lint
    draft t_doc d.py "" docstring
    pool add "$TASK_POOL_DIR/drafts/t_lint.yaml" "$TASK_POOL_DIR/drafts/t_doc.yaml"

    run pool claim ashigaru9
    [ "$status" -eq 0 ]
    [ "$output" = "t_lint" ]

    run pool claim ashigaru1
    [ "$status" -eq 0 ]
    [ "$output" = "t_doc" ]

    draft t_lint2 l2.py "" lint
    pool add "$TASK_POOL_DIR/drafts/t_lint2.yaml"
    run pool claim ashigaru2
    [ "$status" -eq 1 ]
}

@test "T-POOL-012 POOL_KIND_OWNERS override works" {
    export POOL_KIND_OWNERS="pytest=ashigaru1"
    draft t_override o.py "" pytest
    pool add "$TASK_POOL_DIR/drafts/t_override.yaml"
    run pool claim ashigaru1
    [ "$status" -eq 0 ]
    [ "$output" = "t_override" ]
    unset POOL_KIND_OWNERS
}

@test "T-POOL-013 claim hits late check via inline python" {
    draft t_k a.py
    pool add "$TASK_POOL_DIR/drafts/t_k.yaml"
    run bash -c "cd '$PROJECT_ROOT' && PYTHONPATH=. '$PROJECT_ROOT/.venv/bin/python3' -c \"
import sys
import os
import scripts.task_pool as task_pool

class MockTaskState:
    def __init__(self):
        self.count = 0
    def __call__(self, agent):
        self.count += 1
        if self.count == 1:
            return ('idle', '')
        return ('assigned', 't_k')

task_pool.task_state = MockTaskState()

try:
    task_pool.claim('ashigaru1')
except SystemExit as e:
    sys.exit(e.code)
\""
    [ "$status" -eq 3 ]
    # Verify entry is still open and not claimed
    grep -q '^status: open$' "$TASK_POOL_DIR/t_k.yaml"
    # Verify no task YAML was written
    [ ! -f "$TASKS_DIR/ashigaru1.yaml" ]
}

@test "T-POOL-014 kind: pytest task is claimed by ashigaru1 in the Claude formation" {
    export POOL_AGENTS="ashigaru1 ashigaru2"
    draft t_pytest a.py "" pytest
    pool add "$TASK_POOL_DIR/drafts/t_pytest.yaml"
    run pool claim ashigaru1
    [ "$status" -eq 0 ]
    [ "$output" = "t_pytest" ]
    unset POOL_AGENTS
}

@test "T-POOL-015 a bad POOL_KIND_OWNERS value does not break list" {
    export POOL_KIND_OWNERS="bad"
    run pool list
    [ "$status" -eq 0 ]
    unset POOL_KIND_OWNERS
}
