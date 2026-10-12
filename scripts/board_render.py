"""Render queue/board/board.md from the per-agent status files.

Usage: python3 scripts/board_render.py [board_dir [root]]

Reads every ``<agent>.yaml`` in ``board_dir`` (flat ``key: value`` lines),
the in_progress cmds of ``<root>/queue/shogun_to_karo.yaml`` and the
latest QC verdicts of ``<root>/queue/reports/metsuke_report.yaml``, and
writes ``board.md`` atomically (temp file, then rename).
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = ["karo"] + [f"ashigaru{i}" for i in range(1, 11)] + [
    "metsuke",
    "kumigashira",
    "gunshi",
]
COLUMNS = ["task_id", "plan_status", "step", "note", "updated", "cmd"]


def read_flat(path):
    """Return the ``key: value`` lines of one status file as a dict."""
    row = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            key, sep, value = line.rstrip("\n").partition(": ")
            if sep:
                row[key] = value
    return row


def active_cmds(path):
    """Return (cmd id, first 80 chars of purpose) for in_progress cmds."""
    if not os.path.exists(path):
        return []
    cmds, cid, purpose = [], None, ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"- id: (\S+)", line)
            if match:
                cid, purpose = match.group(1), ""
            elif line.startswith("  purpose: "):
                purpose = line[len("  purpose: ") :].strip().strip('"')
            elif line.startswith("  status: in_progress") and cid:
                cmds.append((cid, purpose[:80]))
    return cmds


def recent_qc(path, limit=5):
    """Return (task id, verdict) pairs, newest first, from the QC report."""
    if not os.path.exists(path):
        return []
    found, task = [], None
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"\s*task_id: (\S+)", line)
            if match:
                task = match.group(1)
            match = re.match(r"\s*(?:verdict|qa_decision): (\S+)", line)
            if match and task:
                found.append((task, match.group(1)))
                task = None
    return found[:limit]


def pool_summary(path):
    """Return status counts and one line per claimed task from the task pool."""
    counts = {"open": 0, "claimed": 0, "done": 0, "failed": 0}
    claimed = []
    if not os.path.isdir(path):
        return counts, claimed
    for name in sorted(os.listdir(path)):
        if not name.endswith(".yaml"):
            continue
        raw = read_flat(os.path.join(path, name))
        row = {k: v.strip("'\"") for k, v in raw.items()}
        status = row.get("status", "")
        if status in counts:
            counts[status] += 1
        if status == "claimed":
            since = row.get("claimed_at", "")
            who, task = row.get("claimed_by", ""), row.get("task_id", "")
            claimed.append(f"- {who}: {task} (since {since})")
    return counts, claimed


def render(board_dir, root=ROOT):
    """Write ``board_dir/board.md`` from the status files and queue files."""
    names = [n[: -len(".yaml")] for n in os.listdir(board_dir) if n.endswith(".yaml")]
    names = [n for n in names if not n.startswith("tanya")]
    names.sort(key=lambda n: (ORDER.index(n) if n in ORDER else len(ORDER), n))
    rows = {n: read_flat(os.path.join(board_dir, n + ".yaml")) for n in names}
    cmds = active_cmds(os.path.join(root, "queue", "shogun_to_karo.yaml"))
    qc = recent_qc(os.path.join(root, "queue", "reports", "metsuke_report.yaml"))
    out = ["# Command-layer board", "", "## Active cmds", ""]
    out += [f"- {cid}: {purpose}" for cid, purpose in cmds] or ["- (none)"]
    counts, claimed = pool_summary(os.path.join(root, "queue", "task_pool"))
    out += ["", "## Pool", "", " / ".join(f"{k} {v}" for k, v in counts.items())]
    out += claimed
    out += ["", "## Agents", "", "| agent | " + " | ".join(COLUMNS) + " |"]
    out.append("|---" * (len(COLUMNS) + 1) + "|")
    for n in names:
        cells = [rows[n].get(c, "") for c in COLUMNS]
        out.append(f"| {n} | " + " | ".join(cells) + " |")
    out += ["", "## Open questions / escalations", ""]
    asked = [n for n in names if rows[n].get("question")]
    questions = [f"- {n}: {rows[n]['question']}" for n in asked]
    out += questions or ["- (none)"]
    out += ["", "## Recent QC", ""]
    out += [f"- {task}: {verdict}" for task, verdict in qc] or ["- (none)"]
    tmp = os.path.join(board_dir, "board.md.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, os.path.join(board_dir, "board.md"))


if __name__ == "__main__":
    board = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "queue", "board")
    render(board, sys.argv[2] if len(sys.argv) > 2 else ROOT)
