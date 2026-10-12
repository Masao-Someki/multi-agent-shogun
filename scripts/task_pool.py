#!/usr/bin/env python3
"""Task pool: Karo adds tasks, idle Ashigaru claim them.

One YAML per task in ``queue/task_pool/<task_id>.yaml``; only these
subcommands change it (never edit by hand). Every change runs under the
``.lock.d`` directory lock.

Usage: task_pool.py add <draft.yaml>... | claim <agent> | mark <task_id>
done|failed|reopen | reconcile | list [status] | plan_submit <agent>
"""

import datetime
import os
import subprocess
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.environ.get("TASK_POOL_DIR", os.path.join(ROOT, "queue", "task_pool"))
TASKS = os.environ.get("TASKS_DIR", os.path.join(ROOT, "queue", "tasks"))
INBOX_WRITE = os.environ.get(
    "INBOX_WRITE", os.path.join(ROOT, "scripts", "inbox_write.sh")
)
BOARD_UPDATE = os.environ.get(
    "BOARD_UPDATE", os.path.join(ROOT, "scripts", "board_update.sh")
)
FIELDS = (
    "task_id",
    "parent_cmd",
    "project",
    "bloom_level",
    "plan_gate",
    "files",
    "depends_on",
    "description",
)
# Dedicated ashigaru per task kind (Lord, 2026-10-11): a task with one of these
# kinds goes only to its owner, and an owner takes only its own kind.  Tasks
# without a listed kind go to the other ashigaru.  Override with POOL_KIND_OWNERS
# as "kind=agent kind=agent ...".
KIND_OWNERS = dict(
    pair.split("=", 1)
    for pair in os.environ.get(
        "POOL_KIND_OWNERS",
        "pytest=ashigaru10 lint=ashigaru9",
    ).split()
    if "=" in pair
)
FREE = ("idle", "done", "cancelled")


def present_owners():
    """Return KIND_OWNERS limited to owners in the running formation.

    pool_dispatcher.sh exports POOL_PRESENT_AGENTS (the agent ids of the live
    panes).  The Claude formation has three ashigaru, so ashigaru9 and
    ashigaru10 are absent there and their kinds go to any ashigaru.  Without
    the variable (tests, a manual claim) every owner counts as present.
    """
    present = os.environ.get("POOL_PRESENT_AGENTS") or os.environ.get("POOL_AGENTS")
    if present is None:
        return dict(KIND_OWNERS)
    agents = set(present.split())
    return {kind: owner for kind, owner in KIND_OWNERS.items() if owner in agents}


def _str(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


yaml.SafeDumper.add_representer(str, _str)


def now():
    """Return the local time as an ISO string."""
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Lock:
    """Directory lock shared by every pool change (mkdir is atomic)."""

    def __enter__(self):
        """Take the pool lock or exit after 5 seconds."""
        os.makedirs(POOL, exist_ok=True)
        self.path = os.path.join(POOL, ".lock.d")
        for _ in range(50):
            try:
                os.mkdir(self.path)
                return self
            except FileExistsError:
                time.sleep(0.1)
        sys.exit("task_pool: lock timeout")

    def __exit__(self, *exc):
        """Release the pool lock."""
        os.rmdir(self.path)


def load(path):
    """Read one YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save(path, data):
    """Write one YAML file atomically (temp file, then rename)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)


def entries():
    """Return every pool entry, sorted by file name."""
    if not os.path.isdir(POOL):
        return []
    names = sorted(n for n in os.listdir(POOL) if n.endswith(".yaml"))
    return [load(os.path.join(POOL, n)) for n in names]


def entry_path(task_id):
    """Return the pool file of a task."""
    return os.path.join(POOL, task_id + ".yaml")


def task_path(agent):
    """Return the task YAML of an agent."""
    return os.path.join(TASKS, agent + ".yaml")


def task_state(agent):
    """Return (status, task_id) of the agent's task YAML."""
    path = task_path(agent)
    if not os.path.exists(path):
        return "idle", ""
    task = load(path).get("task") or {}
    return task.get("status", "idle"), task.get("task_id", "")


def set_task_status(agent, task_id, value):
    """Set status in the agent's task YAML if it still holds task_id."""
    path = task_path(agent)
    if not os.path.exists(path):
        return
    data = load(path)
    task = data.get("task") or {}
    if task.get("task_id") == task_id:
        task["status"] = value
        save(path, data)


def add(drafts):
    """Move drafts into the pool as open, then wake idle Ashigaru once."""
    with Lock():
        for draft in drafts:
            entry = load(draft)
            missing = [k for k in FIELDS if k not in entry]
            if missing:
                sys.exit(f"task_pool_add: {draft}: missing {missing}")
            if not (
                isinstance(entry["plan_gate"], bool)
                and isinstance(entry["files"], list)
                and isinstance(entry["depends_on"], list)
                and str(entry["description"]).strip()
            ):
                sys.exit(f"task_pool_add: {draft}: bad field types")
            if os.path.exists(entry_path(entry["task_id"])):
                sys.exit(f"task_pool_add: {entry['task_id']} is already in the pool")
            entry.update(
                status="open",
                claimed_by="",
                created=now(),
                claimed_at="",
                finished_at="",
                attempt=1,
            )
            save(entry_path(entry["task_id"]), entry)
            os.remove(draft)
        claimed = {
            e.get("claimed_by") for e in entries() if e.get("status") == "claimed"
        }
    for agent in os.environ.get("POOL_AGENTS", "").split():
        if task_state(agent)[0] in FREE and agent not in claimed:
            msg = (
                f"You are {agent}. The task pool has open tasks. "
                f"Run: bash scripts/task_pool_claim.sh {agent}"
            )
            subprocess.run(
                ["bash", INBOX_WRITE, agent, msg, "pool_ready", "karo"], check=False
            )


def claim(agent):
    """Give the oldest claimable open task to agent (exit 1: none, 3: busy)."""
    with Lock():
        status, current = task_state(agent)
        if status in ("assigned", "in_progress"):
            print(current)
            sys.exit(3)
        pool = entries()
        done = {e["task_id"] for e in pool if e.get("status") == "done"}
        busy = set()
        for e in pool:
            if e.get("status") == "claimed":
                busy.update(e.get("files") or [])

        owners = present_owners()

        def fits(entry):
            kind = entry.get("kind")
            if kind in owners:
                return owners[kind] == agent
            if agent in owners.values():
                return False
            return True

        ready = [
            e
            for e in pool
            if e.get("status") == "open"
            and set(e.get("depends_on") or []) <= done
            and not set(e.get("files") or []) & busy
            and fits(e)
        ]
        if not ready:
            sys.exit(1)
        entry = sorted(ready, key=lambda e: (e.get("created", ""), e["task_id"]))[0]
        plan_status = "pending" if entry["plan_gate"] else "waived"
        task = {
            k: entry[k] for k in ("task_id", "parent_cmd", "project", "bloom_level")
        }
        task.update(
            pool=True,
            plan_gate=entry["plan_gate"],
            plan_status=plan_status,
            files=entry["files"],
            description=entry["description"],
            status="assigned",
            timestamp=now(),
        )
        status, current = task_state(agent)
        if status in ("assigned", "in_progress"):
            print(current)
            sys.exit(3)
        entry.update(status="claimed", claimed_by=agent, claimed_at=now())
        save(entry_path(entry["task_id"]), entry)
        save(task_path(agent), {"task": task})
    subprocess.run(
        [
            "bash",
            BOARD_UPDATE,
            agent,
            f"task_id={entry['task_id']}",
            f"cmd={entry['parent_cmd']}",
            f"plan_status={plan_status}",
            "note=claimed from pool",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
    )
    print(entry["task_id"])
    if entry["plan_gate"]:
        print(
            f"plan gate: add your plan, then run: bash scripts/plan_submit.sh {agent}"
        )


def mark(task_id, how, agent=""):
    """Mark a claimed task done or failed, or reopen it.

    With ``agent``, done and failed refuse a task claimed by someone else.
    """
    with Lock():
        path = entry_path(task_id)
        if not os.path.exists(path):
            sys.exit(f"task_pool_mark: no pool entry {task_id}")
        entry = load(path)
        claimant = entry.get("claimed_by", "")
        if how in ("done", "failed"):
            if entry.get("status") != "claimed":
                sys.exit(2)
            if agent and agent != claimant:
                sys.exit(
                    f"task_pool_mark: {task_id} is claimed by {claimant}, not {agent}"
                )
            entry.update(status=how, finished_at=now())
            if claimant:
                set_task_status(claimant, task_id, "done")
        elif how == "reopen":
            if claimant:
                set_task_status(claimant, task_id, "idle")
            entry.update(
                status="open",
                claimed_by="",
                claimed_at="",
                attempt=int(entry.get("attempt", 1)) + 1,
            )
        else:
            sys.exit("usage: task_pool_mark.sh <task_id> done|failed|reopen")
        save(path, entry)


def reconcile():
    """Reopen claimed entries whose claimant no longer holds them."""
    with Lock():
        for entry in entries():
            if entry.get("status") != "claimed":
                continue
            status, task_id = task_state(entry["claimed_by"])
            if task_id == entry["task_id"] and status in ("assigned", "in_progress"):
                continue
            entry.update(
                status="open",
                claimed_by="",
                claimed_at="",
                attempt=int(entry.get("attempt", 1)) + 1,
            )
            save(entry_path(entry["task_id"]), entry)


def list_entries(which=None):
    """Print one line per pool entry, optionally of one status."""
    for entry in entries():
        if which and entry.get("status") != which:
            continue
        files = ",".join(entry.get("files") or [])
        print(
            f"{entry.get('status')}\t{entry['task_id']}\t"
            f"{entry.get('claimed_by', '')}\t{files}"
        )


def plan_submit(agent):
    """Set plan_status: submitted and send plan_submitted in one run."""
    path = task_path(agent)
    data = load(path)
    task = data.get("task") or {}
    if not task.get("plan"):
        sys.exit("plan_submit: add your plan: block to your task YAML first")
    task["plan_status"] = "submitted"
    save(path, data)
    msg = f"{agent}: plan submitted for {task.get('task_id')}"
    subprocess.run(
        ["bash", INBOX_WRITE, "kumigashira", msg, "plan_submitted", agent], check=True
    )


def main(argv):
    """Dispatch the subcommand."""
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "add" and args:
        add(args)
    elif cmd == "claim" and len(args) == 1:
        claim(args[0])
    elif cmd == "mark" and args == ["--reconcile"]:
        reconcile()
    elif cmd == "mark" and len(args) >= 2:
        mark(args[0], args[1], args[2] if len(args) > 2 else "")
    elif cmd == "list":
        list_entries(args[0] if args else None)
    elif cmd == "plan_submit" and len(args) == 1:
        plan_submit(args[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
