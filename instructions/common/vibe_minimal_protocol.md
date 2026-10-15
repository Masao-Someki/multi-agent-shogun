# Task protocol

Plain mechanics only - no persona, no role-play. Follow these when relevant;
ignore whatever doesn't apply to how you were started.

## If you see a short message like "inbox3" while idle

It means: check your own inbox file for new instructions.

1. Find your own id: `tmux display-message -t "$TMUX_PANE" -p '#{@agent_id}'`
   (prints something like `ashigaru2`)
2. Read `queue/inbox/<your_id>.yaml`. Look at entries with `read: false`,
   newest first.
3. Read `queue/tasks/<your_id>.yaml` for the actual task - the inbox entry
   is just a notification that it changed.
4. If the task's `status` is `assigned`, do it. If `done`/`idle`/
   `cancelled`, there is nothing to do - wait.

## When your assigned task is complete

1. Write `queue/reports/<your_id>_report.yaml`: what you did, the exact
   commands you ran, and their real output (not a summary).
2. Tell QC:
   ```bash
   qc_target=$(bash scripts/qc_target.sh)
   bash scripts/inbox_write.sh "$qc_target" "<your_id>: <task> done" report_received <your_id>
   ```
3. Tell Karo:
   ```bash
   bash scripts/inbox_write.sh karo "<your_id>: <task> done" report_received <your_id>
   ```

## Boundaries

- Only read/write your own `queue/tasks/<your_id>.yaml` and
  `queue/reports/<your_id>_report.yaml` - never another agent's.
- Do not run `git commit`, `git push`, or any history-discarding command
  (`git reset --hard`, `git checkout -- <path>`, `git clean -f`) unless
  explicitly told to for that exact command. Leave finished work in your
  worktree; QC commits it after review.
- If you were given a task directly (e.g. as your starting prompt), that
  task's own instructions take priority over this file - just follow it,
  including whatever it says about how to report completion or deliver
  a patch.
