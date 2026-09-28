#!/usr/bin/env python3
"""Per-file added/deleted line counts from `git diff`, with renames handled correctly.

Problem this fixes: `git diff --numstat` (without -z) and `git diff --name-status` (without
-z) both abbreviate a rename whose old and new path share a directory prefix, e.g.
`espnet2/gan_tts/{vits => hifigan}/hifigan.py` or, for a full path replacement, `old => new`
with no braces. If you match numstat's path column against name-status's (always full,
unabbreviated) new path by exact string equality, abbreviated rename rows silently fail to
match and their line counts get treated as zero. This is a real bug that was found by hand
on the ESPnet repo (PR #3449 lost 109 lines, PR #4479 lost 30 lines this way) -- see SKILL.md.

Fix: read BOTH `--numstat -z` and `--name-status -z`. With -z, git NEVER abbreviates a
rename: it prints the old path and the new path as two separate NUL-terminated fields
instead of one abbreviated string. Parsing the -z form of each command separately and then
joining on the (always exact, always current) new path removes the ambiguity entirely.

usage:
  python3 numstat_paths.py --repo <path> --base <rev> --head <rev> [--paths <pathspec> ...]
                            [--no-rename-detection] [--csv <out.csv>]

Output: one row per changed file: status, old_path (empty unless renamed/copied), new_path,
added, deleted, total (added+deleted, empty for binary files), similarity (rename/copy % if
applicable).

Read-only: runs only `git diff --numstat -z` and `git diff --name-status -z` against the
given repo. Never fetches, checks out, or writes into the target repo.
"""
import argparse
import csv
import subprocess
import sys


def git_diff_z(repo, sub, base, head, paths, rename_detection):
    args = ["git", "-C", repo, "diff", sub, "-z"]
    if rename_detection:
        args.append("-M")
    args += [base, head]
    if paths:
        args += ["--", *paths]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    # git terminates every field with NUL, including the last one -> drop the trailing empty token
    tokens = out.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    return tokens


def parse_numstat(repo, base, head, paths, rename_detection):
    """Returns {new_path: (added, deleted)}; added/deleted are None for binary files.
    Rename/copy rows arrive as ["add\\tdel\\t", "old_path", "new_path"] (three tokens);
    every other row arrives as a single token "add\\tdel\\tpath"."""
    tokens = git_diff_z(repo, "--numstat", base, head, paths, rename_detection)
    result = {}
    i = 0
    while i < len(tokens):
        rec = tokens[i]
        parts = rec.split("\t")
        add_s, del_s = parts[0], parts[1]
        added = None if add_s == "-" else int(add_s)
        deleted = None if del_s == "-" else int(del_s)
        if len(parts) >= 3 and parts[2]:
            path = parts[2]
            i += 1
        else:
            # rename/copy: this record's 3rd field is empty; old path and new path are the
            # next two NUL-terminated tokens
            path = tokens[i + 2]
            i += 3
        result[path] = (added, deleted)
    return result


def parse_name_status(repo, base, head, paths, rename_detection):
    """Returns a list of (status, old_path_or_None, similarity_or_None, new_path).
    A100/M/D/etc. rows are two tokens (status, path); R100/C100 rows are three tokens
    (status, old_path, new_path)."""
    tokens = git_diff_z(repo, "--name-status", base, head, paths, rename_detection)
    result = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        letter = status[0]
        similarity = int(status[1:]) if len(status) > 1 and status[1:].isdigit() else None
        if letter in ("R", "C"):
            old_path, new_path = tokens[i + 1], tokens[i + 2]
            result.append((letter, old_path, similarity, new_path))
            i += 3
        else:
            path = tokens[i + 1]
            result.append((letter, None, None, path))
            i += 2
    return result


def diff_files(repo, base, head, paths=None, rename_detection=True):
    """The combined, correct per-file view: status + old/new path + line counts.
    Joins name-status (authoritative for status/old-path/new-path) with numstat (authoritative
    for line counts) on the exact NEW path -- both come from -z, so this join never misses a
    renamed file the way a plain-text abbreviation-vs-full-path match would."""
    lines = parse_numstat(repo, base, head, paths, rename_detection)
    statuses = parse_name_status(repo, base, head, paths, rename_detection)
    rows = []
    for letter, old_path, similarity, new_path in statuses:
        added, deleted = lines.get(new_path, (None, None))
        total = None if added is None or deleted is None else added + deleted
        rows.append({
            "status": letter,
            "similarity": similarity if similarity is not None else "",
            "old_path": old_path or "",
            "new_path": new_path,
            "added": "" if added is None else added,
            "deleted": "" if deleted is None else deleted,
            "total": "" if total is None else total,
            "binary": added is None,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", "-R", required=True, help="path to the git repo (read-only)")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--paths", nargs="*", default=None, help="pathspec(s) to restrict the diff to, e.g. espnet2 espnet3")
    ap.add_argument("--no-rename-detection", action="store_true", help="omit -M (rename/copy detection disabled)")
    ap.add_argument("--csv", default=None, help="write rows to this CSV path instead of stdout")
    a = ap.parse_args()

    rows = diff_files(a.repo, a.base, a.head, a.paths, rename_detection=not a.no_rename_detection)

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["status", "similarity", "old_path", "new_path", "added", "deleted", "total", "binary"])
            w.writeheader()
            w.writerows(rows)
    else:
        for r in rows:
            rename = f"{r['old_path']} => {r['new_path']}" if r["old_path"] else r["new_path"]
            print(f"{r['status']}{r['similarity']:<4}\t+{r['added']}\t-{r['deleted']}\t{rename}")
    n_files = len(rows)
    total_lines = sum(r["total"] for r in rows if r["total"] != "")
    print(f"# n_files={n_files} total_changed_lines={total_lines}", file=sys.stderr)


if __name__ == "__main__":
    main()
