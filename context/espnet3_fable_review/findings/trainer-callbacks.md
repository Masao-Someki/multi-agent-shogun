# trainer-callbacks incremental notes (Phase1)

## espnet3/components/trainers/trainer.py
- L123-131: use_distributed_sampler warning checks `hasattr(self.model.config, ...)` (full training config) but reads `self.config.use_distributed_sampler` (trainer block) and warns when the value is ALREADY False (`not self.config.use_distributed_sampler`). Dead/inverted warning. low.
- L118-121/127-130: warning strings missing a space ("to setreload_dataloaders_every_n_epochs"). low.
- L96-100 / L74 / L133 / L138: config type hint allows Dict but code uses attribute access (`self.config.log_every_n_steps`, `self.config.reload_dataloaders_every_n_epochs = 1`) -> AttributeError on plain dict. docs-mismatch low/medium.
- L133/L138: mutates caller's shared `training_config.trainer` in place (side effect), then deep-copies. design low.
- L99: OmegaConf.to_container(best_model_criterion) fails if caller passes plain list (docstring says ListConfig, typecheck absent for that arg). Check training.py call site.
- L74: `init` key used for weight init but NOT removed from trainer_config -> lightning.Trainer(init=...) TypeError if user sets trainer.init. Check training.yaml.
- L87: logger default None -> Lightning: no loggers; default callbacks include LearningRateMonitor which raises MisconfigurationException at on_train_start when trainer.loggers is empty. Need to check training.yaml/tests.

## espnet3/components/callbacks/default_callbacks.py
- L504-511 ordering + Lightning `_reorder_callbacks` moves all Checkpoint callbacks to the END -> AverageCheckpointsCallback.on_validation_end runs BEFORE the best ModelCheckpoints save this epoch's ckpt -> averaged model always lags one validation; the final epoch's best ckpt never included; with max_epochs == nbest the `ave_{nbest}best.pth` file is never produced (only ave_1..ave_{nbest-1}). Need to verify with lightning source / tiny run and check how infer picks the averaged file.
- L195-198: filename `ave_{len(checkpoints)}best.pth` varies with the current count -> stale ave_1best/ave_2best files left behind; consumer must know the K.
- L156-169: dtype check `startswith("torch.int")` misses uint8/bool -> those buffers get divided into float. low.
- L132: safe_torch_load(weights_only?) on Lightning ckpt containing hparams/loops -> check.
- MetricsLogger L299: `on_after_optimizer_step` is not a Lightning Callback hook -> optim_step_time never recorded (dead code), unless module calls it manually. Check grep.
- MetricsLogger L314-322: sums every key in callback_metrics, which contains `train/loss`, `train/loss_step` and stale `train/loss_epoch` from previous epoch (if module logs on_step+on_epoch) -> duplicated/stale keys in the log line. Check lightning_module self.log calls.
- MetricsLogger L275-277: iter_time spans validation/epoch boundaries (first batch after validation gets the whole validation duration). low.
- get_default_callbacks L467-474: last ckpt `save_last="link"`, top_k=1 -> `last.ckpt` symlink; crash between remove-previous and relink leaves dangling symlink. Check training.py resume discovery.
- L487: '/' in monitor replaced by '.' in filename -> nested-dir issue handled OK.

## CONFIRMED via lightning source (callback_connector.py:240-258): _reorder_callbacks moves every Checkpoint to the END of trainer.callbacks. Consequences:
- AverageCheckpointsCallback.on_validation_end runs before the best ModelCheckpoints save -> average lags one validation, never includes final epoch's best ckpt; with max_epochs <= nbest the `ave_{nbest}best.pth` is never written (librispeech_100 inference.yaml:61 expects `${exp_dir}/valid.acc.ave_10best.pth`; mini_an4 max_epochs=1 -> no ave file at all, inference.yaml hardcodes `epoch0_step1_valid.loss.ckpt`).
- EMACallback.on_validation_end (_restore_online) runs before ModelCheckpoint.on_validation_end -> best ckpts (selected by the EMA-evaluated metric) store ONLINE weights; with save_weights_only=True the callbacks' on_save_checkpoint may be skipped -> EMA weights absent from best ckpts (verify dump_checkpoint).
- `on_after_optimizer_step` is not a Lightning hook (grep over lightning/pytorch: no hits) -> MetricsLogger.optim_step_time never recorded. medium/low.
- lightning_module._log_stats logs with log_dict(prog_bar, logger, sync_dist) default on_step/on_epoch (training_step: on_step=True,on_epoch=False) -> callback_metrics has only `train/x` keys; no `_step/_epoch` duplication. OK.

## espnet3/systems/base/training.py + egs3/TEMPLATE/asr/conf/training.yaml
- training.yaml:204 documents a TOP-LEVEL `init:` ("forwarded to ESPnet's initializer") but trainer.py:74 reads `init` from config.trainer (training.py:37 passes config=config.trainer). Top-level init is silently ignored; if a user puts it under trainer:, trainer.py does not strip it -> lightning.Trainer(init=...) TypeError. Verify no other consumer of config.init (grep).
- training.py: no resume logic; `fit: {}` default -> re-running `--stages train` after a crash restarts from scratch in the same exp_dir; user must know to add `fit: {ckpt_path: last}`. Check docs/grep for ckpt_path.
- training.py:33 ESPnetLightningModule(model, config) then trainer mutates config.trainer in place (reload_dataloaders_every_n_epochs, use_distributed_sampler).
- LearningRateMonitor default callback requires a logger (lr_monitor.py:121-124 raises MisconfigurationException) -> any recipe with `trainer.logger: null/false` crashes at on_train_start with a message that does not mention ESPnet3's default callbacks. Check egs3 configs for logger.

## espnet3/components/callbacks/ema.py (+ vendored_ema.py)
- setup(): EMA only on rank 0, created before checkpoint restore; on_load_checkpoint restores EMA state if present. Under trainer.validate/test (stage != fit) EMA is never created -> docstring says swaps for test but test outside fit uses online weights silently. low/medium.
- update timing uses trainer.global_step delta -> correct w.r.t. accumulate_grad_batches (automatic path). Manual multi-optimizer path: global_step counts every optimizer.step() -> still one EMA update per batch. OK.
- vendored EMA defaults update_every=10, update_after_step=100, warmup power=2/3 -> effective decay ramps slowly (documented).
- _swap_in_ema broadcasts state_dict tensors in registration order across ranks; fine for DDP; FSDP would break (sharded). Not default.
- on_validation_end restore happens BEFORE ModelCheckpoint saves (reorder) -> best ckpts store online weights while metric computed on EMA weights. HIGH.
- No on_exception restore: if validation raises, online model keeps EMA weights (process usually dies; low).

## VERIFIED BY EXECUTION (scratch repro.py, lightning 2.6.1, CPU, plain LightningModule + get_default_callbacks + EMACallback)
- trainer.logger absent/False -> `MisconfigurationException: Cannot use LearningRateMonitor callback with Trainer that has no logger.` (default LearningRateMonitor cannot be disabled).
- trainer.enable_progress_bar=False -> `MisconfigurationException: Trainer was configured with enable_progress_bar=False but found TQDMProgressBar in callbacks list.` (default TQDMProgressBar cannot be disabled; same class as enable_checkpointing=False vs ModelCheckpoint).
- trainer.callbacks order at runtime: [AverageCheckpointsCallback, LearningRateMonitor, MetricsLogger, TQDMProgressBar, (EMACallback), ModelCheckpoint, ModelCheckpoint] -> Average/EMA hooks run before checkpoint saves.
- max_epochs=3, criterion ("valid/loss",3,"min"): files = epoch0/1/2 best ckpts, last.ckpt, step12.ckpt, valid.loss.ave_1best.pth, valid.loss.ave_2best.pth; NO ave_3best.pth although best_k_models has 3 entries.
- EMA run: best ckpt keys = [epoch, global_step, loops, pytorch-lightning_version, state_dict] -> no ema_model_state_dict (callbacks' on_save_checkpoint gated by `if not weights_only` in checkpoint_connector.py dump_checkpoint); last.ckpt does contain ema_model_state_dict.
- Second fit() into same exp_dir (no resume): creates last-v1.ckpt and step4.ckpt; last.ckpt still -> old run's step12.ckpt. publication.yaml:72 packs `last.ckpt` -> stale model.
