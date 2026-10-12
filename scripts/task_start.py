"""Task start utility for ashigaru protocol."""

import contextlib
import io
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
import task_pool  # noqa: E402

PLANS_DIR = os.environ.get("PLANS_DIR", "queue/plans")
CHECKS_DIR = os.environ.get("CHECKS_DIR", "queue/checks")


def _guard(agent):
    """Verify the agent running the script is the correct one."""
    tmux_pane = os.environ.get("TMUX_PANE")
    if tmux_pane:
        try:
            res = subprocess.check_output(
                ["tmux", "display-message", "-t", tmux_pane, "-p", "#{@agent_id}"],
                text=True,
            ).strip()
            if res and res != agent:
                print(f"refused: you are {res}, not {agent}")
                sys.exit(2)
        except subprocess.CalledProcessError:
            pass


def _load_task(agent):
    """Load the task associated with the agent.

    Drops any top-level key other than ``task`` (for example a stray
    ``status:`` written outside ``task:``), so a later ``task_pool.save``
    with this ``data`` never writes it back.
    """
    path = task_pool.task_path(agent)
    if not os.path.exists(path):
        return None, None
    data = task_pool.load(path)
    if not data or "task" not in data:
        return None, None
    stray = [k for k in data if k != "task"]
    if stray:
        print(f"warning: dropped stray top-level keys: {stray}")
        data = {"task": data["task"]}
    return path, data


def brief(task_id, parent_cmd, plan_status, files, description, checks_path, agent):
    """Generate the brief summary string."""
    files_str = ", ".join(files) if files else "none (read-only task)"
    return (
        f"task {task_id} (cmd {parent_cmd}, plan_status {plan_status}),\n"
        f"files in scope: {files_str},\n"
        f"description: {description}\n"
        f"then checks: run them with output to {checks_path}, for example:\n"
        f'{{ echo "+ <cmd>"; <cmd>; echo "exit=0"; }} > {checks_path} 2>&1\n'
        f'and finish with: bash scripts/task_finish.sh {agent} "<summary>"\n'
        f"--checks {checks_path}.\n"
        f"Rules line: edit only the files in scope; never edit queue/ files "
        f"by hand; no git commit or push unless the description says so"
    )


def main():
    """Run the main entry point for task_start.py."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    agent = sys.argv[1]
    _guard(agent)
    task_path = task_pool.task_path(agent)

    plan_file = None
    if "--plan" in sys.argv:
        idx = sys.argv.index("--plan")
        if idx + 1 < len(sys.argv):
            plan_file = sys.argv[idx + 1]
        else:
            print("plan rejected: --plan requires a file")
            sys.exit(4)

    status, task_id = task_pool.task_state(agent)

    if status in ("idle", "done", "cancelled") or not task_id:
        try:
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    task_pool.claim(agent)
            except SystemExit as e:
                if e.code not in (0, None):
                    print("idle: no task")
                    sys.exit(1)
            output = buf.getvalue().strip()
            if not output:
                print("idle: no task")
                sys.exit(1)

            lines = output.split("\n")
            task_id = lines[0].strip()

            path, data = _load_task(agent)
            if not path or not data:
                print("idle: no task")
                sys.exit(1)
            task = data["task"]

            plan_status = task.get("plan_status", "pending")
            plan_gate = task.get("plan_gate", False)
            parent_cmd = task.get("parent_cmd", "")
            description = task.get("description", "")
            files = task.get("files", [])
            checks_path = os.path.join(CHECKS_DIR, f"{agent}.txt")

            if plan_status in ("submitted", "escalated"):
                print(
                    "waiting: your plan is with kumigashira; run task_start.sh "
                    "again after plan_approved"
                )
                sys.exit(11)

            if not plan_gate:
                task["status"] = "in_progress"
                task_pool.save(task_path, data)
                print(
                    brief(
                        task_id,
                        parent_cmd,
                        plan_status,
                        files,
                        description,
                        checks_path,
                        agent,
                    )
                )
                print("no plan gate: start work")
                sys.exit(0)

            if plan_status == "pending":
                if plan_file:
                    if not os.path.exists(plan_file):
                        print("plan rejected: file missing")
                        sys.exit(4)
                    with open(plan_file, "r") as f:
                        content = f.read()
                    if (
                        not content
                        or "files:" not in content
                        or "verify:" not in content
                        or "expect:" not in content
                    ):
                        print("plan rejected: invalid format")
                        sys.exit(4)

                    task["plan"] = content
                    task["plan_status"] = "submitted"
                    task_pool.save(task_path, data)

                    msg = f"{agent}: plan submitted for {task_id}"
                    subprocess.run(
                        [
                            "bash",
                            task_pool.INBOX_WRITE,
                            "kumigashira",
                            msg,
                            "plan_submitted",
                            agent,
                        ],
                        check=True,
                    )
                    print(
                        "submitted: wait for the plan_approved message, then run: "
                        "bash scripts/task_start.sh " + agent
                    )
                    sys.exit(0)
                else:
                    print(
                        brief(
                            task_id,
                            parent_cmd,
                            plan_status,
                            files,
                            description,
                            checks_path,
                            agent,
                        )
                    )
                    print(
                        f"plan gate: write your plan to {PLANS_DIR}/{agent}.txt, "
                        f"then run: bash scripts/task_start.sh {agent} "
                        f"--plan {PLANS_DIR}/{agent}.txt"
                    )
                    sys.exit(10)

            if plan_status in ("approved", "revised"):
                task["status"] = "in_progress"
                task_pool.save(task_path, data)
                print(
                    brief(
                        task_id,
                        parent_cmd,
                        plan_status,
                        files,
                        description,
                        checks_path,
                        agent,
                    )
                )
                if plan_status == "approved":
                    print("approved: start work")
                else:
                    print("revised: run the plan printed above")
                sys.exit(0)

            print("refused: unknown state or bad usage")
            sys.exit(2)

        except subprocess.CalledProcessError:
            print("idle: no task")
            sys.exit(1)
    else:
        path, data = _load_task(agent)
        if not path or not data:
            print("idle: no task")
            sys.exit(1)
        task = data["task"]

        task_id = task.get("task_id")
        plan_status = task.get("plan_status", "pending")
        plan_gate = task.get("plan_gate", False)
        parent_cmd = task.get("parent_cmd", "")
        description = task.get("description", "")
        files = task.get("files", [])
        checks_path = os.path.join(CHECKS_DIR, f"{agent}.txt")

        if plan_status in ("submitted", "escalated"):
            print(
                "waiting: your plan is with kumigashira; run task_start.sh "
                "again after plan_approved"
            )
            sys.exit(11)

        if not plan_gate:
            task["status"] = "in_progress"
            task_pool.save(task_path, data)
            print(
                brief(
                    task_id,
                    parent_cmd,
                    plan_status,
                    files,
                    description,
                    checks_path,
                    agent,
                )
            )
            print("no plan gate: start work")
            sys.exit(0)

        if plan_status == "pending":
            if plan_file:
                if not os.path.exists(plan_file):
                    print("plan rejected: file missing")
                    sys.exit(4)
                with open(plan_file, "r") as f:
                    content = f.read()
                if (
                    not content
                    or "files:" not in content
                    or "verify:" not in content
                    or "expect:" not in content
                ):
                    print("plan rejected: invalid format")
                    sys.exit(4)

                task["plan"] = content
                task["plan_status"] = "submitted"
                task_pool.save(task_path, data)

                msg = f"{agent}: plan submitted for {task_id}"
                subprocess.run(
                    [
                        "bash",
                        task_pool.INBOX_WRITE,
                        "kumigashira",
                        msg,
                        "plan_submitted",
                        agent,
                    ],
                    check=True,
                )
                print(
                    "submitted: wait for the plan_approved message, then run: "
                    "bash scripts/task_start.sh " + agent
                )
                sys.exit(0)
            else:
                print(
                    brief(
                        task_id,
                        parent_cmd,
                        plan_status,
                        files,
                        description,
                        checks_path,
                        agent,
                    )
                )
                print(
                    f"plan gate: write your plan to {PLANS_DIR}/{agent}.txt, "
                    f"then run: bash scripts/task_start.sh {agent} "
                    f"--plan {PLANS_DIR}/{agent}.txt"
                )
                sys.exit(10)

        if plan_status in ("approved", "revised"):
            task["status"] = "in_progress"
            task_pool.save(task_path, data)
            print(
                brief(
                    task_id,
                    parent_cmd,
                    plan_status,
                    files,
                    description,
                    checks_path,
                    agent,
                )
            )
            if plan_status == "approved":
                print("approved: start work")
            else:
                print("revised: run the plan printed above")
            sys.exit(0)

        print("refused: unknown state or bad usage")
        sys.exit(2)


if __name__ == "__main__":
    main()
