# misc-utils incremental notes

## espnet3/utils/logging_utils.py

### FINDING: duplicate "run started" / "Cluster env" log lines (verified_by_execution)
- file: espnet3/utils/logging_utils.py, lines 479-485 (log_run_metadata) and 664-667 (log_env_metadata)
- summary: log_run_metadata and log_env_metadata each emit one message twice: once via `logger.info(...)` (stacklevel=1, so record.filename/lineno point at logging_utils.py) and again via `logger.log(logging.INFO, ..., stacklevel=2)` (record points at the real caller). Looks like leftover code from a stacklevel refactor -- other messages in the same functions (Command, Python, Working directory, config paths, Git, Runtime env) are only logged once via the stacklevel=2 form.
- scenario: any stage run calls log_stage_metadata -> log_run_metadata + log_env_metadata (see stages_utils.run_stages). Every stage log therefore contains "=== ESPnet3 run started: ... ===" twice (two different timestamps, since datetime.now() is called twice) and "Cluster env:\n..." twice, while "Runtime env:" appears only once. Docstring's "Example log output" only shows one instance of each, so behavior diverges from documented output.
- verified: ran log_run_metadata/log_env_metadata against a captured StreamHandler: "run started" count=2, "Cluster env" count=2, "Runtime env" count=1.
- severity: medium (100% reproducible on every run/stage, pollutes/duplicates every stage log and could double-count in log-scraping/monitoring, but not a crash or data-correctness issue)
- suggested_fix: drop the plain `logger.info(...)` calls at lines 479 and 666, keeping only the `logger.log(..., stacklevel=2)` versions (consistent with the rest of the function).

### FINDING: no test coverage for set_stage_log_handler
- file: test/espnet3/utils/test_logging.py
- summary: test_logging.py has 14 tests covering configure_logging, set_log_format, log_run_metadata, log_stage_metadata, log_component-based helpers, build_qualified_name/build_callable_name -- but `set_stage_log_handler` (the function stages_utils.run_stages calls every stage, and the one with the already-known rank0/None handler-leak bug) has zero direct tests. Its rotation logic, `_espnet3_stage_log` marker removal, and return value are entirely untested.
- category: test-gap, severity: medium

### Note (not a new finding, context): `_run_pip_freeze` prefers `uv pip freeze` whenever `which("uv")` finds a uv binary anywhere on PATH, without checking that `uv` actually manages the venv/interpreter that is running (`sys.executable`). If a user has a system-wide `uv` installed but launched espnet3 from an unrelated venv/conda env (via plain `pip`/`python -m venv`), `uv pip freeze` can silently report a different environment's packages (or fail) instead of the running interpreter's, making the requirements.txt snapshot (written by --write_requirements) inaccurate for reproducibility auditing. Low-medium confidence real-world impact; flagging as low severity design robustness item.

## espnet3/utils/writer_utils.py

### FINDING: CUDA-tensor guard is bypassed on the custom-writer path (verified by code trace + call site)
- file: espnet3/utils/writer_utils.py, lines 155-161 (write_artifact dispatch) and 192-203 (_run_custom_writer); guard only exists at lines 211-218 (_write_builtin_artifact)
- summary: `write_artifact()` only rejects CUDA tensors inside `_write_builtin_artifact` (`if value.is_cuda: raise ValueError(...)`). When `field_config` carries a `writer:` block (the documented "Custom serialization" feature, docstring example at lines ~102-125), `write_artifact` calls `_run_custom_writer` instead, which passes the raw `value` straight to the user's writer function (`writer(value=value, output_path=output_path, **writer_dict, **options)`) with no CUDA check at all. This contradicts the docstring's blanket "Unsupported values ... CUDA tensors are rejected" claim, which is only true for the built-in path.
- scenario: `InferenceRunner._materialize_output_value` (espnet3/systems/base/inference_runner.py:39-88) forwards inference-output `torch.Tensor` values straight into `write_artifact(value, ..., field_config=artifact_config)` with no `.cpu()`/`.detach()` call anywhere in that file (grepped, zero hits). If a recipe runs inference on GPU and its output function returns a tensor still on CUDA, and the field's `field_config` in `inference.yaml` uses a custom `writer:` (a documented pattern -- see commented example in egs3/TEMPLATE/asr/conf/inference.yaml:151), the CUDA tensor reaches the custom writer unfiltered. A writer that does `np.asarray(value)` gets a confusing `TypeError: can't convert cuda:0 device type tensor to numpy` (instead of the intended friendly "Move the tensor to CPU" ValueError); a writer that does `torch.save(value, path)` silently bakes a CUDA-device tensor into the artifact, which then fails to `torch.load` on any machine without that GPU/CUDA available.
- evidence: writer_utils.py:211-218 `if isinstance(value, torch.Tensor): if value.is_cuda: raise ValueError(...)` is inside `_write_builtin_artifact` only; `_run_custom_writer` (192-203) has no such check.
- severity: high (documented supported feature + real call site with no upstream safety net; not exercised by any currently-checked-in egs3 config, only a commented example, hence not "critical")
- suggested_fix: move the CUDA-tensor rejection (or an automatic `.detach().cpu()`) into `write_artifact()` before branching on `writer_cfg`, so it applies uniformly to both the built-in and custom-writer paths.
- confidence: 0.75

### FINDING: no atomic write for builtin artifacts (temp+rename)
- file: espnet3/utils/writer_utils.py, lines 219-240 (_write_builtin_artifact)
- summary: `np.save`, `sf.write`, `json.dump`, `pickle.dump` all write directly to the final `output_path` with no write-to-temp-then-`os.replace` pattern. A process kill (OOM, SIGKILL, node preemption -- common on the SLURM/PBS clusters this codebase targets, see logging_utils cluster-prefix list) or a mid-write exception (e.g. a non-JSON-serializable nested value) leaves a truncated/corrupt file sitting at the artifact's final path with no marker distinguishing it from a successfully written one.
- scenario: any downstream code that treats "artifact file exists" as "artifact already produced" (a common resume/idempotency pattern for staged pipelines) would pick up the truncated file and silently use corrupt data on retry/resume, instead of re-running inference for that item.
- severity: medium (plausible in the sharded/parallel inference path espnet3 explicitly supports, but requires an existence-based resume check downstream that I could not confirm/deny for this file alone since InferenceRunner is out of this area's assigned files)
- confidence: 0.5

### FINDING: unclear error when custom writer config omits `_target_`
- file: espnet3/utils/writer_utils.py, line 200: `target = writer_dict.pop("_target_")`
- summary: no `.get`/validation before `.pop("_target_")`; a `field_config={"writer": {...}}` missing the required `_target_` key raises a bare `KeyError: '_target_'` instead of a clear config-validation error naming the field/writer config that is malformed.
- severity: low
- confidence: 0.6

## espnet3/utils/scp_utils.py

### FINDING: input validation uses bare `assert`, stripped under `python -O`
- file: espnet3/utils/scp_utils.py, lines 77-79 and 85
- summary: `load_scp_paths` validates `task_dir.exists()` and each `path.exists()` via `assert`, which is compiled out entirely when Python runs with `-O`/`PYTHONOPTIMIZE`. In that mode `load_scp_paths` would happily return paths to nonexistent SCP files instead of failing fast with a clear message, pushing the failure downstream (e.g. into `BaseMetric`'s file-reading code) with a much less informative error.
- severity: low (requires `-O`, which is unusual but not implausible in some deployment/packaging setups)
- confidence: 0.4
- note (not a finding): scp_utils.py does not itself parse or write SCP file *contents* (no handling of spaces/tabs/newlines in values, duplicate keys, encoding) -- it is purely a path-existence resolver. The actual SCP writing (hyp.scp/ref.scp) happens in espnet3/systems/base/inference_runner.py, which is outside this area's assigned files.

## espnet3/utils/download_utils.py

### FINDING: entire module is dead code (0 production callers) -- confirmed via repo-wide grep
- summary: `grep -rn "download_url\|extract_targz\|download_utils" --include=*.py .` across the whole repo shows download_utils is imported/used only by its own test file (test/espnet3/utils/test_download.py). No file under espnet3/ or egs3/ calls `download_url`, `extract_targz`, or `setup_logger` from this module. Meanwhile, real dataset download/extraction is separately hand-rolled (e.g. `urllib.request.urlretrieve` directly in egs3/mini_an4/asr/dataset/builder.py) rather than reusing this "canonical" helper.
- category: design (dead code / duplicated logic), severity: medium
- confidence: 0.85 (grep-verified; can't rule out dynamic/plugin-style imports I didn't search for)

### FINDING: extract_targz has no path-traversal protection (tarfile.extractall with no filter)
- file: espnet3/utils/download_utils.py, lines 156-158
- summary: `tar.extractall(path=dst_dir)` is called with no `filter=` argument (or member allowlist). On Python 3.10-3.11 this is the classic unrestricted extraction: a tar entry with `../../` in its name, an absolute path, or a symlink pointing outside `dst_dir` is extracted wherever it says, i.e. arbitrary file write outside `dst_dir` (CVE-2007-4559-class issue; Python only started defaulting to the safe `'data'` filter in 3.14).
- scenario: if this helper is ever wired up to download+extract a dataset archive from a URL (which is exactly its apparent purpose, paired with `download_url`), a compromised mirror/CDN or a malicious `.tar.gz` (or a corrupted download that happens to still parse as a tar with crafted paths) could write files anywhere the running user can write, e.g. overwriting files elsewhere in the recipe tree or home directory.
- severity: medium (currently unreachable / dead code per the finding above, so no live default-recipe path is affected today; would be high/critical the moment any recipe wires this up to download third-party archives without adding a filter)
- suggested_fix: pass `filter="data"` (or a custom filter that rejects absolute paths / `..` / symlinks) to `extractall`.
- confidence: 0.8

### FINDING: download_url has no checksum verification, no retry, and leaves partial files on failure
- file: espnet3/utils/download_utils.py, lines 104-138
- summary: `download_url` calls `urllib.request.urlretrieve(url, dst_path, reporthook=progress)` directly with no hash/checksum check against an expected digest, no retry on transient network errors, and no existence/staleness check before downloading (always re-downloads, no "already downloaded, skip" fast path). `urlretrieve` itself writes straight to `dst_path` (no temp-file+rename), so if the connection drops mid-transfer the exception propagates but a truncated file is left at `dst_path`.
- scenario: any caller that later does `if dst_path.exists(): skip download` (a very common pattern for exactly this kind of helper, and the pattern used by the hand-rolled downloader in egs3/mini_an4/asr/dataset/builder.py) would treat the truncated file as a successfully cached download and silently proceed with corrupt/incomplete data.
- severity: medium (same "currently dead code" caveat as above)
- confidence: 0.7

### FINDING (test-quality): test_extract_targz always mocks tarfile.open, never exercises real extraction
- file: test/espnet3/utils/test_download.py, tests `test_extract_targz` (60-88) and `test_extract_targz_accepts_none_logger` (90-108)
- summary: both tests replace `download_utils.tarfile.open` with a `DummyTar` stub whose `extractall` is a no-op that just records the `path` argument. No test ever calls the real `tarfile.extractall`, so the test suite would not catch a path-traversal regression, an unsupported-filter-argument TypeError on some Python versions, or any other real-extraction behavior change.
- category: test-gap, severity: medium
- confidence: 0.7
