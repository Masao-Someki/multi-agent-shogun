# Codex 0.162.1 / vLLM 0.31.0 Harmony namespace and live Web search

The installed package has been patched. Originals were copied to `original/`
before editing. Only six files in the OpenAI Harmony/Responses rendering/conversion
path changed. Model weights, server configuration, and reasoning/tool parsers
were not changed. Playwright and matching Chromium were installed separately
under `browser-search/`; vLLM's Python dependencies were not upgraded.

## Root cause and implementation

The Responses request schema already accepts `NamespaceTool`, but
`get_developer_message()` rejected it. The Harmony output adapters also omitted
the Responses `namespace` field, and history replay assumed `functions.<name>`.
The normal, non-Harmony Responses path's `namespace__name` mapping did not
repair these separate Harmony adapters.

`openai_harmony.DeveloperContent.with_tools(ToolNamespaceConfig(...))` supports
native namespaces. The patch uses that representation, preserving namespace
descriptions, function names/descriptions, and JSON schemas without flattening.
An exact request-local mapping resolves `namespace.function` recipients to
Responses `{type: "function_call", namespace: "namespace", name: "function"}`.
This avoids guessing from `__` separators in MCP tool names and preserves
ordinary function names containing punctuation. Both streamed item-added and
item-done events carry namespace; argument events and call IDs retain their
existing lifecycle. History replay uses namespace-qualified recipients and tool
authors. Reasoning channel handling is unchanged.

The local capture used the actual installed Codex CLI 0.162.1, pointed at a
disposable loopback HTTP server. It saved only tool declarations in
`codex-tools.json` locally; raw captures are not committed. Regression tests use
`codex-tools.sanitized.json`, a small representative request-shape fixture with
no account-specific tool catalog. No authorization headers or conversation text were saved.
Captured namespaces included `multi_agent_v1` and `mcp__codex_apps__*`, containing
multiple function definitions. Shell tools were ordinary functions in this
configuration. The capture intentionally returns HTTP 400 after recording;
it is a request-shape diagnostic, not a model execution test.

## Web search capability fix

Actual Codex 0.162.1 request shapes are summarized in `codex-web-search.sanitized.json`:

- `cached`: `{"type":"web_search","external_web_access":false}`.
- `live`: `{"type":"web_search","external_web_access":true}`.
- `disabled`: no Web search declaration; the same function and namespace tools
  remain available.

The SDK/request union parses modern Web search, but Harmony previously routed
only `web_search_preview` to the browser execution loop. The patch accepts live
`web_search` and its versioned alias when a server-side browser is configured.
Harmony-only routing reuses the existing browser prompt, MCP execution loop,
tool-result messages, and Responses `web_search_call`/SSE generation. The actual
request is preserved. Non-Harmony tool-type routing is unchanged.

Offline/cache-only access, domain filters, location targeting and non-default
context-size options cannot be enforced by this browser and remain explicit
errors. Cached requests are never silently converted to live searches.

Stateless Codex resends completed `web_search_call` items on later requests.
Harmony now preserves their action/ID metadata as historical commentary without
re-executing the search or fabricating retrieved text. Hosted search output items
do not contain that retrieved text. Stateful Responses history keeps the original
browser tool messages/results. Incomplete hosted actions are rejected on replay.

A Playwright-backed MCP service is provided in `browser-search/`. It performs
real live searches and page reading without an Exa API key. See that directory's
README for installation and for adding `--tool-server 127.0.0.1:8765` to the
existing GPT-OSS launch command. Keep all other model/server/parser options.

`codex-gptoss.py` in the project root launches the original Codex binary with
live Web search enabled and the given existing vLLM provider:

```bash
export GPTOSS_BASE_URL=http://YOUR_EXISTING_SERVER:8000/v1
# If required, set GPTOSS_API_KEY in the environment; no OpenAI key is borrowed.
# If the server uses an alias, set GPTOSS_MODEL to its served model name.
.pixi/envs/default/bin/python codex-gptoss.py
```

It forwards normal CLI arguments and retains function/namespace tools. It does
not modify global Codex config. `GPTOSS_WEB_SEARCH` selects its search mode,
defaulting to `live`. An existing Codex provider/profile can instead use
`-c 'web_search="live"'`, or set `web_search = "live"` in its active profile.

Official references:
https://developers.openai.com/api/reference/resources/responses/methods/create
https://developers.openai.com/api/docs/guides/tools-web-search
https://learn.chatgpt.com/docs/config-file/config-basic

## Apply after reinstalling

From the project directory, with a fresh vLLM **0.31.0** installation:

```bash
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/apply_patch.py
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/test_namespace.py
```

The application script verifies version and exact source content, performs a
dry run, and saves adjacent `.before-namespace` backups before applying the
unified diff. It refuses an already patched or divergent installation.
Restart the existing server with its existing launch command to load changes.
Do not start an additional 120B instance. Originals for this initial patch
are in `original/vllm/`; these may be copied back to the corresponding package
paths to undo it, after checking for intervening edits.

The standalone reusable diff is `vllm-0.31.0-namespace.patch`. It uses `-p1`
relative to `site-packages`. `make_patch.py` regenerates it from saved originals
and installed files.

## Validation and limits

Run the standard-library regression suite using the commands above; pytest
is not installed in this environment. Coverage includes existing functions,
native namespaces/multiple children, captured Codex schemas, JSON arguments,
tool-result and assistant-response round trips, reasoning plus calls,
streaming namespace/ID preservation, separator-containing names, and explicit
validation failures. These tests exercise the installed code without mocking
vLLM/Harmony conversion functions.

Initial inspection had no running model. Subsequent tests against the existing
GPT-OSS instance completed real shell/file-edit round trips and browser searches;
see `RESULTS.md` and `../../responses-proxy/RESULTS.md` for the scope and evidence.
The later seven-agent configuration is tested offline, without starting a model.
Model tool-selection reliability is not guaranteed by protocol regression tests.

The unchanged Codex CLI was also run against a disposable scripted Responses
server using the installed vLLM input/output and SSE adapters. It executed
three shell calls, edited a temporary file, returned the tool results, and
quoted a random token learned from those results in its final answer. This
client integration test passed; it does not claim to test GPT-OSS inference
or the interactive TUI. To reproduce:

```bash
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/test_codex_roundtrip.py
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/test_codex_roundtrip.py --live-browser
```

For the already-running real server, set `GPTOSS_BASE_URL` (and authentication
and model alias as needed) and run:

```bash
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/live_roundtrip.py
```

This test first checks `/models`, uses real inference through Codex's exec
engine shared with the TUI, edits only a fresh temporary fixture, and asserts
successful shell calls, the changed file, and an answer using its secret second
line. It preserves JSON event logs and the final result under the reported
temporary directory. It never starts a server. Interactive TUI verification
still requires running `codex-gptoss.py` against that same real endpoint.

The following remain explicit errors rather than silently dropped tools:

- Namespace children of type `custom` (including a free-form grammar-based
  `apply_patch` if configured). This patch supports function children; shell
  based file reading/editing uses those same JSON function calls.
- Cache-only Web search, domain/location filters, and non-default context sizes.
  Live Web search requires an available browser MCP tool; unavailable backends
  fail explicitly. Browser CAPTCHA/access restrictions can cause live searches
  to fail. The model receives the failure text rather than invented results.
- Namespace names `browser`, `python`, `container`, or containing a dot,
  which conflict with Harmony routing; duplicate namespaces are rejected.
- A native `functions` namespace together with top-level function tools,
  which would occupy the same Harmony namespace, is rejected explicitly.

To recapture current Codex tools (Web search disabled for compatibility):

```bash
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/capture_codex.py
```

For a live check, launch the existing Codex TUI/provider configuration with
Web search set to live, request a search and a shell command followed by reading and
editing a disposable project file, and then ask a follow-up question. Inspect
the returned SSE items for matching `namespace`, `name`, `call_id`, and JSON
arguments. This live check was not claimed as passing.
