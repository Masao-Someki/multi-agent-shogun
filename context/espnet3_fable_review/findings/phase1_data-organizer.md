# Phase1 / data-organizer — DataOrganizer / CombinedDataset / data_src resolution

Verified by execution (scratch scripts verify_combined.py, verify_organizer.py, verify_local_module.py, verify_builder.py) unless marked (analytic).

## High
1. dataset.py:393-398 `CombinedDataset.shard()` builds a fresh CombinedDataset whose `_use_espnet_collator` is reset to False (line 165). lightning_module.train_dataloader sets the flag on the *unsharded* dataset (1130) and DataLoaderBuilder.build shards afterwards (dataloader.py:195) -> sharded dataset returns plain dicts to CommonCollateFn. Verified: flag True -> False after shard().
2. collect_stats.py:43-50 unpacks `uid, sample = item` when `dataset.use_espnet_preprocessor` is True, but CombinedDataset returns the (uid, sample) tuple iff `use_espnet_collator` (dataset.py:212-215). TEMPLATE `preprocessor:` empty + default CommonCollateFn -> TypeError "unhashable type: 'dict'"; reverse (AbsPreprocessor + custom collate) -> TypeError "string indices must be integers". test_collect_stats.DummyDataset encodes the wrong contract, hiding this.
3. data_organizer.py:404-427/309-318: when `preprocessor._target_` is a factory *function* (TEMPLATE training.yaml:97-98 example `src.preprocess.build_preprocessor`), `is_espnet` is False so `train` is never injected; the returned AbsPreprocessor is then re-instantiated for valid with identical kwargs -> valid/test run with train=True (augmentation in validation). Verified: valid was_train == True.
4. egs3/mini_an4/asr/dataset/dataset.py:93-97 auto-builds inside the Dataset constructor; builder.is_built (builder.py:152-154) is existence-only and manifests are written non-atomically (230-235). Concurrent DDP ranks / Dask workers constructing the organizer race: zero-byte manifest -> "Manifest is empty"; mid-line -> ValueError unpack; truncated at line boundary -> silently shorter dataset. Verified is_built()==True for zero-byte manifests and the three read outcomes.

## Medium
5. dataset.py:316-353 + 271-276: in string-index mode, uids of int-addressable sub-datasets are `str(idx)` but never registered in `_uid_to_dataset`; `combined["0"]` -> ValueError (pure numeric mode accepts it). Any empty sub-dataset flips the whole dataset into string mode (dataset[0] raises IndexError). Breaks espnet iter_factory uid batches for mixed datasets.
6. dataset.py:248-262 `supports_integer_index` swallows every exception from `dataset[0]`; a corrupt/missing first file is misclassified as string-index dataset and the error re-raises from `_collect_string_keys`.
7. dataset.py:416 `__repr__` references undefined `self.multiple_iterator` -> AttributeError on repr(); log_component (%r) would crash if a CombinedDataset is ever logged.
8. dataset.py:194-217 negative int index -> first dataset's tail element with uid "-1" (string mode raises IndexError). Inconsistent, silently wrong.
9. dataset_module.py:102-116 synthetic module per call: re-executes `__init__.py` for every entry; class identity differs from `egs3.mini_an4.asr.dataset.Dataset`; unpicklable in a fresh interpreter (spawn DataLoader workers / ddp_spawn / macOS). librispeech uses absolute imports so it is picklable — inconsistent.
10. data_organizer.py:319-331 instance path mutates the caller's AbsPreprocessor (`.train=False`) and flips `.train` on a deepcopy without rebuilding train-dependent state (CommonPreprocessor.data_aug, MiniAn4TokenizeSpeedPerturbPreprocessor._delegate built in __init__).
11. data_organizer.py:279-283 split config missing `train` -> do_nothing (untokenized train) while valid tokenizes; only a warning. Documented (146) but never a sensible outcome.
12. dataset_module.py:207 `data_src_args: null` -> `dict(None)` TypeError "'NoneType' object is not iterable"; docstring says ValueError; test named *_type_error asserts ValueError.
13. data_organizer.py:23-69, 246-249 DatasetConfig is dead code and unsupported (dict(DatasetConfig) TypeError); preprocessor hint `Callable[[dict], dict]` is wrong.
14. egs3/librispeech_100/asr/dataset/dataset.py:91-94 docstring promises `utt_id` in samples; __getitem__ (134-140) omits it; src/inference.py falls back to str(idx) so SCP outputs are keyed by index.
15. egs3/mini_an4/asr/dataset/builder.py:209-217 `if not wav.exists()` treats zero-byte/partial wav left by an interrupted sph2pipe as done (analytic).
16. egs3/librispeech_100/asr/dataset/dataset.py:53-58 silently skips utterances with missing .flac / empty transcript -> silently smaller split.

## Low
17. data_organizer.py:392-394 unnamed test entries collapse to one key ("local"/data_src); test locks in last-wins.
18. dataset_module.py:162-168 wrong tag -> "No module named 'egs3.no_such_recipe'"; trailing slash -> 'egs3.mini_an4.asr.'.
19. egs3/librispeech_100/asr/conf/tuning/training_e_branchformer.yaml:44 `train: true` triggers the "will be ignored" warning at every construction.
20. egs3/TEMPLATE/tts/conf/*.yaml `dataset:` null vs ASR template providing `_target_`+`_recursive_: false` (load-bearing: without it Hydra pre-instantiates preprocessor/transform -> instance path #10).
21. data_organizer.py:299-307 split path instantiates the train preprocessor even when train is None (inference-only).
22. tests: no coverage for shard()+collator flag, `combined["<int>"]` in mixed mode, negative index, repr, factory-target preprocessor, DatasetConfig.
