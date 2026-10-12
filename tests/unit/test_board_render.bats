#!/usr/bin/env bats

setup() {
    export PROJECT_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
    export ROOT="$(mktemp -d "$BATS_TMPDIR/board_root.XXXXXX")"
    export BOARD="$ROOT/queue/board"
    mkdir -p "$BOARD" "$ROOT/queue/reports"
    export PY="$PROJECT_ROOT/.venv/bin/python3"
    [ -x "$PY" ] || PY=python3
}

teardown() {
    rm -rf "$ROOT"
}

render() {
    "$PY" "$PROJECT_ROOT/scripts/board_render.py" "$BOARD" "$ROOT"
}

@test "T-RENDER-001 an empty board still has the four sections" {
    run render
    [ "$status" -eq 0 ]
    for section in "## Active cmds" "## Agents" "## Open questions / escalations" "## Recent QC"; do
        grep -qF "$section" "$BOARD/board.md"
    done
}

@test "T-RENDER-002 an agent file becomes a table row" {
    printf 'task_id: t1\nstep: 2/5\nnote: hi\n' > "$BOARD/ashigaru1.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -qF "| ashigaru1 | t1 |  | 2/5 | hi |" "$BOARD/board.md"
}

@test "T-RENDER-003 rows follow the formation order" {
    printf 'note: g\n' > "$BOARD/gunshi.yaml"
    printf 'note: k\n' > "$BOARD/karo.yaml"
    run render
    [ "$status" -eq 0 ]
    [ "$(grep -n '^| karo ' "$BOARD/board.md" | cut -d: -f1)" -lt "$(grep -n '^| gunshi ' "$BOARD/board.md" | cut -d: -f1)" ]
}

@test "T-RENDER-004 a question is listed" {
    printf 'question: which file?\n' > "$BOARD/ashigaru2.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -qF -- "- ashigaru2: which file?" "$BOARD/board.md"
}

@test "T-RENDER-005 an in_progress cmd is listed" {
    printf -- '- id: cmd_x\n  purpose: "Do X"\n  status: in_progress\n- id: cmd_y\n  purpose: "Do Y"\n  status: done\n' > "$ROOT/queue/shogun_to_karo.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -qF -- "- cmd_x: Do X" "$BOARD/board.md"
    run grep -qF "cmd_y" "$BOARD/board.md"
    [ "$status" -eq 1 ]
}

@test "T-RENDER-006 the latest QC verdicts are listed" {
    printf 'a:\n  task_id: qc_1\n  verdict: PASS\n' > "$ROOT/queue/reports/metsuke_report.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -qF -- "- qc_1: PASS" "$BOARD/board.md"
}

@test "T-RENDER-007 no temp file is left" {
    run render
    [ "$status" -eq 0 ]
    [ ! -f "$BOARD/board.md.tmp" ]
}


@test "T-RENDER-008 the cmd column is shown" {
    printf 'task_id: t1\ncmd: cmd_x\n' > "$BOARD/karo.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -qF "| agent | task_id | plan_status | step | note | updated | cmd |" "$BOARD/board.md"
    grep -qF "| cmd_x |" "$BOARD/board.md"
}


@test "T-RENDER-009 tanya rows are not shown" {
    printf 'note: t\n' > "$BOARD/tanya.yaml"
    printf 'note: t2\n' > "$BOARD/tanya2.yaml"
    printf 'note: k\n' > "$BOARD/karo.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -q '^| karo ' "$BOARD/board.md"
    run grep -c '^| tanya' "$BOARD/board.md"
    [ "$output" = "0" ]
}


@test "T-RENDER-010 the Pool section counts the task pool" {
    mkdir -p "$ROOT/queue/task_pool"
    printf 'task_id: t_a\nstatus: open\n' > "$ROOT/queue/task_pool/t_a.yaml"
    printf "task_id: t_b\nstatus: claimed\nclaimed_by: ashigaru2\nclaimed_at: '2026-10-11T20:00:00'\n" > "$ROOT/queue/task_pool/t_b.yaml"
    run render
    [ "$status" -eq 0 ]
    grep -qF "open 1 / claimed 1 / done 0 / failed 0" "$BOARD/board.md"
    grep -qF -- "- ashigaru2: t_b (since 2026-10-11T20:00:00)" "$BOARD/board.md"
}
