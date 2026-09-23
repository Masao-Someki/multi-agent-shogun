# Phase 1 / base-inference — infer stage end to end

Files read in full: espnet3/systems/base/inference.py (207), inference_provider.py (321),
inference_runner.py (437), egs3/TEMPLATE/asr/src/inference.py, egs3/mini_an4/asr/src/inference.py,
egs3/librispeech_100/asr/src/inference.py, egs3/TEMPLATE/asr/conf/inference.yaml,
egs3/mini_an4/asr/conf/inference.yaml, egs3/mini_an4/asr/conf/inference_transducer.yaml.
Supporting files read in full: espnet3/parallel/base_runner.py, parallel/env_provider.py,
parallel/parallel.py, parallel/inference_provider.py, utils/writer_utils.py, utils/run_utils.py,
egs3/TEMPLATE/asr/run.py, egs3/TEMPLATE/tts/conf/inference.yaml, egs3/librispeech_100/asr/conf/inference.yaml,
all inference tests (test/espnet3/systems/base/test_inference*.py, systems/asr/test_asr_inference.py,
parallel/test_inference_runner.py, parallel/test_inference_provider.py, parallel/test_base_runner_batch.py).
Skimmed: systems/base/system.py, utils/stages_utils.py, utils/config_utils.py (load_and_merge_config,
_ensure_target_convert_all), utils/publication_utils.py (_write_bundle_config), publication/inference_model.py,
components/data/data_organizer.py (test_sets), components/metrics/base_metric.py (scp reader),
espnet2/bin/asr_inference.py + asr_transducer_inference.py (__call__ return shapes), systems/base/training.py.

Verification scripts (all run from SCRATCH with PYTHONPATH=REPO): SCRATCH/v/v1_convert_all.py,
v2_lock_leak.py, v3_stale.py, v4_idx_key.py, v6_misc.py, v16_ddp_sim.py.

## Findings (see StructuredOutput for full detail)
H1  Multi-GPU `train`+`infer` in one run.py invocation: Lightning re-executes run.py in every DDP rank,
    no rank guard exists, all ranks run infer() against the same inference_dir -> lock collision crash
    (verified with 2 concurrent processes: rank0 died with "Shard is already locked").
H2  Resume silently reuses stale results after the model/beam config changes (manifest stores only indices;
    no log when all shards are skipped) - verified.
H3  Pre-locking all pending shards + no unlock on failure/cancel leaks lock files for shards that never ran;
    next run fails with "already locked by another runner" - verified with a 2-shard plan.
M1  `_convert_: all` (set by load_and_merge_config) hands the provider a plain dict; build_dataset's
    dict branch falls through into the DictConfig branch and instantiates DataOrganizer twice
    (3 constructions per test set in infer) - verified.
M2  InferenceRunner(idx_key=/hyp_key=/ref_key=) constructor args are dead: write_record reads them from env;
    output_keys missing from an output -> bare KeyError('ref') - verified.
M3  TEMPLATE build_output_transducer returns a tuple (return_decoded_hyp=True) or a Hypothesis object
    (default) -> TypeError or a pickle path silently written to hyp.scp - verified with fake outputs.
M4  build_model forces device=<resolved> into every model target, silently overriding model.device - verified.
M5  batch_size: 1 (suggested in TEMPLATE comment) breaks Speech2Text + build_output; error blames
    "batched inputs" and no utt/index context on any per-utterance failure - verified.
M6  parallel.env=local with n_workers>1 never parallelises (1 shard, driver only) - verified.
M7  Class docstring claims list-valued hyp/ref -> hyp0.scp/hyp1.scp; code raises TypeError.
M8  TEMPLATE-null blocks give misleading late errors: dataset.test null -> "'NoneType' object is not
    iterable"; model null -> "'NoneType' object is not callable" after dataset build - verified.
M9  TTS TEMPLATE `dataset:` null lacks _target_/_recursive_ -> recipe with only dataset.test fails with
    "ListConfig indices must be integers" - verified.
L*  duplicate InferenceProvider in parallel/inference_provider.py; _convert_relative_paths_to_absolute
    rewrites any attr equal to an existing filename (token_type="bpe" -> abs path, verified); infer()
    mutates shared config (test_set, parallel.options) which pack_model later dumps; writer handles not
    closed on shard failure; stale docstrings (NotImplementedError "always"); vacuous parallel test;
    production dict-config path untested.
