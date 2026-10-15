# ESPnet3 API

See [shared contributor guidance](../../AGENTS.md) and inspect `espnet3/api/` for current modules.

The **api** package is the top of the one-way dependency the Lord promised sw005320:

    api → contract → components → systems

That is the whole point of the package: every system honours the promises declared here, in one place.


## What exists today

- `espnet3.api.inference` – calling a trained model: the fields it takes and returns, how audio reaches it, and how the `infer` stage’s provider and runner run it.

The candidates for what comes next, in the order they would pay off, are the item a recipe’s `dataset/` must return, the `metric(...)` call the `measure` stage makes, and the trainable model that fine-tuning loads weights into. Each is a de facto convention today; it belongs here once it is written down.


## The layering rule (the core)

- **api is the top.** Things below import api; api does not import them.
- Nothing in api imports components or systems – not even inside a TYPE_CHECKING block.

**One honest thing we must not paper over:**

```bash
grep -n "^from\|^import" espnet3/api/inference/loading.py | head -20
```

Gunshi found that `loading.py` imports `espnet3.utils.config_utils` and `espnet3.publication.schema`. So “api imports nothing” is **NOT true as written today**. State the rule, then state the one place that does not yet follow it.


## Where the tests live

- `test/espnet3/api/inference/` – tests for the inference layer, including device handling, loading, and model inference.


## What to do when adding a new promise

1. Add the promise to the api layer’s public interface (e.g., new inference fields or behaviors).
2. Update the docstring in `espnet3/api/__init__.py` to describe the new promise.
3. Add tests under `test/espnet3/api/` that verify the promise is honoured by systems.
4. Update any downstream documentation (recipes, egs3, doc/) that relies on the new promise.

Do not add a promise that would require api to import from components or systems. If you must, refactor the dependency so that the promise is expressed as data or configuration, not as an import.
