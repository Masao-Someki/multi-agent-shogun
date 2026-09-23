# ESPnet3 Fable Review Context

This is the durable, actionable output of the ESPnet3 review run with Claude
Fable 5.1. The review examined `espnet3/`, `egs3/`, and `test/espnet3/` at
commit `ec5632b167`.

Use it as historical review evidence. It is not a claim that a finding remains
open on the current branch: verify the cited code and tests before proposing or
implementing a fix.

## Start here

- `report_parts/executive_summary.md` gives the scope, verified finding counts,
  and cross-cutting risks.
- `findings/<area>.json` is the smallest useful source for a focused technical
  question. Matching Markdown notes are included where available.
- `BACKLOG.md` is the complete human-readable checklist for broad triage.
- `verify/verdicts.json` records the independent verification outcome for the
  critical, high, and medium findings.
- `all_findings.json` supports structured searches across review areas.

## How roles should use it

- **Ashigaru:** follow the ESPnet rules in
  `context/espnet_agent_rules/.agent/`; read this review only when the assigned
  task explicitly provides a relevant finding.
- **Karo:** consult the summary and relevant findings while planning ESPnet3
  work, then assign a current-code check before scheduling a fix.
- **Gunshi:** use the relevant findings as input to ESPnet3 design, regression,
  and review analysis, and distinguish verified historical evidence from the
  status of the current branch.

`STATE.md`, the captured test output, and the recheck report are retained for
provenance. Review orchestration scripts, raw agent transcripts, and generated
translations are intentionally excluded because they are not needed for task
context.
