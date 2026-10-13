# Verification — 2026-10-13 (namespace + live Playwright Web search)

- Installed versions: vLLM 0.31.0; codex-cli 0.162.1; Python 3.12.
- `python test_namespace.py`: 18 tests passed, 0 failures, 0 skips (0.032 s).
- Actual CLI request capture: passed; fixture includes top-level functions and
  multiple function namespaces; Web search disabled explicitly for this capture.
- Unified patch forward dry run against saved originals: passed for all 6 files.
- Unified patch reverse dry run against patched installation: passed for all 6 files.
- Original sources saved before mutation in `original/vllm/`.
- Playwright 1.64.0 (2 Node packages) and its matching headless Chromium were
  installed under `browser-search/`. No Python dependency upgrades, model starts,
  weight changes, or changes to existing server/parser configuration performed.
- Live GPT-OSS/Codex execution: not run; no vLLM process or API listener found
  on the current host or the active allocation node `babel-x9-32`.
- Actual Codex Web search request captures: cached=false external access,
  live=true external access, disabled=no search tool; function/namespace lists
  were identical across all three modes. Records in `codex-web-search.json`.
- Modern live-search/browser routing, unavailable-browser rejection, unsupported
  cache/filter option rejection, and history reuse validation passed. Ordinary
  non-Harmony routing and original request objects remain unchanged.
- Real Codex CLI integration with scripted inference and installed vLLM
  adapters: passed. Three successful shell calls, file edit, tool-result replay,
  and answer using a random token obtained from the result. Logs retained at
  `/tmp/codex-gptoss-roundtrip-i75b2lxr`. This is not a live GPT-OSS or TUI test.
- Real Playwright search/open/find via the installed vLLM MCP/Harmony adapters:
  passed. Actual search results carried titles, decoded source URLs and snippets;
  page reading and text finding passed; unknown cursors produced explicit errors.
- Real Codex + real Playwright search + scripted inference: passed. Codex accepted
  native Web search SSE events, replayed search history, and continued with three
  successful shell calls, file editing, and a final answer consuming a shell
  result. Logs at `/tmp/codex-gptoss-roundtrip-yfffl1nz`.
- A live browser MCP service is running at `127.0.0.1:8765`; the GPT-OSS server
  must register it via `--tool-server 127.0.0.1:8765` on the same host.

Regression cases:

1. Captured Codex namespace definitions and each child function's output identity.
2. Existing ordinary function tools.
3. Existing dotted function names remain ordinary function names.
4. JSON arguments and namespace-qualified tool-result/history round trips.
5. Missing call IDs remain validation errors.
6. Multiple functions and descriptions/schemas in a namespace.
7. Namespace and function names containing `__` remain reversible.
8. Analysis/reasoning and tool calling together.
9. Conflicting/reserved namespace validation.
10. Streaming dispatcher, namespace fields, arguments, and ID consistency.
11. Unsupported custom children explicitly rejected.
12. Modern live Web search and versioned alias with available browser; explicit
    cache-only and unavailable-browser errors.
13. Legacy Web search requires a configured browser capability.
14. Search validation occurs before history reuse, returns HTTP 400 param=tools,
    and preserves the complete request.
15. Actual Codex cached/live/disabled request declarations and retained tools.
16. Modern browser routing is Harmony-only; original request fields preserved.
17. Unsupported filters/location/context-size options are not silently ignored.
18. Completed Web search history preserves metadata without another search;
    incomplete hosted actions remain explicit errors.
