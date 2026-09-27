#!/usr/bin/env python3
"""Read-only probe: when did a path (file or dir) first enter a repo's mainline branch?

usage:
  python3 probe.py --repo <path-to-repo> --ref <mainline-ref> <path> [<path> ...]
  python3 probe.py --repo <path-to-repo> --ref <mainline-ref> --tree <treeish-for-existence> <path> [<path> ...]

Only runs: git log / rev-list / merge-base --is-ancestor / show / diff / cat-file -e.
Never fetches, checks out, creates worktrees, or stashes.

--repo and --ref are REQUIRED and must not be hardcoded by the caller: this tool is meant
to be reused across repos and mainline-branch names (e.g. upstream/master, origin/main).

Steps per path (see SKILL.md for the full rationale / pitfalls P1-P8):
  1. O = oldest commit that ADDS the path (git log --full-history --diff-filter=A --reverse,
     no --follow). For a directory, the oldest commit adding any file under it.
  2. rename chain (files only): git log --follow --name-status --diff-filter=R; accept an R
     entry only if the old name is confirmed gone in that commit (git cat-file -e fails) --
     otherwise --follow may have jumped to an unrelated but similar file (P2).
  3. M = oldest first-parent commit of <ref> containing O (binary search with
     git merge-base --is-ancestor). M is a merge ('Merge pull request #N'), a squash
     ('... (#N)') or a direct commit (O itself on first-parent => 'pre-PR / direct commit').
  4. step3b / P8: is-ancestor(O, M) being true does NOT guarantee the path exists in M's
     tree -- it may have been added then deleted again inside the same feature branch before
     that branch was merged. Verify with `git cat-file -e <M>:<path>` (try every name in the
     rename chain too). If absent, advance along the first-parent chain to the first commit
     that actually contains the path, and re-derive O among the candidates integrated there.
  5. PR number from M's subject; date = committer date of M; author date noted if different.

This script only produces CANDIDATES. A human must still confirm each row by hand:
  - git merge-base --is-ancestor <O> <M>            (must exit 0 / true)
  - git merge-base --is-ancestor <O> <M>^            (must exit 1 / false -- M is the EARLIEST)
  - git cat-file -e <M>:<path>                       (must exit 0 -- the tree actually has it)
  - git log -1 --format='%H%n%s%n%cd (author %ad)' --date=short <M>
Never copy this script's output straight into a report without running those four checks.
"""
import argparse
import functools
import re
import shutil
import subprocess
import sys

GIT = shutil.which("git") or "/usr/bin/git"


def build_g(repo):
    def g(*a):
        return subprocess.run([GIT, "-C", repo, *a], capture_output=True, text=True).stdout.strip()
    return g


def build_is_anc(repo):
    def is_anc(a, b):
        return subprocess.run([GIT, "-C", repo, "merge-base", "--is-ancestor", a, b]).returncode == 0
    return is_anc


def build_cat_exists(repo):
    def exists(commit, path):
        return subprocess.run([GIT, "-C", repo, "cat-file", "-e", f"{commit}:{path}"], capture_output=True).returncode == 0
    return exists


class Probe:
    def __init__(self, repo, ref):
        self.repo = repo
        self.ref = ref
        self.g = build_g(repo)
        self.is_anc = build_is_anc(repo)
        self.exists = build_cat_exists(repo)
        self._fp_chain = None

    def fp_chain(self):
        # oldest -> newest first-parent commits of <ref>
        if self._fp_chain is None:
            self._fp_chain = list(reversed(self.g("rev-list", "--first-parent", self.ref).splitlines()))
        return self._fp_chain

    def integrating(self, c):
        ch = self.fp_chain()
        lo, hi = 0, len(ch) - 1
        if not self.is_anc(c, ch[hi]):
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            if self.is_anc(c, ch[mid]):
                hi = mid
            else:
                lo = mid + 1
        return ch[lo]

    def add_candidates(self, path, tip=None):
        """All commits that ADD path anywhere in tip's history (--full-history is REQUIRED:
        default history simplification silently drops adds of paths absent at tip -- P3).
        No cap: directories can have hundreds of add events; the oldest may be last."""
        tip = tip or self.ref
        return self.g("log", "--full-history", "--diff-filter=A", "--format=%H", tip, "--", path).splitlines()

    def oldest_add(self, path, tip=None):
        c = self.add_candidates(path, tip)
        return min(c, key=lambda x: int(self.g("log", "-1", "--format=%ct", x))) if c else None

    def rename_chain(self, path, tip=None):
        """Genuine renames only, following back from `path`: [(commit, old_name, new_name)].
        Accept an R entry only if (a) its new name is the path currently being followed and
        (b) the old name no longer exists in that commit (a copy from a similar file is NOT
        a rename -- P2. --follow alone is unsafe: it jumps to similar files)."""
        tip = tip or self.ref
        out = self.g("log", "--follow", "--name-status", "--diff-filter=R", "--format=@%H", tip, "--", path)
        chain, cur, following = [], None, path
        for line in out.splitlines():
            if line.startswith("@"):
                cur = line[1:]
                continue
            m = re.match(r"R\d+\t(\S+)\t(\S+)", line)
            if not m or m.group(2) != following:
                continue
            old = m.group(1)
            if not self.exists(cur, old):
                chain.append((cur, old, following))
                following = old
        return chain

    def subj(self, c):
        return self.g("log", "-1", "--format=%s", c)

    def dates(self, c):
        return self.g("log", "-1", "--format=%cd %ad", "--date=short", c).split()

    def pr_of(self, c):
        s = self.subj(c)
        m = re.search(r"Merge pull request #(\d+)", s) or re.search(r"\(#(\d+)\)\s*$", s)
        return m.group(1) if m else None

    def probe(self, path, tip=None):
        tip = tip or self.ref
        O = self.oldest_add(path, tip)
        name = path
        notes = []
        if not O:
            return {"path": path, "error": "no A commit found"}
        # directory? decide from the add commit itself (the path may no longer exist at tip)
        is_dir = any(
            l.startswith(path.rstrip("/") + "/")
            for l in self.g("show", "--name-only", "--format=", "--diff-filter=A", O).splitlines()
        )
        if not is_dir:
            for c, old, new in self.rename_chain(path, tip):
                O2 = self.oldest_add(old, tip)
                if O2 and int(self.g("log", "-1", "--format=%ct", O2)) < int(self.g("log", "-1", "--format=%ct", O)):
                    notes.append(f"rename {old} -> {new} @ {c[:11]}")
                    O, name = O2, old
        cands = {O} | set(self.add_candidates(name, tip))
        best = None
        for c in cands:
            m = self.integrating(c)
            if m is None:
                continue
            pos = self.fp_chain().index(m)
            if best is None or pos < best[0] or (
                pos == best[0] and int(self.g("log", "-1", "--format=%ct", c)) < int(self.g("log", "-1", "--format=%ct", best[1]))
            ):
                best = (pos, c, m)
        if not best:
            return {"path": path, "O": O, "error": f"no add commit reachable from {tip}"}
        _, O, M = best

        # step3b / P8: O being an ancestor of M is necessary but NOT sufficient -- the path
        # may have been deleted/renamed inside the branch before the merge. Require that some
        # name of the path exists in M's tree; otherwise advance to the earliest first-parent
        # commit that has it and re-pick O among the add candidates integrated exactly there.
        names = [path] + [old for _, old, _ in self.rename_chain(path, tip)] if not is_dir else [path]

        def has_any(c):
            return any(self.exists(c, n) for n in names)

        if not has_any(M) and is_dir:
            # a directory may have been renamed in-branch (e.g. egs/vcc2020/voc1 -> egs/vcc20/voc1):
            # look for the same leaf directory name among files added by M's first-parent diff.
            leaf = "/" + path.rstrip("/").split("/")[-1] + "/"
            added = self.g("diff", "--name-only", "--diff-filter=A", M + "^", M).splitlines()
            hits = sorted({a[:a.index(leaf) + len(leaf) - 1] for a in added if leaf in a})
            if hits:
                notes.append(f"P8-dir: {path} absent at {M[:11]} but same leaf dir present as {hits[0]} (renamed in-branch); M kept, verify by hand")
                names = names + hits

        if not has_any(M):
            ch = self.fp_chain()
            i = ch.index(M) + 1
            while i < len(ch) and not has_any(ch[i]):
                i += 1
            if i >= len(ch):
                return {"path": path, "O": O, "error": "path never present on first-parent chain after its add"}
            M2 = ch[i]
            notes.append(f"P8: {M[:11]} contains add {O[:11]} but not the path (deleted in-branch); first first-parent commit with the path is {M2[:11]}")
            M = M2
            for c in sorted(cands, key=lambda x: int(self.g("log", "-1", "--format=%ct", x))):
                if self.is_anc(c, M) and not self.is_anc(c, ch[i - 1]):
                    O = c
                    break

        nparents = self.g("rev-list", "--parents", "-n1", M).count(" ")
        kind = "merge" if nparents >= 2 else ("squash" if self.pr_of(M) else "direct")
        cd, ad = self.dates(M)
        if cd != ad:
            notes.append(f"author date {ad} != committer date {cd}")
        if kind == "direct":
            notes.append("pre-PR / direct commit")
        if kind == "merge" and not self.pr_of(M):
            notes.append("no PR number (direct branch merge)")
        return {
            "path": path,
            "name_at_add": name,
            "O": O[:11],
            "O_date": self.dates(O)[0],
            "O_subj": self.subj(O)[:60],
            "M": M[:11],
            "M_date": cd,
            "kind": kind,
            "PR": self.pr_of(M),
            "notes": notes,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", "-R", required=True, help="path to the git repo (read-only; never fetched/checked out)")
    ap.add_argument("--ref", required=True, help="mainline ref to search, e.g. upstream/master, origin/main")
    ap.add_argument("--tree", help="alternate treeish to use for the existence/candidate lookup (e.g. a pre-deletion snapshot like '<removal-commit>^')")
    ap.add_argument("paths", nargs="+", help="one or more file/directory paths to probe")
    args = ap.parse_args()

    p = Probe(args.repo, args.ref)
    tip = args.tree or args.ref
    for path in args.paths:
        r = p.probe(path, tip)
        if "error" in r:
            print(f"{r['path']:40s} ERROR {r['error']}")
            continue
        print(
            f"{r['path']:40s} M={r['M']} {r['M_date']} {r['kind']:6s} PR={r['PR'] or '-':5s} "
            f"O={r['O']} {r['O_date']} name@add={r['name_at_add']} | {r['O_subj']} | {'; '.join(r['notes'])}"
        )


if __name__ == "__main__":
    main()
