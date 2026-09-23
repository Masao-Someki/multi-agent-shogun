# Phase1 / data-loading incremental notes (reviewer: data-loading)

## espnet3/components/data/dataloader.py
- 83-90,258: `_get_world_info`/`_build_iter_factory` decide "distributed" by `self.num_device > 1` (num_device = per-node `config.num_device`). Multi-node DDP with 1 GPU per node (num_device=1, num_nodes>1, both in TEMPLATE) -> world_size treated as 1, rank 0 on every rank -> batches are NOT split across ranks (every rank iterates all batches) and shard_idx is rank-independent; EpochSyncIterator (which uses torch.distributed.is_initialized()) still syncs, so no deadlock, just silent data duplication (each utterance seen num_nodes times per epoch, effective batch size x num_nodes). HIGH.
- 192-217/226-244: TEMPLATE puts `total_shards`/`dist_world_size` under `dataloader.train` but the code never reads config keys (reads dataset attributes at 109/119). With `iter_factory: null` (documented Case 2) the two keys are forwarded via `**config` to torch DataLoader -> TypeError unexpected kwarg. Dead/misleading config + crash. MEDIUM-HIGH (verified).
- 204/237: mode config without an `iter_factory` key at all -> `config.iter_factory` raises ConfigAttributeError (Missing key) / pop KeyError. Only `iter_factory: null` works. MEDIUM/LOW robustness.
- 258-288: DDP tail-drop removes the same `remainder` batches every epoch (batch list from build_batch_sampler is deterministic; shuffle only permutes order afterwards). For sorted/numel types the tail holds the longest or shortest utterances -> they are never trained on. Also keep=0 when total < world_size -> empty epoch. MEDIUM.
- 140-141 + trainer.py 130-131: ShardedDataset + standard DataLoader (the only shard path that can work, since iter_factory shape files are global) under Lightning DDP: `use_distributed_sampler` stays True (only set False when is_espnet_sampler), so Lightning wraps the rank-specific shard in DistributedSampler -> each rank sees only 1/W of its own shard. HIGH (not executed).
- 195: valid dataloader is also sharded & rotated by epoch -> valid/loss across epochs computed on different shards; best_model_criterion compares incomparable numbers. MEDIUM.
- ShardedDataset + iter_factory: batches built from global shape_files (uids of the whole dataset) then `dataset[uid]` on a shard -> KeyError for uids outside the shard; shape_files cannot rotate with epoch. Sharding is effectively incompatible with the espnet2 iter_factory path. MEDIUM design.
- build() docstring claims ValueError on bad mode; no validation exists (getattr default {}). LOW docs.

## espnet3/components/data/iterator.py
- Logic OK; all-reduce per batch; len is an upper bound. Inconsistent "is distributed" detection vs dataloader.py (is_initialized vs num_device>1) -> see HIGH above. Non-issue otherwise.

## espnet3/components/data/collect_stats.py
- 499-504 (+ parallel/base_runner.py 84,306-357,458-480): CollectStatsRunner never passes `resume`, so BaseRunner.resume=True. Re-running collect_stats with the same dataset length and batch_size finds manifest.json identical and split.N/done present -> skips all shards and re-merges the OLD shard files, regardless of model/frontend/dataset-content changes. VERIFIED: second run with DummyModel scale=2.0 reproduced scale=1.0 sums exactly. TEMPLATE stats_dir=${recipe_dir}/exp/stats is shared by every exp_tag in a recipe (mini_an4 configs inherit it; librispeech GlobalMVN reads ${stats_dir}/train/feats_stats.npz). HIGH (silently wrong normalization stats / shape files).
- 368-374, 82-95, 437-450: sum/sum_square accumulated in float32 (defaultdict(float) + float32 arrays stays float32, verified). espnet2 parity. LOW.
- 506-507, 569-579: empty split -> no *_shape / *_stats.npz, `stats_keys` with only "\n"; failure surfaces later as FileNotFoundError in build_batch_sampler. LOW.
- 85-96 vs espnet2/main_funcs/collect_stats.py 55-62: espnet3 writes shape files only for collect_feats outputs and includes `*_lengths` keys (feats_lengths_shape, feats_lengths_stats.npz); espnet2 writes shape files for every input key (speech_shape, text_shape) and skips *_lengths. espnet2-style `shape_files: [speech_shape, text_shape]` cannot be ported. LOW.
- 43-50 tuple unpacking mismatch: already known from other area (not duplicated).
- Numerics/layout/merge order otherwise OK: shards enumerated in id order, chunks partition indices, npz keys count/sum/sum_square match GlobalMVN (espnet2/layers/global_mvn.py 48-52).

## espnet3/systems/base/training.py
- 31-40, 67-68 (+ lightning_module.py 159-164, 1170-1203; collect_stats.py 121-131,173-181,245,270): collect_stats stage builds a full ESPnetLightningModule (instantiates DataOrganizer + model) and ESPnet3LightningTrainer (loggers/callbacks) only to call model.collect_stats(), which re-instantiates the organizer 2x per mode and the model 1x per mode -> organizer built 5x, model 3x. MEDIUM design.
- 62-65 normalize pop: known (other area).

## espnet3/components/data/dataset_module.py
- 207 (+ docstring 184-186): `data_src_args: null` (natural YAML for "no args") -> dict(None) TypeError "'NoneType' object is not iterable"; docstring promises ValueError. VERIFIED. MEDIUM (misleading error).
- 102-115: local dataset module re-executed and sys.modules overwritten on each call (DataOrganizer calls it per entry; collect_stats path instantiates the organizer 5x) -> import-time side effects repeat, distinct class objects. LOW.
- 61-72: hyphen normalisation docstring implies `my-recipe/asr` works; a hyphenated egs3 dir is not importable. LOW docs.
- 31-36: _to_plain_dict(resolve=False) leaves `${dataset_dir}` literal for attached DictConfig; safe only because DataOrganizer resolves first (data_organizer.py 436-438). LOW.

## espnet3/components/data/dataset_builder.py: pure ABC, nothing actionable.

## dataloader.py extra
- 216-217: `mode` never passed to _build_iter_factory/_build_standard_dataloader -> valid loader logged as "[train]" and, because log_dataloader/_LOGGED_DISTRIBUTED_BATCHES dedupe by label, the valid loader is never logged. LOW.

## Tests
- test_collect_stats.py 209-211/235/365/414: use_parallel=True uses env=local -> _plan_shards gives 1 shard, _run_local -> multi-shard merge and Dask never exercised; no re-run test; no CombinedDataset test. MEDIUM test-gap. Line 20 mp.set_start_method("fork", force=True) at import mutates session-global state. LOW.
- test_dataloader_builder.py: no multi-node/num_device=1 case, no missing-iter_factory-key case, tail-drop test does not check stability across epochs, sharding tests bypass Lightning (so DistributedSampler double-sharding is invisible).
- test_iterator.py / test_dataset_module.py: adequate for what they cover; no `data_src_args: None` test.
