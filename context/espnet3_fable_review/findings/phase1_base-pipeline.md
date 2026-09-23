# Phase1 / base-pipeline (System base class, Task, stage runner, run_utils)

Files read in full: espnet3/systems/base/system.py, espnet3/systems/base/training.py,
espnet3/utils/stages_utils.py, espnet3/utils/run_utils.py, egs3/TEMPLATE/asr/run.py,
egs3/mini_an4/asr/run.py, egs3/librispeech_100/asr/run.py (+ callees: logging_utils,
config_utils, asr/tts system.py, trainer.py, task_utils.py, publication_utils (parts),
demo/packing.py (parts), metric.py (parts), recipe conf/*.yaml, tests).

Verified by execution (scripts in SCRATCH, PYTHONPATH=REPO):
1. training.collect_stats pops model.normalize/normalize_conf from the SHARED training_config;
   a following train() in the same process builds UtteranceMVN instead of configured global_mvn.
2. librispeech README step 3 (measure with --training_config + --metrics_config, no
   --inference_config) -> ConfigAttributeError: Missing key inference_dir.
3. TEMPLATE/mini_an4/librispeech demo.yaml "Quick usage" (--demo_config only) ->
   InterpolationKeyError 'exp_tag'. Standalone publication resolves exp_tag="publication".
4. set_stage_log_handler(None) (rank!=0 in rank0 mode) leaves previous stage handler attached.
5. run_stages wraps ANY TypeError as "does not accept CLI arguments".
6. pack_demo/upload_demo stage logs and --write_requirements pip-freeze land inside the demo
   bundle dir that upload_demo ships (requirements.txt overwritten).
7. config_utils import-time logging.info() installs basicConfig handler; configure_logging()
   then skips its formatted StreamHandler (console loses LOG_FORMAT).
8. _has_exp_identity docstring example raises InterpolationKeyError; --dry_run still mkdirs exp_dir;
   resolve_stages(['bogus'], ...) == [] silently; create_dataset forwards
   {'func':..., 'dataset_dir':..., 'recipe_dir':...} to builders (func never used).

Not verified (needs multi-GPU): DDP subprocess launcher / srun re-executes run.py on every rank ->
all requested stages (pre- and post-train) run once per rank; run_stages has no rank guard.
