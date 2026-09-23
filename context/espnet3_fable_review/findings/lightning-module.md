# lightning-module incremental notes (reviewer: lightning-module area)

Files read in full: espnet3/components/modeling/lightning_module.py (1203), espnet3/components/modeling/optimization_spec.py (219),
egs3/TEMPLATE/asr/conf/training.yaml (284), test/espnet3/components/modeling/test_model.py (803),
test_model_with_optim_scheduler.py (869), test_optimization_spec.py (76). Also read for call sites: espnet3/systems/base/training.py,
espnet3/components/trainers/trainer.py, espnet3/components/callbacks/default_callbacks.py, ema.py excerpts.

## lightning_module.py

- L916-976 _run_multi_optimizer_updates: manual_backward(step.loss) writes .grad into EVERY parameter reachable from that loss, not only
  the named optimizer's params. zero_grad for optimizer X only runs when X.accum_counter==0 (L952) or right after X steps (L972). So in a GAN
  where g_loss backprops through D, any D accumulation (accum_grad_steps>1 or step_every_n_iters>1, both documented knobs) makes D's
  accumulated gradient include dL_G/dD. Silent wrong gradient. HIGH. Fix: manual_backward(loss, inputs=params_of(step.name)) or zero
  other optimizers' grads before each backward.
- L955-961 accumulation semantics: when meets_accum is True but meets_iter False, the loop `continue`s and keeps accumulating unscaled
  gradients (loss already divided by accum_grad_steps only). step_every_n_iters=N, accum_grad_steps=1 => N micro-batches summed with NO
  1/N scaling; step_every_n_iters=3, accum_grad_steps=2 => 3 grads scaled by 1/2. TEMPLATE comment "only step on every N-th training
  iteration" implies a no-op on other iterations. HIGH-ish (silent grad scale), confidence moderate (could be argued intended).
- accum_counter persists across epoch boundaries (never reset in on_train_epoch_end) and is checkpointed (L1103-1110) while .grad buffers
  are not: resume with accum_counter>0 => next step applies fewer micro-batches at 1/accum scale. MEDIUM.
- L707-709 configure_optimizers resets self._optimizer_states to fresh OptimizerRuntimeState() AFTER Lightning has already called
  on_load_checkpoint (restore_model runs before strategy.setup -> configure_optimizers). So restored update_step/accum_counter are
  discarded on resume. test_checkpoint_restores_runtime_state calls configure_optimizers BEFORE on_load_checkpoint (opposite of Lightning
  order) so it passes. MEDIUM (verify order via grep).
- L220-222 _sync2skip: uses config.num_device == 1 to decide "no collective". num_device is per-node; num_nodes>1 with num_device=1 =>
  ranks decide independently => one rank skips backward, others all-reduce => DDP hang on first NaN. HIGH (distributed). Fix: use
  self.trainer.world_size > 1 / torch.distributed.is_initialized().
- L1072-1078 on_train_epoch_end monitored epoch scheduler: callback_metrics.get(monitor) is None on any epoch without validation
  (check_val_every_n_epoch>1, val_check_interval, limit_val_batches=0) -> RuntimeError "metric was not logged" at first epoch end.
  Message misleading (not logged *yet*). MEDIUM.
- L905-913 step-scheduler+monitor misconfig is only detected at the first optimizer update (after optimizer.step already ran at L971),
  not in SchedulerSpec.validate. LOW.
- L623-631 / L714-717 single path requires BOTH optimizer and scheduler; scheduler missing/null -> ValueError "Must specify either
  `optimizer` or `optimizers` and `scheduler` or`schedulers`" (also missing space). Multi path requires a scheduler per optimizer
  (names must match exactly). LR scheduler is mandatory everywhere. LOW/MEDIUM design.
- L640 interval = str(getattr(config,"scheduler_interval","step")): a blank YAML key (`scheduler_interval:` -> None) becomes "None" and
  trips the assertion. egs3/TEMPLATE/tts/conf/training.yaml:48-49 has both keys blank. Check tts template has optimizer+scheduler.
- L613-616 docstring says monitor may be `train/<key>`; train stats are logged on_step only so callback_metrics holds the LAST batch
  value, not an epoch aggregate -> plateau scheduler on a train key sees single-batch noise. LOW docs/design.
- Multi path + default best_model_criterion `valid/loss` (trainer.py:67, default_callbacks.py:427, TEMPLATE:194): docs example stats
  have generator_loss/discriminator_loss and auto keys valid/<name>/loss, no `valid/loss` -> ModelCheckpoint raises
  MisconfigurationException after first validation unless best_model_criterion changed; TEMPLATE example says nothing. MEDIUM.
- _log_stats: v.item() per stat per step (GPU sync) — perf only, skip. weight=None in multi path -> Lightning infers batch_size from the
  (uids, dict) batch with a warning; validation mean weighting then uses inferred size. LOW note.
- L1162-1169 state_dict/load_state_dict forward to self.model (no `model.` prefix); load_state_dict drops `assign` kwarg. LOW.
- nan_countdown: reset to 1 on success (L287) but starts at 0; validation NaNs share the counter. LOW nit.
- L1130-1132/1149-1151 use_espnet_collator flag set on dataset at each dataloader build; known reset by CombinedDataset.shard (other area).

## optimization_spec.py
- L87-94 hasattr(cfg,"accum_grad_steps") is True for a blank YAML value (None) -> int(None) TypeError with no config context. LOW.
- OptimizerSpec.params typed str but a YAML list -> re.escape(ListConfig) TypeError. LOW.
- SchedulerSpec.validate does not reject interval=step with monitor (deferred to runtime). LOW.
- TEMPLATE training.yaml:150/161 says "substring used to select parameters"; implementation (lightning_module.py:442-451) matches on
  dot-delimited boundaries. docs-mismatch LOW.

## training.yaml (TEMPLATE asr)
- L205 `init:` top-level documented as "forwarded to ESPnet's initializer" but trainer.py:74-75 reads getattr(self.config,"init") where
  self.config is config.trainer (training.py:37). Top-level init is silently ignored; putting it under trainer: makes lightning.Trainer(init=..)
  TypeError since _del_config_key_on does not strip it. Verify via grep that nothing else reads config.init.
- L200 `seed:` blank -> no seed_everything -> non-reproducible by default (espnet2 default seed=0). LOW design.

## tests
- test_model.py: CustomCollate.__call__(batch) missing self; test never iterates the loader so never notices. test-quality LOW.
- test_checkpoint_restores_runtime_state: order inverted vs Lightning. test-quality MEDIUM (masks the bug above).
- test_clip_gradients_uses_optimizer_spec monkeypatches clip_gradients; no test of real clip path. test-gap LOW.
- No test for accum_grad_steps>1 gradient scale; no test for grad contamination; no test for multi-node _sync2skip. test-gap.
