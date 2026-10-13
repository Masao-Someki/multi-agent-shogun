# Playwright browser service for GPT-OSS

Provides native `browser.search`, `browser.open`, and `browser.find` through
vLLM's existing MCP integration. Runs independently of the model and uses no GPU.
Node.js and MCP are supplied by the existing Pixi environment. Playwright 1.64.0
and its matching headless Chromium are installed locally in this directory.

Start on the **same host as the vLLM API server**:

```bash
.pixi/envs/default/bin/python browser-search/server.py
```

The service listens only on `127.0.0.1:8765`, using SSE at `/sse`. Its MCP server
name is `browser`, as required by vLLM's native Harmony browser execution path.
Add this one option to the existing GPT-OSS vLLM launch command, keeping the
existing model, ports, parsers and all other options:

```text
--tool-server 127.0.0.1:8765
```

Restart that existing server to load the installed compatibility patch and
register the browser. Do not start an extra GPT-OSS model instance. Existing
tool-server URLs can be retained in vLLM's comma-separated tool-server list.

Use Codex with `-c 'web_search="live"'`, or the project's `codex-gptoss.py`
launcher, which now defaults to live search. Cached/offline searches cannot be
supplied by this live browser. Unsupported search options remain explicit errors.

Search uses DuckDuckGo HTML, falling back to Bing if access is blocked or no
usable results are returned. Results contain actual titles, source URLs,
snippets, and cursors. Bing/DuckDuckGo redirect URLs are decoded when possible.
Opening a source returns its actual title and numbered body text. Find searches
retrieved text literally. Search-engine relevance and bot restrictions remain
external dependencies; failed access returns an error, not fabricated results.
This does not implement OpenAI's hosted search index or citation annotations.

Browser pages are fresh for each operation. Retained source/cursor metadata is
bounded and in memory. Restarting this service invalidates old cursors; original
URLs can still be used. No searches modify model weights or the Codex binary.

`open` and `find` accept an actual source URL, an integer/string cursor,
`cursor:<number>`, or a returned `ref_id`. Search also returns `search_ref`
aliases such as `turn0search0`; these are scoped to the current MCP session so
different workers cannot accidentally resolve one another's aliases. Opaque
`browser:<run>:<number>` references identify their server run and reject stale
references after a restart. Prefer URLs across conversations/restarts.
Missing/unknown/expired/conflicting references return actionable MCP `ToolError`
results, not generic `UnexpectedToolError` crashes. No unknown reference is
silently replaced with a guessed or unrelated page.

Run reference regression tests without making Web requests:

```bash
.pixi/envs/default/bin/python browser-search/test_references.py
.pixi/envs/default/bin/python browser-search/test_live_references.py
```

Reinstall the Node dependency and matching browser from the project root:

```bash
pixi run npm ci --prefix browser-search --ignore-scripts
PLAYWRIGHT_BROWSERS_PATH="$PWD/browser-search/browsers" pixi run node browser-search/node_modules/playwright/cli.js install chromium --only-shell
```

Verify while the service is running:

```bash
.pixi/envs/default/bin/python browser-search/test_browser.py
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/test_codex_roundtrip.py --live-browser
```

The first test makes real browser requests through vLLM's actual MCP/Harmony
adapters. The second runs the actual Codex client with a real browser search and
scripted model responses, checking that search history can be replayed before
shell execution/file editing continues. Neither test claims GPT-OSS inference or
interactive TUI validation; that requires the existing GPT-OSS API endpoint.
