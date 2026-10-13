# Verification (2026-10-13)

- Proxy regression: 16 passed, zero failures/skips.
- Browser reference regression: 10 passed, zero failures/skips.
- Existing vLLM process and model weights were retained. No new Python
  dependencies or additional model instance were installed/started.
- Actual Codex CLI 0.162.1, actual GPT-OSS-120B (`shogun-worker`), actual browser:
  capability query performed Web search and returned success; scientific query
  performed search/open and returned literature references. No browser tool
  names were executed as shell commands in those checks.
- Actual shell/file round trip through proxy :8003 passed: four successful shell
  executions, changed temporary fixture, preserved random second line, and final
  answer using that line. Artifacts: `/tmp/codex-gptoss-roundtrip-rjlp1fhq`.
- Mac testing exposed an unknown browser cursor. The old implementation raised
  ValueError, which MCP 2.3.0 wrapped as UnexpectedToolError and hid the actionable
  message. Expected failures now use ToolError. Reference normalization covers
  URLs, integer/string cursors, prefixed and returned references, and session
  aliases without guessing missing references.
- Tool-free compaction requests previously received an unintended added browser
  capability. The proxy now leaves these requests tool-free and guidance-free.
- Original browser server saved as `browser-search/server.py.before-cursor-fix`;
  the user's existing search debug prints were preserved.
- Actual MCP wire check on the temporary updated server :8766 passed:
  search → open via `turn0search0` → find via returned opaque reference; omitted,
  unknown and restart-stale references all returned actionable errors.
- MCP 2.3.0 creates a new ServerSession wrapper per request. Alias state is keyed
  by the stable HTTP session or underlying connection, not that transient wrapper.
