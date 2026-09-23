# espnet3 review -- state and resume runbook

Goal: the review described in `submit_fable_review.sh` (exhaustive read-only design/correctness review of
`espnet3/` + `egs3/`, plus a test-quality audit of `test/espnet3/`), written to `espnet3_fable_review.md`
(progress log while running; final `## Report` section at the end).

## Resume in one line
Tell Claude: "review_log/STATE.md を読んで続きをやって". Then Claude runs
`python3 review_log/tools/status.py`, which prints done/pending areas and writes the exact Workflow
arguments to `review_log/tools/phase1b_resume_args.json`.

## Layout
- `espnet3_fable_review.md` -- the deliverable. `## Progress Log` gets one line per finished agent.
- `review_log/findings/<area>.json` -- structured findings per area (existence == area done).
- `review_log/findings/*.md` -- reviewers' incremental notes (used to reconstruct JSON if an agent is cut off).
- `review_log/tools/COMMON_INSTRUCTIONS.md`, `TQ_INSTRUCTIONS.md`, `SALVAGE_INSTRUCTIONS.md` -- agent instructions.
- `review_log/tools/phase1b_plan.json` -- the area plan (batches, model per area, files, focus).
- `review_log/tools/phase1b.js` -- Workflow script (sequential batches; stops early when a whole batch fails = session limit).
- `review_log/tools/status.py` -- progress + resume args.
- `review_log/tools/extract_transcript.py` -- pulls narration/commands out of a subagent transcript.
- `review_log/pytest_espnet3.txt` -- full-suite result (697 passed, 2 failed [pkg_resources env issue], 7 skipped).
- `review_log/salvage/*.txt` -- transcript extracts of cut-off agents.

## Phases
1. **Phase 1 (finders)** -- 5 areas done (metrics, tts-system as JSON; base-pipeline, base-inference,
   data-organizer as notes awaiting salvage). Phase 1b covers the remaining 13 areas in 6 sequential batches
   (see plan). Usage-limit pacing: 2 agents at a time; Fable only for data-loading, lightning-module,
   trainer-callbacks, asr-system, config-hydra; Sonnet for the rest.
2. **Phase 2 (light verification)** -- only critical/high findings, Sonnet verifiers, batches of ~8,
   one lens ("try to refute; cite the guard"). Medium/low pass through marked unverified.
   Steps: `python3 review_log/tools/collect.py` (merges findings -> `review_log/all_findings.json`, writes
   `review_log/tools/phase2_args.json`), then Workflow `{scriptPath: review_log/tools/phase2.js, args: <phase2_args.json>}`,
   then `python3 review_log/tools/collect.py --merge-verdicts` (-> `review_log/verify/verdicts.json`).
3. **Phase 3 (synthesis)** -- write `review_log/report_parts/executive_summary.md` (and optionally
   `punch_list_notes.md`) by hand after reading `all_findings.json`, then `python3 review_log/tools/build_report.py`
   replaces everything from `## Report` onwards in `espnet3_fable_review.md` (per-area findings, test-quality
   section, punch list, coverage/assumptions appendix, dropped/duplicate findings). `--dry-run` previews.

## History
- 2026-09-01 20:44 first run (25 finders, 6 concurrent): 2 finished, 3 finished analysis but were cut off before
  reporting, rest died at the session limit after ~18 min.
- 2026-09-02 10:10 second run (10 agents at once via Agent tool): all died at the session limit within minutes.
- 2026-09-03 11:46 re-planned to sequential batches + Sonnet for non-core areas (this file created).
- 2026-09-03 ~11:55 Phase 1b launched as Workflow run `wf_ee147586-9be` (same-session resume only; across
  sessions use `status.py` + a fresh Workflow call with `phase1b_resume_args.json`).
- 2026-09-03 12:20 usage check: 23% of the 5-hour window gone after the 3 salvage agents. Plan edited so that on the
  NEXT resume only lightning-module and trainer-callbacks stay on Fable; asr-system and config-hydra switched to Sonnet.
  (The running workflow keeps its original args; the change applies when status.py regenerates the resume args.)
- 2026-09-03 12:25 per user request: `parallel` split out of `parallel-misc` and put on Fable (with the inference/TTS
  runner+provider files as context); `misc-utils` stays Sonnet. data-loading (sharding) was already Fable.
  New batch order after the running batches: [asr-system/S, publication/S] -> [parallel/F, misc-utils/S] -> [config-hydra/S].
- 2026-09-03 12:50 run 1 (wf_ee147586-9be) stopped after 3 batches; plan is now EMBEDDED in phase1b.js (status.py
  re-embeds it), so resume args are just keys: see the JSON printed by `python3 review_log/tools/status.py`.
  Run 2 launched with the 7 pending areas in 4 batches (parallel/Fable moved ahead of asr-system/publication).
- 2026-09-03 13:05 user decisions: Phase 2 verifies critical+high+MEDIUM (low is not verified). Every finding of
  every severity must be preserved: build_report.py now also writes `review_log/BACKLOG.md` (checklist, all
  severities, duplicates and refuted findings kept and marked) and the report's punch list includes low.
- 2026-09-03 13:35 Phase 1 complete (16/16 areas). Phase 2 findings are EMBEDDED in phase2.js (regenerate with
  collect.py + the embed snippet in STATE.md history, or just re-run collect.py and re-embed); launch with
  Workflow {scriptPath: review_log/tools/phase2.js, args: {}}. Batch outputs land in review_log/verify/batch_<i>.json;
  to resume after a cutoff pass args {"skip": [<completed batch indices>]}.
- 2026-09-03 13:40 Phase 2 launched: Workflow run `wf_8161a01a-9a6` (phase2.js, 118 findings embedded, 15 batches).
  After it finishes (or dies): `python3 review_log/tools/collect.py --merge-verdicts`, then check which
  review_log/verify/batch_<i>.json exist; relaunch phase2.js with args {"skip": [<existing indices>]} if incomplete.
- 2026-09-03 14:00 findings are pinned to commit ec5632b167. The user has a separate bugfix branch for the data layer
  (theme E) that may not be in this tree. After merging: `python3 review_log/tools/recheck_after_merge.py [rev]`
  lists findings whose cited lines changed (re-verify), whose file shifted (re-locate), and untouched ones.
- 2026-09-03 14:12 usage ~92%: stopped Phase 2 (run wf_8161a01a-9a6) after 8/15 batches (64 verdicts: 57 confirmed,
  6 corrected, 1 refuted). Generated a PARTIAL final report + BACKLOG so nothing is lost. To finish verification:
  Workflow {scriptPath: review_log/tools/phase2.js, args: {"skip":[0,1,2,3,4,5,6,7]}}, then collect.py --merge-verdicts,
  then build_report.py. Unverified candidate ids are in review_log/verify/remaining.json.
- 2026-09-03 18:55 Phase 2 COMPLETE (15/15 batches, 118/118 verified: 107 confirmed, 10 corrected, 1 refuted =
  config-hydra#01, the run.py `__package__` crash claim). Final report generated (`## Report` in
  espnet3_fable_review.md) and `review_log/BACKLOG.md` (206 findings). REVIEW DONE. Follow-ups: (a) after
  `git fetch upstream`, run `recheck_after_merge.py upstream/master`; (b) planned docs/docstring review on the
  docs branch (see memory). Note: a verifier's `run.py --dry_run` created an empty egs3/TEMPLATE/asr/exp in
  the repo (the dry-run side-effect finding base-pipeline#09 in action); removed.
- 2026-09-03 19:05 Japanese translation: `split_report.py` -> review_log/ja/chunk_NN.md (21 chunks), Workflow
  `translate.js` (Sonnet) writes chunk_NN.ja.md; concatenate with `cat review_log/ja/chunk_*.ja.md > espnet3_fable_review.ja.md`.
  Resume with args {"chunks": <manifest>, "skip": [done idx]}.
- 2026-09-03 20:15 Japanese translation done: `espnet3_fable_review.ja.md` (21 Sonnet chunks concatenated; structure
  verified against the English report). If the English report is regenerated, re-run split_report.py + translate.js
  (skip unchanged chunks) and re-concatenate.
