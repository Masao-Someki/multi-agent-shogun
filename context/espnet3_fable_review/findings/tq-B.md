# tq-B notes (test/espnet3/systems/**, parallel/**, publication/**, demo/**)

## Confirmed via source + execution
- espnet3/parallel/base_runner.py:283-291 `_plan_shards`: when `parallel.env == "local"`, `num_shards` is hardcoded to 1 regardless of `n_workers`. Only non-"local" envs use `n_workers` to split into shards. Verified live: env=local,n_workers=2 -> 1 shard; env=local_gpu,n_workers=2 -> 2 shards.
- This makes test/espnet3/parallel/test_inference_runner.py::test_parallel_shards_offline_with_base_runner and ::test_parallel_shards_streaming_with_base_runner (set env="local", n_workers=2/3) vacuous for parallel dispatch: they always run through `_run_local`'s single-shard sequential path, and assert only `len(shard_dirs) >= 1`, which a single shard trivially satisfies. The real multi-shard/Dask dispatch path (`_run_parallel_dask`) is never exercised anywhere in test/espnet3/parallel/** or test/espnet3/systems/**.
- Also a design/robustness smell: n_workers is silently ignored under env=local with no warning -- a recipe author setting n_workers>1 with env=local gets no parallelism and no diagnostic.

## Checked and OK (not hollow, contrary to initial lead)
- test/espnet3/systems/tts/test_system.py:283-309 (test_collect_stats_delegates_to_trainer / test_collect_stats_preserves_null_normalize): only mocks `_build_trainer` (heavy Lightning trainer construction, legitimate external dep) and `_ensure_directories`. TTSSystem.collect_stats itself (espnet3/systems/tts/system.py:435-458) contains NO normalize-popping logic (unlike base collect_stats in training.py:62-65), so the assertion is a real regression guard: if someone "simplifies" TTSSystem.collect_stats back to call the base implementation, this test will fail. Mutation-verified: reintroducing the pop logic into TTSSystem.collect_stats made test_collect_stats_preserves_null_normalize fail (see mut_result.txt).

## Duplicate test
- test/espnet3/systems/base/test_inference_utils.py::test_materialize_output_value_rejects_top_level_lists duplicates test/espnet3/systems/base/test_inference.py::test_materialize_output_value_rejects_top_level_list almost verbatim (same SUT call, same assertion). Low-severity duplication.

## Coverage gap
- espnet3/parallel/base_runner.py `BaseRunner._run_parallel_dask` (the Dask-backed distributed shard dispatch, including its exception/`client.cancel(futures)` cleanup path) has zero references anywhere in test/espnet3/**. All parallel/systems tests that exercise BaseRunner/InferenceRunner either omit `parallel` config (defaults to local) or set env="local" explicitly, so the actual multi-worker/distributed code path is completely untested.

## Files read, all judged meaningful (real SUT executed, real assertions), no further findings:
- test/espnet3/systems/asr/metrics/test_metrics.py
- test/espnet3/systems/asr/test_asr_inference.py
- test/espnet3/systems/asr/test_asr_transducer.py
- test/espnet3/systems/asr/test_system.py
- test/espnet3/systems/asr/test_task.py
- test/espnet3/systems/asr/tokenizer/test_sentencepiece.py
- test/espnet3/systems/base/test_base_system.py
- test/espnet3/systems/base/test_inference.py
- test/espnet3/systems/base/test_inference_runner.py
- test/espnet3/systems/base/test_metric.py
- test/espnet3/systems/base/test_training.py
- test/espnet3/systems/tts/test_remove_long_short.py
- test/espnet3/systems/tts/test_system.py
- test/espnet3/parallel/test_base_runner_batch.py
- test/espnet3/parallel/test_inference_provider.py
- test/espnet3/parallel/test_inference_runner.py
- test/espnet3/parallel/test_parallel.py
- test/espnet3/publication/test_inference_model.py
- test/espnet3/demo/test_app_builder.py
- test/espnet3/demo/test_pack.py
