# Chunk Task Template (Karo → Ashigaru implementation/test tasks)

When Karo delegates a bounded implementation-or-test chunk to an Ashigaru
(especially a free/babel worker), use this fixed structure. Karo decides
only the CONTENT fields below; the surrounding skeleton is boilerplate and
should be reused verbatim every time - don't re-derive it per task.

Rationale: tasks that are small, point at a stable/already-tested API, and
use this skeleton have a high success rate with no rework needed. Tasks
that skip the skeleton (no patch-file deliverable, no explicit scope
limits, no design-doc pointer) have repeatedly produced silent scope
violations, fabricated signatures, and undetected test deletion.

## What Karo decides (content, ~5-10 lines)

- `WORKTREE_PATH`, `BRANCH` - where the ashigaru works.
- `DESIGN_DOC_PATH` - absolute path to the spec/design doc to read (never
  a bare relative path - untracked design docs do not exist in a fresh
  worktree unless explicitly copied in; always copy it in and reference
  the absolute path).
- `BASELINE_CMD` - the pytest invocation that must pass before starting
  (scope it to the relevant test files/dirs, not the whole suite).
- `READ_FIRST` - the specific file(s)/function(s) to actually read before
  writing anything, when prior knowledge of similar systems could tempt a
  wrong guess at a signature or behavior.
- `TASK` - 3-8 sentences: what to build/test, which already-implemented
  functions to use (don't modify), and the single most likely wrong
  assumption to guard against (if there's a known one - e.g. "a role name
  does not necessarily match its log_dir key").
- `SCOPE_LIMIT` - explicit list of what NOT to touch (other functions,
  other worktrees, production code when only tests are wanted).
- `PATCH_NAME` - filename for the patch under the shared scratch dir.

## Fixed skeleton (reuse verbatim)

```
# Task: {TASK_TITLE}

Working directory: {WORKTREE_PATH}, branch {BRANCH}. First:
  pwd && git branch --show-current
  {BASELINE_CMD}
(must pass before you start)

Read {DESIGN_DOC_PATH}'s {relevant section/items only - name them}.
(If that file doesn't exist, STOP and report - don't proceed without
reading it.)

## Context: what already exists, don't modify any of it
{READ_FIRST - file paths and function names, one line each}

## Task
{TASK}

This should require ZERO production code changes if the task is test-only
- if something doesn't work as expected, report exactly what broke and
why, don't patch around it or weaken the test to make it pass.

## Scope limit
{SCOPE_LIMIT}

## Deliverable: a patch file, not direct changes to the shared branch
  cd {WORKTREE_PATH}
  git add -A
  git diff --cached > {SHARED_SCRATCH_DIR}/{PATCH_NAME}

Do not run git commit/push/reset, and don't touch any other worktree.

## Self-check before reporting done
  {BASELINE_CMD}
Report the patch path and the full pytest output. If it fails, report the
failure and do NOT produce the patch - a "done" report must always include
real command output, not a summary claim.
```

## Worktree setup (fast - use sparse-checkout, not a full checkout)

A full `git worktree add` checks out the entire repo (10000+ files) and
can take 1-2+ minutes on NFS. Scope it to what's actually needed:

```bash
git worktree add --no-checkout -b <new-branch> <path> <base-branch>
cd <path>
git sparse-checkout init --cone
git sparse-checkout set espnet3 egs3 test design
git checkout <new-branch>
```

This drops to a few seconds. Exclude `espnet2`/`egs2` (legacy, unrelated)
unless the task specifically needs them.

The design doc (e.g. `design/config_tree_fix.md`) is typically UNTRACKED
in the source repo - sparse-checkout only affects tracked files, so after
checkout, create the directory and copy it in by hand:

```bash
mkdir -p <path>/design
cp <source_repo>/design/<doc>.md <path>/design/<doc>.md
```

Prefer `/tmp/<name>` for throwaway/short-lived worktrees - it's fast, but
can be cleared by the OS at any time, so don't rely on it surviving past a
single session. For anything that needs to persist, use a path under the
project's own `wt/` directory (persistent disk) instead.

## Rules this template exists to enforce (see also F004, CLAUDE.md rules)

- Each ashigaru works in its own dedicated worktree - never the main
  checkout or another agent's worktree.
- Commit (or deliver as a patch) at the end of each chunk - never leave
  finished work uncommitted and unreported.
- Never run destructive git commands without explicit instruction.
- A "done" report without the actual command output attached is not
  acceptable - Karo/Metsuke should treat a bare completion claim as
  unverified until the real pytest output is produced.
