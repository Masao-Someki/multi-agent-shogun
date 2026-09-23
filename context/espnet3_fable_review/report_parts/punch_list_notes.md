How to read this list: items are grouped by severity and, within a group, ordered by reviewer confidence. Each line carries the finding id (details in section 3), and a badge: _verified_ (independently re-checked in Phase 2), _reproduced by reviewer_ (the original reviewer ran code that showed the failure), or _unverified_ (code reading only). Every item, including low severity, is also in `review_log/BACKLOG.md` as a checklist.

Suggested triage order, because many items share a root cause (see section 2b):

1. Stop stages from mutating the shared config and derive one resolved experiment context (theme A). This alone closes the critical normalize bug, the standalone `measure`/`pack_demo` crashes, and the config-dump inconsistencies.
2. Add a runtime rank/world-size context and a rank guard in `run_stages`; stop inferring distributed mode from `num_device` (theme C).
3. Introduce one artifact helper (atomic write, fingerprinted `.done` marker, lock with guaranteed release) and use it in every stage and recipe builder (theme D). This closes the stale-resume, lock-leak and truncated-download items together.
4. Fix the two Lightning callback-order dependencies (checkpoint averaging, EMA-vs-checkpoint) and make default callbacks opt-out (theme G).
5. Decide the dataset item contract (stable uid, single return shape) and the preprocessor `train=` contract before the first release (theme E); these are the only items that touch recipe authors.
6. Then work through the remaining medium items file by file; most are local fixes once 1-5 are in place.
