#!/usr/bin/env python3
"""Functional test for line_breakdown.py, using a hand-crafted fixture
(tests/fixture_edge_cases.py) that mixes docstrings, comments, blank lines, an f-string,
and a non-docstring multi-line string whose content happens to start with '#'.

Run: python3 tests/test_line_breakdown.py   (exit 0 = all assertions passed)
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import line_breakdown as lb  # noqa: E402

FIXTURE = os.path.join(HERE, "fixture_edge_cases.py")


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    return cond


def main():
    with open(FIXTURE, encoding="utf-8") as f:
        text = f.read()

    doc_lines, syntax_error = lb.python_docstring_lines(text)
    comment_lines, tokenize_failed = lb.python_comment_only_lines(text)

    ok = True
    ok &= check("no ast syntax error on the fixture", not syntax_error)
    ok &= check("no tokenize failure on the fixture", not tokenize_failed)

    # --- docstring detection ---
    ok &= check("module docstring lines 1-4 detected", {1, 2, 3, 4} <= doc_lines)
    ok &= check("class docstring line 9 detected", 9 in doc_lines)
    ok &= check("function docstring line 12 detected (even though code follows on the "
                "same physical line)", 12 in doc_lines)
    ok &= check("f-string statement (line 25) is NOT treated as a docstring",
                25 not in doc_lines)
    ok &= check("plain multi-line string (lines 18-20) is NOT treated as a docstring "
                "(it is the 3rd statement in baz(), not the function's first)",
                not ({18, 19, 20} & doc_lines))

    # --- comment detection (tokenize-based, not naive startswith('#')) ---
    ok &= check("real comment-only line 16 detected as comment", 16 in comment_lines)
    ok &= check("module-level trailing comment line 29 detected as comment",
                29 in comment_lines)
    ok &= check("code line 17 with a trailing inline comment is NOT comment-only "
                "(whole-line granularity: any real code makes the line 'code')",
                17 not in comment_lines)
    ok &= check("line 19, whose stripped content starts with '#' but is really inside a "
                "plain (non-docstring) multi-line string, is NOT misclassified as a "
                "comment", 19 not in comment_lines)
    ok &= check("line 18 (opening a multi-line string) is NOT a comment",
                18 not in comment_lines)

    # --- aggregate breakdown sanity ---
    b = lb.breakdown_python(text)
    ok &= check("aggregate total == code+docstring+comment+blank",
                b["total"] == b["code"] + b["docstring"] + b["comment"] + b["blank"])
    ok &= check("aggregate docstring count is at least the 6 known docstring lines "
                "(1,2,3,4,9,12)", b["docstring"] >= 6)
    ok &= check("aggregate comment count is exactly 2 (lines 16 and 29 only)",
                b["comment"] == 2)

    # --- YAML / shell breakdown smoke test ---
    yaml_text = "a: 1\n# a comment\n\nb:\n  c: 2\n  d: 3\n"
    yb = lb.breakdown_config(yaml_text)
    ok &= check("YAML breakdown: 1 comment line", yb["comment"] == 1)
    ok &= check("YAML breakdown: 1 blank line", yb["blank"] == 1)
    ok &= check("YAML breakdown: 4 config lines (a:, b:, c:, d:)", yb["config"] == 4)
    leaves = lb.yaml_leaves(yaml_text)
    ok &= check("YAML leaf count: a=1, c=2, d=3 -> 3 leaves", leaves == 3)

    shell_text = "#!/usr/bin/env bash\n# a comment\n\nFOO=bar\necho \"$FOO\"\n"
    sb = lb.breakdown_config(shell_text)
    ok &= check("shell breakdown: 2 comment lines (shebang + real comment)",
                sb["comment"] == 2)
    ok &= check("shell breakdown: 1 blank line", sb["blank"] == 1)
    ok &= check("shell breakdown: 2 config lines (FOO=bar, echo)", sb["config"] == 2)

    # --- F1 regression: --files must accept a directory, not just individual files ---
    dir_rows = lb.collect_rows_files([HERE], r"test_line_breakdown\.py$", "")
    dir_paths = {r["path"] for r in dir_rows}
    ok &= check("collect_rows_files(directory) does not raise IsADirectoryError "
                "and returns at least one row", len(dir_rows) >= 1)
    ok &= check("collect_rows_files(directory) walks into the directory and finds "
                "fixture_edge_cases.py", FIXTURE in dir_paths)
    ok &= check("collect_rows_files(directory) applies exclude_regex per discovered "
                "file (test_line_breakdown.py itself is excluded)",
                not any(p.endswith("test_line_breakdown.py") for p in dir_paths))
    ok &= check("collect_rows_files(directory) rows report the directory itself as "
                "'root', not the individual file", all(r["root"] == HERE for r in dir_rows))

    print()
    if ok:
        print("ALL ASSERTIONS PASSED")
        return 0
    else:
        print("SOME ASSERTIONS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
