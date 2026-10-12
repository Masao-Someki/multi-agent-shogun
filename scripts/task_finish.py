#!/usr/bin/env python3
"""Task finish utility for ashigaru protocol."""

import argparse
import datetime
import os
import subprocess
import sys

import yaml

# Add scripts to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import task_pool
    from task_start import brief
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

# Environment overrides
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.environ.get("REPORTS_DIR", os.path.join(ROOT, "queue", "reports"))
CHECKS_DIR = os.environ.get("CHECKS_DIR", os.path.join(ROOT, "queue", "checks"))
PLANS_DIR = os.environ.get("PLANS_DIR", os.path.join(ROOT, "queue", "plans"))
INBOX_WRITE = os.environ.get(
    "INBOX_WRITE", os.path.join(ROOT, "scripts", "inbox_write.sh")
)
BOARD_UPDATE = os.environ.get(
    "BOARD_UPDATE", os.path.join(ROOT, "scripts", "board_update.sh")
)


def get_qc_target():
    """Get configured recipient for Ashigaru completion reports."""
    env_val = os.environ.get("QC_TARGET")
    if env_val:
        return env_val
    try:
        res = subprocess.run(
            ["bash", os.path.join(ROOT, "scripts", "qc_target.sh")],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "metsuke"  # Fallback


def _guard(agent):
    """Verify the agent running the script is the correct one."""
    tmux_pane = os.environ.get("TMUX_PANE")
    if not tmux_pane:
        return  # Bats unsets TMUX_PANE

    cmd = ["tmux", "display-message", "-t", tmux_pane, "-p", "#{@agent_id}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        tmux_id = res.stdout.strip()
        if tmux_id and tmux_id != agent:
            print(f"refused: you are {tmux_id}, not {agent}")
            sys.exit(2)
    except subprocess.CalledProcessError:
        pass


def main():
    """Run the task finish logic."""
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", help="Agent ID")
    parser.add_argument("summary", help="One-line summary")
    parser.add_argument("--checks", help="Path to checks file")
    args = parser.parse_args()

    agent = args.agent
    _guard(agent)

    task_path = task_pool.task_path(agent)
    if not os.path.exists(task_path):
        print("refused: no active task")
        sys.exit(2)

    task_data = task_pool.load(task_path)
    task = task_data.get("task") or {}
    task_id = task.get("task_id")
    status = task.get("status")

    if not task_id or status not in ("assigned", "in_progress"):
        print("refused: no active task")
        sys.exit(2)

    # Check plan_status
    plan_status = task.get("plan_status")
    if plan_status in ("pending", "submitted", "escalated"):
        print(f"refused: task {task_id} is in {plan_status} state")
        sys.exit(5)

    if not args.summary.strip():
        print("refused: empty summary")
        sys.exit(2)

    if args.checks and not os.path.exists(args.checks):
        print("refused: missing checks file")
        sys.exit(6)

    # 1. Check if task is actually claimed by this agent (in the pool entry)
    pool_entry_path = task_pool.entry_path(task_id)
    if os.path.exists(pool_entry_path):
        pool_entry = task_pool.load(pool_entry_path)
        if pool_entry.get("claimed_by") != agent:
            print(f"refused: pool claimed_by not {agent}")
            sys.exit(2)

    # 2. Collect evidence
    print(f"Collecting evidence for {task_id}...")

    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
        git_status = subprocess.check_output(
            ["git", "status", "--short"], cwd=git_root, text=True
        )
        git_diff = subprocess.check_output(
            ["git", "diff", "--stat"], cwd=git_root, text=True
        )

        # Out of scope check
        scope_files = task.get("files", [])
        all_diff_files = subprocess.check_output(
            ["git", "diff", "--name-only"], cwd=git_root, text=True
        ).splitlines()
        out_of_scope = [f for f in all_diff_files if f not in scope_files]

        evidence_data = {
            "head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=git_root, text=True
            ).strip(),
            "status_short": git_status,
            "diff_stat": git_diff,
            "out_of_scope": out_of_scope,
        }
    except subprocess.CalledProcessError as e:
        print(f"Error collecting git evidence: {e}")
        evidence_data = {"error": str(e)}
    except Exception as e:
        print(f"Unexpected error: {e}")
        evidence_data = {"error": str(e)}

    # 3. Collect check results
    check_results = ""
    if args.checks and os.path.exists(args.checks):
        with open(args.checks, "r") as f:
            check_results = f.read()
    # Last 200 lines
    check_results_truncated = "\n".join(check_results.splitlines()[-200:])

    # 4. Prepare report
    report = {
        "worker_id": agent,
        "task_id": task_id,
        "parent_cmd": task.get("parent_cmd"),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "evidence": evidence_data,
        "checks": check_results_truncated,
        "summary": args.summary,
    }

    # 5. Write report
    report_path = os.path.join(REPORTS_DIR, f"{agent}_report.yaml")
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(report_path, "w") as f:
        yaml.safe_dump(report, f, sort_keys=False, allow_unicode=True)

    # 6. Write history copy
    history_dir = os.path.join(REPORTS_DIR, "history", agent)
    os.makedirs(history_dir, exist_ok=True)
    history_path = os.path.join(history_dir, f"{task_id}.yaml")
    with open(history_path, "w") as f:
        yaml.safe_dump(report, f, sort_keys=False, allow_unicode=True)

    # 7. Mark task done in pool and agent task file
    if task.get("pool"):
        task_pool.mark(task_id, "done", agent)
        subprocess.run(
            [
                "bash",
                BOARD_UPDATE,
                agent,
                f"task_id={task_id}",
                "step=done",
                f"note=done: {args.summary[:60]}",
            ],
            check=False,
        )
    else:
        task_pool.set_task_status(agent, task_id, "done")
        subprocess.run(
            [
                "bash",
                BOARD_UPDATE,
                agent,
                f"task_id={task_id}",
                "step=done",
                f"note=done: {args.summary[:60]}",
            ],
            check=False,
        )

    # 8. Notify QC and Karo
    qc_target = get_qc_target()
    subprocess.run(
        [
            "bash",
            INBOX_WRITE,
            qc_target,
            f"{agent}: {task_id} done. See the report.",
            "report_received",
            agent,
        ],
        check=True,
    )
    subprocess.run(
        [
            "bash",
            INBOX_WRITE,
            "karo",
            f"{agent}: {task_id} done. See the report.",
            "report_received",
            agent,
        ],
        check=True,
    )

    # 9. Claim next task
    print("Claiming next task...")
    checks_path = os.path.join(CHECKS_DIR, f"{agent}.txt")
    res = subprocess.run(
        ["bash", os.path.join(ROOT, "scripts", "task_pool_claim.sh"), agent],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        print(res.stdout.strip())
        new_task_path = task_pool.task_path(agent)
        if os.path.exists(new_task_path):
            new_task_data = task_pool.load(new_task_path)
            new_task = new_task_data.get("task") or {}
            new_task_id = new_task.get("task_id")
            if new_task_id:
                print(
                    brief(
                        new_task_id,
                        new_task.get("parent_cmd", ""),
                        "assigned",
                        new_task.get("files", []),
                        new_task.get("description", ""),
                        checks_path,
                        agent,
                    )
                )
    elif res.returncode == 1:
        print("idle")
    else:
        print(f"error claiming next task: {res.stderr.strip() or res.stdout.strip()}")


if __name__ == "__main__":
    main()
