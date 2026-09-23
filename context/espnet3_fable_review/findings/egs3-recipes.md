# egs3-recipes incremental notes

## egs3/TEMPLATE/asr/conf/training.yaml (lines 46-53) vs espnet3/systems/base/system.py (lines 226-278)
`create_dataset:` block documents `func: src.creating_dataset.create_dataset` and comment says
"The function is resolved from `create_dataset.func` and called with the remaining fields in this
block as keyword arguments." This is FALSE for the actual stage: `BaseSystem.create_dataset()`
(espnet3/systems/base/system.py:226-278) never reads `create_dataset.func`. It instead does
`default_builder_kwargs = dict(create_dataset_config)` and, for each dataset entry, loads the
recipe's `dataset/__init__.py` module, instantiates `module.DatasetBuilder()`, and calls
`is_source_prepared/prepare_source/is_built/build(**builder_kwargs)`. `func` and `dataset_dir` end
up silently forwarded as unused extra kwargs (absorbed by `**_kwargs` in builder methods per the
DatasetBuilder ABC contract) -- no crash, but the documented mechanism (a user-defined
`create_dataset.func` hook) simply does not exist anywhere in the codebase (grepped
espnet3/systems, no reader of `create_dataset.func`). Neither mini_an4 nor librispeech_100 ship a
`src/creating_dataset.py`, consistent with the hook being dead. Severity: medium-high docs-mismatch
-- this is the DATASET CREATION SETTING section of the canonical TEMPLATE, so any new recipe author
following it will write a `src/creating_dataset.py:create_dataset()` function that is never called.
Confidence 0.9. VERIFIED by execution: loading mini_an4's real `conf/training.yaml` through
`load_and_merge_config(..., default_package="egs3.TEMPLATE.asr")` from SCRATCH produces
`cfg.create_dataset == {'func': 'src.creating_dataset.create_dataset', 'dataset_dir':
'/path/to/your/dataset', 'recipe_dir': '.'}` -- i.e. the real recipe's merged config silently
carries the TEMPLATE placeholder `dataset_dir: /path/to/your/dataset` and a `func` pointing at a
module (`src.creating_dataset`) that does not exist in mini_an4/asr/src/ (confirmed via `ls`), and
`BaseSystem.create_dataset()` passes both straight through as unused `**builder_kwargs`.

## egs3/mini_an4/asr/dataset/builder.py `prepare_source()`/`is_source_prepared()` -- non-atomic download, existence-only re-check (lines 92-134, 64-90)
Refined from the note above: the strongest concrete failure needs no distributed/concurrency
assumption at all. `prepare_source()` (lines 117-125) calls
`urllib.request.urlretrieve(url, str(archive))` writing directly to the final `archive_path`
(`downloads.tar.gz`) with no temp-file+atomic-rename and no completeness marker (no checksum, no
`.done` sentinel). If this single-process download is interrupted (Ctrl-C, OOM-kill, node
preemption, network drop -- routine on shared clusters) partway through, `archive.exists()` is
still `True` afterward (a truncated file is on disk). On the next `create_dataset` invocation,
`prepare_source()` (line 120: `if not archive.exists(): ...`) sees the archive "already there" and
skips re-downloading, then unconditionally runs `tar -xzf` on the truncated `downloads.tar.gz`
(line 130-133). Two outcomes are both bad: (a) `tar` raises `CalledProcessError` and the recipe is
stuck needing manual deletion of the corrupt archive (no error message hints at this -- user sees a
generic tar traceback), or (b) `tar` partially extracts before failing and leaves partial
`downloads/an4/{etc,wav}` directories; `is_source_prepared()` (lines 64-90) only checks
`(an4/etc).is_dir() and (an4/wav).is_dir()`, so if both directories exist with *any* content, later
`build()` calls treat the source as ready even though files referenced by the transcripts may be
missing -- `build()` (lines 213-224) would then raise `FileNotFoundError`-style failure per-missing
sph file deep into manifest building, or (with sph2pipe silently producing a 0-byte file for a
missing input, per the already-known zero-byte-wav bug) silently write bad manifest rows. Distinct
from the two already-known builder bugs (`is_built` existence-only + non-atomic manifest write DDP
race; zero-byte wav from interrupted sph2pipe) because this is about the *source archive
acquisition* step, is reachable from a single interrupted run (no concurrency needed), and
`is_source_prepared` never re-validates completeness once the etc/wav dirs exist at all. Severity
high (silent, hard-to-diagnose corruption reachable via a routine interrupted download on shared/
preemptible compute); confidence 0.7, not executed (would require actually killing a download
mid-flight to observe, deemed unnecessary/wasteful for SCRATCH). The multi-process concurrent-
download variant (two ranks/jobs racing on the same `urlretrieve` target) is a secondary, lower-
confidence (0.4) manifestation of the same missing-atomicity root cause -- `run_stages`
(espnet3/utils/stages_utils.py) does not rank-guard the `create_dataset` stage (its rank-awareness
only branches file *logging*, not stage execution), so nothing in the reviewed files prevents this.

## egs3/TEMPLATE/asr/conf/publication.yaml exp_dir convention (line 27) vs training.yaml/inference.yaml (line 28/23)
`publication.yaml: exp_dir: exp/${exp_tag}` (no `${recipe_dir}` prefix), while
`training.yaml`/`inference.yaml` both use `exp_dir: ${recipe_dir}/exp/${exp_tag}`. In the common
flow `apply_training_experiment_context` overwrites `publication_config.exp_dir` from
`training_config.exp_dir` so this rarely bites, but for standalone `pack_model`/`upload_model`
(publication_config only, no training_config) with a non-default `recipe_dir`, publication's
`exp_dir` silently resolves relative to CWD instead of `recipe_dir`. Low-medium severity, design
inconsistency / footgun. Not yet fully traced into run_utils.py (out of area) so confidence 0.5.

## egs3/mini_an4/asr/dataset/builder.py prepare_source() download race (lines 92-134)
`prepare_source()` checks `archive.exists()`; if missing, calls
`urllib.request.urlretrieve(url, str(archive))` directly to the final archive path (no temp file +
atomic rename, no lock). The base `DatasetBuilder` ABC docs (espnet3/components/data/dataset_builder.py)
and `BaseSystem.create_dataset()` caller pattern (`if not is_source_prepared: prepare_source()`) show
no synchronization is done by the caller either. Concrete failure: two ranks/processes in a
multi-worker `create_dataset` invocation (or a user re-running `run.py --stages create_dataset` while
a previous run is mid-download) both see `archive.exists() == False`, both call `urlretrieve` to the
same path concurrently -> interleaved writes corrupt `downloads.tar.gz`, and the subsequent
`tar -xzf` either raises `CalledProcessError` for one/both processes or (worse) extracts truncated
data that `is_source_prepared()` then reports as `True` (etc/wav dirs exist) even though the archive
was corrupt, silently poisoning the recipe's data for all future runs until someone notices missing
utterances. This is a different race than the already-known `is_built`-existence-only / non-atomic
manifest-write DDP race (which is about `build()`, not `prepare_source()`'s download step). Severity
high (silent data corruption, matches "critical" bar for corrupted training data but only reachable
via concurrent create_dataset runs -- keeping at high pending confirmation that no external lock
wraps this call). Confidence 0.55 (plausible misuse path, not fully traced to whether the `create_dataset`
CLI stage/DataOrganizer serializes calls e.g. via rank-0-only or filelock upstream -- that logic
lives outside the assigned files).

## egs3/mini_an4/asr/src/app.py, egs3/TEMPLATE/asr/src/app.py -- verbatim duplication
`build_demo()`/`main()` in both files are byte-for-byte identical (~110 lines each), and
`librispeech_100/asr/src/app.py` is the same size (3797 bytes) suggesting the same duplication.
This boilerplate Gradio launcher does not need to be recipe-local; it should live once in
`espnet3/publication/demo/` and be imported, not copy-pasted into every recipe's `src/app.py`
(`ui.app_script: src/app.py` in demo.yaml is what gets packed, so some recipe-local file is needed,
but it need not duplicate the whole `build_demo`/`main` implementation -- a one-line wrapper
importing a shared helper would do). Low severity maintainability/design finding: any future change
to Gradio wiring (e.g. output component type handling) must be replicated in 3+ places, and already
one recipe (nothing observed yet, but the risk is real given 3 independent copies).

## egs3/TEMPLATE/asr/readme.md 'Quick start' step 1 (line 13-14) -- generic template says "Convert LibriSpeech to Hugging Face format"
TEMPLATE/asr is the *generic* runner template (per repo docs: "TEMPLATE/asr = canonical runner +
configs"), yet its readme's first Quick-start comment is LibriSpeech-specific ("Convert LibriSpeech
to Hugging Face format (run once)") and the command matches neither what a generic recipe's
`create_dataset` stage actually does (see finding above: `create_dataset.func` hook is dead) nor
what mini_an4 does (mini_an4 builds AN4 manifests, not "Hugging Face format" anything). This reads
as leftover copy-paste from librispeech_100/asr/readme.md that was never generalized when TEMPLATE
was authored generically elsewhere. Low-medium severity docs-mismatch; will confirm against
librispeech_100/asr/readme.md text next.
