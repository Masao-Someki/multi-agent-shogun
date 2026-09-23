# Phase 1 / tts-system — TTSSystem, remove_long_short provider/runner, TEMPLATE/tts configs

Files read in full: espnet3/systems/tts/system.py, remove_long_short_provider.py, remove_long_short_runner.py,
egs3/TEMPLATE/tts/conf/{training,inference,metrics}.yaml, espnet3/systems/asr/system.py, espnet3/systems/base/system.py.
Supporting: espnet3/parallel/base_runner.py, env_provider.py, parallel.py, espnet3/systems/base/training.py,
espnet3/utils/stages_utils.py, task_utils.py, config_utils.py (parts), components/data/collect_stats.py (parts),
egs3/TEMPLATE/asr/run.py + conf/*, test/espnet3/systems/tts/*.py, espnet2 references (tts.sh, tokenize_text.py,
tasks/tts.py, layers/global_mvn.py, text/char_tokenizer.py).

Repro scripts (SCRATCH/tts): repro_stage.py, repro_normalize.py (+ stub_pkg.py: pkg_resources stub needed because
pyworld import fails in this env; espnet2.tasks.tts cannot be imported here without it).

## Findings (severity, verified?)
1. HIGH  system.py:496-498  TTS collect_stats keeps model.normalize as-is -> canonical TTS configs (normalize: global_mvn,
   normalize_conf.stats_file under stats_dir) crash FileNotFoundError on first run; base pop -> TypeError; espnet2 tts.sh
   forces --normalize none / --pitch_normalize none / --energy_normalize none. Verified (task-level with stub).
2. HIGH  base/training.py:62-65  base collect_stats pops normalize/normalize_conf IN PLACE on the shared training_config;
   `--stages collect_stats train` in one invocation then trains with the task default normalizer (ASR: utterance_mvn)
   even when global_mvn was configured; saved config.yaml records the default. Verified.
3. MED   system.py:363-367  create_token_list default path: blank line or <3-column row -> IndexError (vocab_builder
   branch and _load_entries both guard this). Verified.
4. MED   system.py:41-58  TTSSystem.__init__(**kwargs) + hard-coded stage_log_mapping -> TypeError "multiple values for
   keyword argument 'stage_log_mapping'"; ASRSystem merges. Verified.
5. MED   system.py:174-180 (+ base_runner.py:347-351)  resume=False never clears stale shard dirs; a hard-killed run
   (SIGKILL/OOM/Dask worker death) leaves split.N/lock and every re-run raises "Shard is already locked by another
   runner" with no recovery hint. Verified (simulated lock).
6. MED   system.py:145-149,201-202,284-286  filtered manifests are consumed by nothing; create_token_list defaults to the
   UNFILTERED data/manifest/train.tsv; dataset must be re-pointed manually or training silently uses unfiltered data.
7. MED   system.py:128-134,332-347  OmegaConf .get(key, default) returns None for explicit `null` -> TEMPLATE-style null
   placeholders (splits:, token_type:, add_symbol:, cutoff:) crash with TypeError/TypeCheckError. Verified.
8. LOW   system.py:115-120  no min<max validation; min>=max silently writes empty filtered manifests. Verified.
9. LOW   system.py:149  output name = manifest basename -> manifest_paths sharing a basename silently overwrite. Verified.
10. LOW  runner.py:62-63  one missing/unreadable wav aborts the whole split with a soundfile error lacking utt_id. Verified.
11. LOW  system.py:65-66,174-180  "in parallel" docstring: with parallel.env=local BaseRunner plans 1 shard and runs
    sequentially regardless of n_workers; non-local env spins up a new Dask cluster per split.
12. LOW  TEMPLATE/tts/conf/training.yaml:29  stats_dir=${exp_dir}/stats vs ASR ${recipe_dir}/exp/stats (inconsistent).
13. LOW  system.py:350-359,388-401  add_nonsplit_symbol duplicates the symbol in tokens.txt when it occurs in text;
    TokenIDConverter rejects it at train time (inherited from espnet2). Verified.
14. LOW  TEMPLATE/tts lacks remove_long_short / create_token_list sections and any run.py; the TTS-specific stages are in
    no stage list and their stage log dirs silently fall back to exp_dir.
15. TEST-GAP  test_system.py:254-309  collect_stats tests mock _build_trainer and assert only that normalize "survives",
    i.e. they pin the behaviour that crashes for global_mvn configs; no Dask-mode, zero-length/missing wav, stale-lock,
    or end-to-end (run_stages + config merge) coverage; no TTS recipe in egs3.
