#!/usr/bin/env python3
"""Break every line of a Python/YAML/shell file into a category, so "real code" can be
compared across codebases without docstrings/comments/blank lines inflating the count.

Python  -> code / docstring / comment / blank
YAML    -> config / comment / blank   (plus a leaf-value count via pyyaml)
Shell   -> config / comment / blank   (plus a NAME=value assignment count)

Read-only: only reads file contents (via `git show <rev>:<path>` in --repo mode, or a
plain filesystem read in --files mode). Never writes to the target repo/files, never
fetches, never checks out. No project-specific paths or values are embedded here; the
repo, revision and target paths are always given as arguments.

Docstring detection uses `ast`, not a "line starts with a quote" heuristic: a docstring is
the first statement of a Module/ClassDef/FunctionDef/AsyncFunctionDef body, and only counts
if that statement is a bare string-constant expression (ast.Expr wrapping an ast.Constant
whose value is a str). This correctly:
  - covers multi-line docstrings in full (uses the AST node's lineno..end_lineno range,
    not just the first line),
  - excludes f-strings (an f-string is ast.JoinedStr, never ast.Constant, and a bare
    f-string statement is not a docstring under Python's own semantics -- it doesn't
    populate __doc__),
  - excludes ordinary string-literal statements that merely happen to be the first line of
    a *later* block (only the module/class/def's own first body statement counts).

Comment detection uses `tokenize`, not "line strip starts with #": a line is only
classified as a comment if the *only* non-trivial token it contains is a COMMENT token.
This means:
  - a `# real comment` line -> comment,
  - a line that is part of a (non-docstring) multi-line string whose content happens to
    start with `#` after stripping -> NOT a comment (it carries a STRING token) -> code,
  - a line with trailing code plus an inline `# comment` -> code (this tool classifies
    whole physical lines, one category each; a line containing any non-comment token is
    "code", even if it also has a trailing comment -- there is no half-comment category).

usage:
  line_breakdown.py --repo R --rev REV --paths p1 p2 ... [--exclude-regex RE] [--csv out.csv] [--label L]
  line_breakdown.py --files f1 f2 ...                    [--exclude-regex RE] [--csv out.csv] [--label L]
"""
import argparse, ast, csv, io, os, re, subprocess, sys, tokenize
from collections import defaultdict


def git_show(repo, rev, path):
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def git_ls_tree(repo, rev, path):
    return subprocess.run(["git", "-C", repo, "ls-tree", "-r", rev, "--", path],
                           capture_output=True, text=True).stdout.splitlines()


def yaml_leaves(text):
    """Count YAML leaf values (a dict/list contributes the sum of its children; a scalar
    contributes 1; an empty dict/list/None contributes 1, so an empty mapping still counts
    as one "item" rather than vanishing). Requires pyyaml; refuses to silently approximate
    unless RECIPE_SIZE_ALLOW_YAML_FALLBACK=1 is set (matching the source tool's policy)."""
    try:
        import yaml
    except ImportError:
        if os.environ.get("RECIPE_SIZE_ALLOW_YAML_FALLBACK") != "1":
            sys.exit("line_breakdown.py: pyyaml is required to count YAML leaves (pip install pyyaml), "
                     "or set RECIPE_SIZE_ALLOW_YAML_FALLBACK=1 to accept an approximate regex count")
        print("WARNING: pyyaml missing, YAML leaf counts are approximate", file=sys.stderr)
        return sum(1 for l in text.splitlines() if re.match(r"^\s*[-\w\.]+\s*:\s*\S", l) and not l.lstrip().startswith("#"))

    def cnt(o):
        if isinstance(o, dict):
            return sum(cnt(v) for v in o.values()) if o else 1
        if isinstance(o, list):
            return sum(cnt(v) for v in o) if o else 1
        return 1
    try:
        return sum(cnt(d) for d in yaml.safe_load_all(text) if d is not None)
    except Exception:
        return -1  # malformed YAML: caller sees -1 and should not treat it as a real count


def python_docstring_lines(text):
    """1-indexed physical line numbers that belong to a genuine docstring. Returns
    (line_set, syntax_error: bool). If ast.parse fails, line_set is empty and
    syntax_error is True -- callers must not silently treat that as "no docstrings",
    but flag the file so the counts are read as an approximation of comment/blank only."""
    lines = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return lines, True
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                val = getattr(body[0], "value", None)
                # ast.Constant with a str value only -- deliberately excludes f-strings
                # (ast.JoinedStr), bytes literals, numbers, etc. A bare f-string statement
                # is never a docstring in real Python (it doesn't set __doc__).
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    start = body[0].lineno
                    end = getattr(body[0], "end_lineno", start)
                    lines.update(range(start, end + 1))
    return lines, False


def python_comment_only_lines(text):
    """1-indexed physical line numbers whose *only* non-trivial token is a COMMENT.
    Returns (line_set, tokenize_failed: bool). A line that is part of a multi-line string
    (STRING token spanning several lines) is never included here, even if its stripped
    content starts with '#' -- it carries a STRING token, not just a COMMENT token, so it
    is correctly left for the caller to classify as code (or docstring, if ast already
    claimed it)."""
    per_line_types = defaultdict(set)
    ignored = {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
               tokenize.ENDMARKER, tokenize.ENCODING}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            ttype = tok.type
            if ttype in ignored:
                continue
            start_line, end_line = tok.start[0], tok.end[0]
            for ln in range(start_line, end_line + 1):
                per_line_types[ln].add(ttype)
    except (tokenize.TokenizeError, IndentationError, SyntaxError, ValueError):
        return set(), True
    comment_lines = {ln for ln, types in per_line_types.items() if types == {tokenize.COMMENT}}
    return comment_lines, False


def breakdown_python(text):
    doc_lines, ast_syntax_error = python_docstring_lines(text)
    comment_lines, tokenize_failed = python_comment_only_lines(text)
    lines = text.splitlines()
    code = docstring = comment = blank = 0
    naive_fallback = tokenize_failed  # only used if tokenize itself could not run
    for i, raw in enumerate(lines, start=1):
        s = raw.strip()
        if i in doc_lines:
            docstring += 1
        elif s == "":
            blank += 1
        elif (not naive_fallback and i in comment_lines) or (naive_fallback and s.startswith("#")):
            comment += 1
        else:
            code += 1
    return dict(total=len(lines), code=code, docstring=docstring, comment=comment, blank=blank,
                syntax_error=ast_syntax_error, tokenize_failed=tokenize_failed)


def breakdown_config(text):
    """YAML/shell: config (real content) / comment / blank. No docstring concept.
    Comment detection here IS the naive "stripped line starts with #" heuristic (YAML/shell
    do not have Python's tokenize module available for their own grammars); this is
    documented as a known limitation in SKILL.md, not silently hidden."""
    lines = text.splitlines()
    config = comment = blank = 0
    for raw in lines:
        s = raw.strip()
        if s == "":
            blank += 1
        elif s.startswith("#"):
            comment += 1
        else:
            config += 1
    return dict(total=len(lines), config=config, comment=comment, blank=blank)


def classify_and_count(path, text, exclude_regex):
    if exclude_regex and re.search(exclude_regex, path):
        return None
    ext = os.path.splitext(path)[1]
    is_shell = ext == ".sh" or text.startswith("#!/usr/bin/env bash") or text.startswith("#!/bin/bash")
    if ext == ".py":
        b = breakdown_python(text)
        items = len(re.findall(r"^def |^class ", text, re.M))
        return dict(path=path, kind="python", lines=b["total"], code_lines=b["code"],
                    docstring_lines=b["docstring"], comment_lines=b["comment"], blank_lines=b["blank"],
                    items=items, symlink_target="", syntax_error=b["syntax_error"],
                    tokenize_failed=b["tokenize_failed"])
    if ext in (".yaml", ".yml"):
        b = breakdown_config(text)
        items = yaml_leaves(text)
        return dict(path=path, kind="yaml", lines=b["total"], code_lines=b["config"],
                    docstring_lines=0, comment_lines=b["comment"], blank_lines=b["blank"],
                    items=items, symlink_target="", syntax_error=False, tokenize_failed=False)
    if is_shell:
        b = breakdown_config(text)
        items = len(re.findall(r"^[A-Za-z_][A-Za-z0-9_]*=", text, re.M))
        return dict(path=path, kind="shell", lines=b["total"], code_lines=b["config"],
                    docstring_lines=0, comment_lines=b["comment"], blank_lines=b["blank"],
                    items=items, symlink_target="", syntax_error=False, tokenize_failed=False)
    lines = text.splitlines()
    return dict(path=path, kind=ext or "other", lines=len(lines), code_lines=len(lines),
                docstring_lines=0, comment_lines=0, blank_lines=0, items=0, symlink_target="",
                syntax_error=False, tokenize_failed=False)


def collect_rows_git(repo, rev, paths, exclude_regex, label):
    rows = []
    for p in paths:
        for l in git_ls_tree(repo, rev, p):
            mode, typ, sha, path = l.split(None, 3)
            if exclude_regex and re.search(exclude_regex, path):
                continue
            if mode == "120000":
                rows.append(dict(label=label, root=p, path=path, kind="symlink", lines=0, code_lines=0,
                                  docstring_lines=0, comment_lines=0, blank_lines=0, items=0,
                                  symlink_target=git_show(repo, rev, path).strip(),
                                  syntax_error=False, tokenize_failed=False))
                continue
            text = git_show(repo, rev, path)
            if text is None:
                continue
            r = classify_and_count(path, text, None)  # already filtered above
            if r is not None:
                rows.append({**r, "label": label, "root": p})
    return rows


def expand_files(paths):
    """Expand each root path into individual files: a plain file passes through as-is;
    a directory is walked recursively (os.walk, sorted for deterministic output) and every
    contained file is yielded. Symlinked directories are never followed (os.walk's default
    followlinks=False) -- a symlinked subdirectory found while walking is silently skipped,
    not recursed into. A root path that is itself a symlink is yielded as-is (never treated
    as a directory) so the existing symlink-recording branch below still handles it."""
    for root in paths:
        if os.path.isdir(root) and not os.path.islink(root):
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames.sort()
                for name in sorted(filenames):
                    yield root, os.path.join(dirpath, name)
        else:
            yield root, root


def collect_rows_files(paths, exclude_regex, label):
    rows = []
    for root, p in expand_files(paths):
        if exclude_regex and re.search(exclude_regex, p):
            continue
        if os.path.islink(p):
            rows.append(dict(label=label, root=root, path=p, kind="symlink", lines=0, code_lines=0,
                              docstring_lines=0, comment_lines=0, blank_lines=0, items=0,
                              symlink_target=os.readlink(p), syntax_error=False, tokenize_failed=False))
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        r = classify_and_count(p, text, None)
        if r is not None:
            rows.append({**r, "label": label, "root": root})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo")
    ap.add_argument("--rev")
    ap.add_argument("--paths", nargs="+")
    ap.add_argument("--files", nargs="+")
    ap.add_argument("--exclude-regex", default=r"(README|RESULTS|\.md$|__pycache__)")
    ap.add_argument("--csv")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    if a.files:
        rows = collect_rows_files(a.files, a.exclude_regex, a.label)
    elif a.repo and a.rev and a.paths:
        rows = collect_rows_git(a.repo, a.rev, a.paths, a.exclude_regex, a.label)
    else:
        sys.exit("line_breakdown.py: give either --files f1 f2 ... or --repo R --rev REV --paths p1 p2 ...")

    fieldnames = ["label", "root", "path", "kind", "lines", "code_lines", "docstring_lines",
                  "comment_lines", "blank_lines", "items", "symlink_target", "syntax_error", "tokenize_failed"]
    if a.csv:
        new = not os.path.exists(a.csv)
        with open(a.csv, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            if new:
                w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fieldnames})

    tot = {}
    for r in rows:
        t = tot.setdefault(r["root"], dict(files=0, lines=0, code=0, docstring=0, comment=0, blank=0, items=0))
        t["files"] += 1
        t["lines"] += r["lines"]
        t["code"] += r["code_lines"]
        t["docstring"] += r["docstring_lines"]
        t["comment"] += r["comment_lines"]
        t["blank"] += r["blank_lines"]
        t["items"] += r["items"] if isinstance(r["items"], int) and r["items"] > 0 else 0
    for k, v in tot.items():
        print(f"{a.label:14s} {k:34s} files={v['files']:3d} lines={v['lines']:5d} "
              f"code_or_config={v['code']:5d} docstring={v['docstring']:4d} comment={v['comment']:4d} "
              f"blank={v['blank']:4d} items={v['items']}")


if __name__ == "__main__":
    main()
