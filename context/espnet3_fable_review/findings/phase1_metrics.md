# Phase 1 / metrics (measure stage, BaseMetric, WER/CER/TER) -- reviewer notes

Files read in full: espnet3/systems/base/metric.py, espnet3/components/metrics/base_metric.py,
espnet3/systems/asr/metrics/{cer,ter,wer}.py, egs3/{TEMPLATE,mini_an4,librispeech_100}/asr/conf/metrics.yaml,
egs3/TEMPLATE/tts/conf/metrics.yaml. Supporting (full): utils/scp_utils.py, systems/base/system.py, utils/run_utils.py,
egs3/TEMPLATE/asr/run.py, systems/base/inference.py, systems/base/inference_runner.py, utils/stages_utils.py,
test/espnet3/{systems/base/test_metric.py,components/metrics/test_base_metric.py,systems/asr/metrics/test_metrics.py},
egs3/{TEMPLATE,mini_an4}/asr/conf/inference.yaml. Skimmed: utils/config_utils.py, utils/logging_utils.py,
utils/publication_utils.py (metrics.json consumer), espnet2/text/cleaner.py, espnet2/text/sentencepiece_tokenizer.py.

Environment note: jiwer is NOT installed in the pixi env; staged jiwer 4.0.0 (latest, unpinned in pyproject) under
SCRATCH/pylib for verification. The 3 metric test files pass against jiwer 4.0.0 (30 passed).

## Verified findings (scripts in SCRATCH/e2e and SCRATCH/chk)
1. HIGH  Documented scoring path `run.py --stages measure --training_config X --metrics_config conf/metrics.yaml`
   (librispeech_100 readme step 3, mini_an4/librispeech metrics.yaml "Common usage") -> metrics_config has no
   `inference_dir` (only copied from --inference_config; TEMPLATE/recipe metrics.yaml never define it; training.yaml
   has none) -> `_resolve_test_sets` raises omegaconf ConfigAttributeError "Missing key inference_dir".
   validate_experiment_context checks exp_tag/exp_dir (unused by measure) but not inference_dir.
2. MED   `python -O` strips the assert-based UID/length checks in BaseMetric.iter_inputs -> same-length, misordered
   ref/hyp scored silently (WER 100.0 where truth is 0.0).
3. MED   Zero-utterance ref.scp/hyp.scp -> jiwer 4.0 wer([],[]) == 0 -> {"WER": 0} reported as a perfect score.
4. MED   results keyed by class path -> two metrics of the same class (supported via `inputs`) overwrite each other in
   metrics.json and share one `wer_alignment` file.
5. MED   Test sets discovered by scanning inference_dir (inference_config.dataset.test never propagated): stale dirs from
   earlier inference configs are scored/bundled; a dir left by a failed infer (mkdir before dataset build) aborts the
   whole stage with "Missing SCP file".
6. MED   BaseMetric.__call__ annotates `output_dir: Path`; measure passes a str (verified type 'str').
7. MED   TTS template `metrics:` null passes `assert hasattr(...)` -> TypeError 'NoneType' object is not iterable.
8-16 LOW: "." placeholder silently alters denominators (mixed case 50.0 vs 66.67); list-form `inputs` alias mismatch ->
   bare KeyError('ref'), null `inputs` -> ValueError from to_container; TER example path exp/bpe_5000 vs actual
   data/bpe_5000, lazy SPM load fails only at call time; duplicate utt_ids double counted (42.86 vs 40.0);
   unregistered pytest mark execution_timeout; no e2e test with real metrics via Hydra; unescaped \n/\t in values
   (tab: WER 200%); alignment computed twice; nonexistent inference_dir -> raw FileNotFoundError.

Checked and OK: edit distance (ref 'a b c' hyp 'a c' -> 33.33); CER counts spaces (consistent with espnet2 char
tokenization); TER re-tokenizes both sides like espnet2 stage 13; hyp.scp/ref.scp are written in the same order by
InferenceRunner.write_record so lockstep alignment holds; stage logs are files (infer.log) so they do not pollute the
directory scan; `_convert_: all` injection makes `clean_types: null` instantiate cleanly; jiwer install hint matches
pyproject `asr` extra.
