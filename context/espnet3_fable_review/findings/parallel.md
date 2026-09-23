# parallel area -- incremental notes (Phase1/parallel)

## espnet3/parallel/parallel.py (read in full, 355 LOC)
- 113-133 set_parallel mutates the caller's DictConfig (`config.options = options`) -> on a struct-mode config lacking `options`, hasattr is False and the assignment raises ConfigAttributeError; also copies via copy.copy (shallow). medium/low; check call sites.
- 335-338 get_client: build_client() then _register_worker_plugin() happen BEFORE the try/finally -> a failing plugin registration leaks the Client/cluster. low.
- 342 stale comment "Avoid shutdown for LocalCluster..." but the code closes every cluster. low docs.
- 288-296 wrapped(): overwrites Dask's plugin registry entry worker.plugins["env"] with a plain dict (in DictReturnWorkerPlugin.setup); works because distributed uses hasattr(plugin,"teardown"), but fragile. low design.
- 61,125-133 module global parallel_config without lock; set_parallel(None) re-reads the global. low.
- 144-145 env=="local" LocalCluster path is dead for BaseRunner (known finding). 

## espnet3/parallel/base_runner.py (read in full, 480 LOC)
- 283-304 _plan_shards: contiguous chunks, shard_id in order -> concatenate_shard_files preserves item order (verify by snippet). Empty items -> [] shards -> merge([]). num_shards = n_workers only when env != local.
- 327 manifest equality `manifest_shards != planned_shards` compares JSON-roundtripped data with in-memory items: tuple / numpy-int indices would yield a false "shard plan changed" RuntimeError. medium if callers pass non-int; check callers.
- 375-394 _run_one_shard: init_state()/open_writers() run BEFORE the try; if forward raises, finalize_state()/close_writers() are never called -> writers left open (unflushed partial shard files remain, done marker absent) ; finally only unlocks. medium.
- 336-357 pre-locks every pending shard on the driver before running any (known leak). In Dask mode the lock is created by the driver PID and released by a worker -> pid in lock file is meaningless; no staleness check.
- 410-456 _run_parallel_dask: setup_fn closes over provider_setup; shard_task closes over runner_cls; results (whole state incl. records) shipped back to driver.
- 458-480 __call__: batch_size validated only when not None; indices materialised to list.

## espnet3/parallel/env_provider.py (88 LOC): abstract only; docstring says heavy init should be inside setup fn.
## espnet3/parallel/inference_provider.py (96 LOC)
- 160-178 build_worker_setup_fn's closure references self.build_dataset/self.build_model/self._log_env -> `self` (with self._local_env = prebuilt dataset+model) is a free variable of `setup` -> registering the WorkerPlugin pickles the whole driver-side model/dataset to every worker. HIGH if this class is the one used; check systems/base version + egs3 usage.
- 122 __init__ eagerly builds dataset+model on the driver even for fully distributed runs. medium design.
- 102,180-185 _LOGGED_ENV module global -> logs once per process; fine.

## espnet3/systems/base/inference_runner.py (read in full, 437 LOC)
- 110-136 vs 296-346: constructor stores self.idx_key/hyp_key/ref_key but write_record (staticmethod) takes idx_key/hyp_key/ref_key/output_keys ONLY from **env (provider params) -- BaseRunner.reduce_state passes env only. Constructor args are dead unless the provider params duplicate them; docstring example 422-427 `InferenceRunner(provider, output_dir=..., idx_key="utt_id")` misleads. resolve_idx_key (138) has no caller? (grep). HIGH/medium depending on BaseSystem wiring.
- 324-336 output_keys explicitly configured but absent from a record -> raw KeyError at output[field_key] (validation 149-181 only checks idx/hyp/ref). low/medium.
- 346 scp line f"{idx_value} {value}\n": a str hyp containing '\n' corrupts the scp; idx_value containing '/' used as artifact filename (59). low.
- 365-389 merge([]) (empty test set / zero indices) -> RuntimeError "No output keys found in inference results." misleading. medium-low; check caller indices.
- 276-280 batched path wraps ANY exception (OOM, KeyError in output_fn) into "Batched inference failed ... set batch_size to None" (chained). low misleading.
- 433-437 _load_output_fn lru_cache keyed by path; fine.

## espnet3/systems/base/inference_provider.py (read in full, 321 LOC)
- 85-91 __init__: self.config.update(self.params) mutates the caller's DictConfig in place (no copy): params leak into config.model/dataset namespace and into subsequent calls reusing the same config; None config -> AttributeError; struct config -> ConfigKeyError; non-primitive params (docstring 72-74 says "tokenizer") -> UnsupportedValueType. medium docs/design.
- 207-216 build_dataset: dict input instantiates the organizer twice (207-212), non-dict/non-DictConfig -> UnboundLocalError organizer; `config.test_set` missing -> organizer.test[None]. low.
- 118-148 setup_fn correctly captures only cls/config/params (unlike parallel/inference_provider.py). OK.
- 262-271 build_model chdir(recipe_dir) then _convert_relative_paths_to_absolute walks the whole model graph rewriting any str attr that happens to name a file relative to recipe_dir. low hazard.
- 267 instantiate(config.model, device=device) forces every model _target_ to accept `device`. design note.

## espnet3/systems/tts/remove_long_short_runner.py (106 LOC) / remove_long_short_provider.py (113 LOC)
- 367 forward isinstance(idx, int) -> numpy ints would be iterated. low.
- 383-384 sf.info(wav_path) relative path resolved against worker cwd. note.
- provider does not capture self; entries list rebuilt per worker from manifest. OK. n_dropped_empty put in env but not surfaced by merge (check tts system caller).

## tests (test/espnet3/parallel/*.py, read in full) + doc/espnet3/parallel.md + call sites
- test_parallel.py: exercises get_client/wrap_func_with_worker_env directly on a LocalCluster; nothing goes through BaseRunner._run_parallel_dask. test_base_runner_batch.py: local path only; test_failed_shard_releases_lock uses ONE shard so the mid-loop/other-shard lock leaks are invisible. test_inference_runner.py: misnamed -- tests an STFTRunner(BaseRunner), never InferenceRunner; its "parallel_shards" tests set env=local n_workers=2/3 so they run on the driver. test_inference_provider.py tests espnet3.parallel.inference_provider.InferenceProvider, which no egs3 config uses (egs3 -> espnet3.systems.base.inference_provider.InferenceProvider).
- doc/espnet3/parallel.md 72-91 and base_runner.py:72 reference `parallel_map`, which does not exist anywhere. base_runner.py class docstring 60-68 documents async_mode/async_specs_dir/async_num_workers/async_result_dir -- none exist in __init__ (78-91).
- Verified by execution (scratch verify.py / verify2.py): shard plan contiguous+ordered, merge order preserved; numpy int indices -> TypeError at _write_manifest; tuple indices -> false "shard plan changed"; struct cfg w/o options and options:null -> exceptions in set_parallel; parallel/inference_provider setup closure captures self (5MB pickled); systems/base provider rejects object params (UnsupportedValueType); failing forward leaves open writers; _filter_pending_shards leaks locks acquired before the failing shard; provider param `output_dir` hijacks the shard dir (done written elsewhere, lock left, FileNotFoundError).
- Callers: inference.py:89 set_parallel(getattr(config,"parallel",None)) and training.py:54 / tts/system.py:124,429 `if config.get("parallel")` -> a stage without `parallel` inherits the previous stage's global parallel_config within one process (run_stages).
- collect_stats.py:281 setup() reads self.config.write_collected_feats -> captures self (same pattern as parallel/inference_provider).
