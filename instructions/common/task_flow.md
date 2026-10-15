# Ticket Flow

## Workflow: Head Chef → Sous-chef → Cook / Quality Inspector / Menu Planner

```
Head Chef: direct command → Sous-chef: record ticket YAML, decompose → inbox_write → Cook: execute → report YAML → Quality Inspector (Menu Planner escalation) → Sous-chef: update dashboard and reply to Head Chef
```

Default formation: Sous-chef, Cooks 1–3, Quality Inspector, Research Cook, Menu Planner (seven panes).
Sous-chef consults Menu Planner when strategic judgment is needed; Research Cook remains Menu Planner's bounded research assistant. Existing Cook/Menu Planner communication remains available.
`queue/shogun_to_karo.yaml` and its archive retain their legacy names, but Sous-chef now writes human requests there with the required cmd fields before dispatch.
An explicit legacy profile may still enable Owner; it is not a default dependency.

## Status Reference (Single Source)

Status is defined per YAML file type. **Keep it minimal. Simple is best.**

Fixed status set (do not add casually):
- `queue/shogun_to_karo.yaml`: `pending`, `in_progress`, `done`, `cancelled`
- `queue/tasks/ashigaruN.yaml`: `assigned`, `blocked`, `done`, `failed`
- `queue/tasks/ashigaruN.yaml` field `plan_status`: `pending`, `submitted`, `approved`, `revised`, `escalated`, `waived`
- `queue/tasks/pending.yaml`: `pending_blocked`
- `queue/ntfy_inbox.yaml`: `pending`, `processed`

Do NOT invent new status values without updating this section.

### Command Queue: `queue/shogun_to_karo.yaml`

### Optional plan gate: `plan_status` in `queue/tasks/ashigaruN.yaml`

The seven-role default has no Shift Lead and does not use the plan gate. Set
`plan_gate: true` only when an explicitly selected profile enables Shift Lead.

- `approved` / `revised`: Shift Lead accepted the plan, or fixed it; the Cook runs it step by step (using `task_start.sh <N>`)
- `waived`: no gate is active for this ticket/profile


Meanings and allowed/forbidden actions (short):

- `pending`: not acknowledged yet
  - Allowed: Sous-chef reads and immediately ACKs (`pending → in_progress`)
  - Forbidden: dispatching subtasks while still `pending`

- `in_progress`: acknowledged and being worked
  - Allowed: decompose/dispatch/collect/consolidate
  - Forbidden: moving goalposts (editing acceptance_criteria), or marking `done` without meeting all criteria

- `done`: complete and validated
  - Allowed: read-only (history)
  - Forbidden: editing old cmd to "reopen" (use a new cmd instead)

- `cancelled`: intentionally stopped
  - Allowed: read-only (history)
  - Forbidden: continuing work under this cmd (use a new cmd instead)

### Ticket pool: `queue/task_pool/<ticket_id>.yaml`
- Statuses: `open`, `claimed`, `done`, `failed`
- Managed only by `task_pool_add.sh`, `task_pool_claim.sh` and `task_pool_mark.sh` (never by hand)
- Sous-chef adds drafts from `queue/task_pool/drafts/`; an idle Cook claims the oldest open ticket whose `depends_on` are done and whose `files` do not overlap a claimed ticket

### Archive Rule

The active queue file (`queue/shogun_to_karo.yaml`) must only contain
`pending` and `in_progress` entries. All other statuses are archived.

When a cmd reaches a terminal status (`done`, `cancelled`, `paused`),
Sous-chef must move the entire YAML entry to `queue/shogun_to_karo_archive.yaml`.

| Status | In active file? | Action |
|--------|----------------|--------|
| pending | YES | Keep |
| in_progress | YES | Keep |
| done | NO | Move to archive |
| cancelled | NO | Move to archive |
| paused | NO | Move to archive (restore to active when resumed) |

**Canonical statuses (exhaustive list — do NOT invent others)**:
- `pending` — not started
- `in_progress` — acknowledged, being worked
- `done` — complete (covers former "completed", "superseded", "active")
- `cancelled` — intentionally stopped, will not resume
- `paused` — stopped by Head Chef's decision, may resume later

Any other status value (e.g., `completed`, `active`, `superseded`) is
forbidden. If found during archive, normalize to the canonical set above.

**Sous-chef rule (ack fast)**:
- The moment Sous-chef starts processing a cmd (after reading it), update that cmd status:
  - `pending` → `in_progress`
  - This prevents "nobody is working" confusion and stabilizes escalation logic.

### Cook Ticket File: `queue/tasks/ashigaruN.yaml`

Meanings and allowed/forbidden actions (short):

- `assigned`: start now
  - Allowed: assignee cook executes and updates to `done/failed` + report + inbox_write
  - Forbidden: other agents editing that cook YAML

- `blocked`: do NOT start yet (prereqs missing)
  - Allowed: Sous-chef unblocks by changing to `assigned` when ready, then inbox_write
  - Forbidden: nudging or starting work while `blocked`

- `done`: completed
  - Allowed: read-only; used for consolidation
  - Forbidden: reusing ticket_id for redo (use redo protocol)

- `failed`: failed with reason
  - Allowed: report must include reason + unblock suggestion
  - Forbidden: silent failure

Note:
- Normally, "idle" is a UI state (no active ticket), not a YAML status value.
- Exception (placeholder only): `status: idle` is allowed **only** when `ticket_id: null` (clean start template written by `shutsujin_departure.sh --clean`).
  - In that state, the file is a placeholder and should be treated as "no ticket assigned yet".

### Pending Tickets (Sous-chef-managed): `queue/tasks/pending.yaml`

- `pending_blocked`: holding area; **must not** be assigned yet
  - Allowed: Sous-chef moves it to a `ashigaruN.yaml` as `assigned` after prerequisites complete
  - Forbidden: pre-assigning to cook before ready

### NTFY Inbox (Head Chef phone): `queue/ntfy_inbox.yaml`

- `pending`: needs processing
  - Allowed: Sous-chef processes and sets `processed` (Owner only in an explicit legacy formation)
  - Forbidden: leaving it pending without reason

- `processed`: processed; keep record
  - Allowed: read-only
  - Forbidden: flipping back to pending without creating a new entry

## Immediate Delegation Principle (Sous-chef)

**Record and dispatch promptly, then end your turn** so the Head Chef can input the next command.

```
Head Chef: command → Sous-chef: write cmd/ticket YAML → inbox_write → END TURN
                                        ↓
                                  Head Chef: can input next
                                        ↓
                              Cook/Quality Inspector/Menu Planner: work in background
                                        ↓
                              dashboard.md updated as report
```

## Event-Driven Wait Pattern (Sous-chef)

**After dispatching all subtasks: STOP.** Do not launch background monitors or sleep loops.

```
Step 7: Dispatch cmd_N subtasks → inbox_write to cook
Step 8: check_pending → if pending cmd_N+1, process it → then STOP
  → Sous-chef becomes idle (prompt waiting)
Step 9: Cook completes → inbox_write sous-chef → watcher nudges sous-chef
  → Sous-chef wakes, scans reports, acts
```

**Why no background monitor**: inbox_watcher.sh detects cook's inbox_write to sous-chef and sends a nudge. This is true event-driven. No sleep, no polling, no CPU waste.

**Sous-chef wakes via**: direct human input, QC/strategy inbox reports, ntfy input, or system events. No polling.

## "Wake = Full Scan" Pattern

Claude Code cannot "wait". Prompt-wait = stopped.

1. Dispatch cook
2. Say "stopping here" and end processing
3. Cook wakes you via inbox
4. Scan ALL report files (not just the reporting one)
5. Assess situation, then act

## Report Scanning (Communication Loss Safety)

On every wakeup (regardless of reason), scan ALL `queue/reports/ashigaru*_report.yaml`.
Cross-reference with dashboard.md — process any reports not yet reflected.

**Why**: Cook inbox messages may be delayed. Report files are already written and scannable as a safety net.

## Foreground Block Prevention (24-min Freeze Lesson)

**Sous-chef blocking = entire kitchen halts.** On 2026-02-06, foreground `sleep` during delivery checks froze sous-chef for 24 minutes.

**Rule: NEVER use `sleep` in foreground.** After dispatching tickets → stop and wait for inbox wakeup.

| Command Type | Execution Method | Reason |
|-------------|-----------------|--------|
| Read / Write / Edit | Foreground | Completes instantly |
| inbox_write.sh | Foreground | Completes instantly |
| `sleep N` | **FORBIDDEN** | Use inbox event-driven instead |
| tmux capture-pane | **FORBIDDEN** | Read report YAML instead |

### Dispatch-then-Stop Pattern

```
✅ Correct (event-driven):
  cmd_008 dispatch → inbox_write cook → stop (await inbox wakeup)
  → cook completes → inbox_write sous-chef → sous-chef wakes → process report

❌ Wrong (polling):
  cmd_008 dispatch → sleep 30 → capture-pane → check status → sleep 30 ...
```

## Timestamps

**Always use `date` command.** Never guess.
```bash
date "+%Y-%m-%d %H:%M"       # For dashboard.md
date "+%Y-%m-%dT%H:%M:%S"    # For YAML (ISO 8601)
```

## Pre-Commit Gate (CI-Aligned)

Rule:
- Run the same checks as GitHub Actions *before* committing.
- Only commit when checks are OK.
- Ask the Head Chef before any `git push`.

Minimum local checks:
```bash
# Unit tests (same as CI)
bats tests/*.bats tests/unit/*.bats

# Instruction generation must be in sync (same as CI "Build Instructions Check")
bash scripts/build_instructions.sh
git diff --exit-code instructions/generated/
```
