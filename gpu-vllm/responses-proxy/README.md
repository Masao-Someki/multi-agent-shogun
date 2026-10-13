# Babel Responses proxy

Routes live Web research through vLLM's server-side browser MCP and removes only
the conflicting Codex Apps search function from model-visible tool declarations.
The installed aiohttp dependency is used; no dependency installation is required.

```text
Codex → SSH/API → proxy :33987 → vLLM :8000 → browser MCP :8765 → Web
```

Start on the same Babel node as vLLM:

```bash
.pixi/envs/default/bin/python responses-proxy/proxy.py
```

The default upstream is `http://127.0.0.1:8000`. The proxy listens only on
`127.0.0.1:33987`. It forwards the incoming Authorization header; it neither
stores nor substitutes an API key. vLLM must already have its browser MCP
registered. No extra model instance is started.

For the current `babel-m5-28` allocation, a separate Mac tunnel is:

```bash
sshpass -f .babel_pass ssh -tt \
  -o ExitOnForwardFailure=yes \
  -L 32424:127.0.0.1:38003 \
  msomeki@login.babel.cs.cmu.edu \
  'ssh -N \
    -o ExitOnForwardFailure=yes \
    -L 127.0.0.1:38003:127.0.0.1:33987 \
    babel-m5-28'
```

Keep that terminal open. Change only Codex's provider URL to
`http://127.0.0.1:32424/v1`, retain `web_search="live"`, and start a fresh
conversation. The proxy supplies browser guidance, so the previous
`developer_instructions` override is unnecessary. Point the SSH tunnel at the
actual allocation node after a node change.

## Policy and transport

- Removes only `_web_run` in `mcp__codex_apps__search_service`, or its explicitly
  qualified flat-function equivalent. Other functions, schemas, descriptions,
  namespaces and other children in the same namespace are preserved.
- Retains an existing `web_search`/preview declaration with all options intact.
  If it replaces the client search function and no server Web tool was declared,
  it adds `web_search_preview`. `--server-tool web_search` changes that default.
- Tool-free requests, including Codex's context-compaction requests, receive no
  search tool or guidance. `tool_choice="none"` is respected. A named/allowed
  choice referring to a removed search function is rejected explicitly instead
  of silently broadened.
- Adds one developer input message describing native browser calls, separating
  them from shell commands and local sandbox networking. Original input items
  remain intact and ordered; original instructions and all other request fields
  are preserved. `--no-guidance` disables this additional message.
- Preserves call/response IDs, arguments, namespace fields, previous_response_id,
  storage flags, metadata, query encoding and upstream HTTP errors.
- Relays response bytes incrementally, including SSE and compressed responses.
  Handles concurrent requests and closes upstream streams on client cancellation.
- Policy audit logs contain removed tool identities and counts, not credentials,
  user text, arguments, page contents or model reasoning.

Request bodies may use identity/gzip/deflate encoding. Other encodings receive an
explicit 415; they are not forwarded around the filtering policy. Request size
is limited to 16 MiB. Non-Responses routes are forwarded without applying policy.
Web search offline/cache/filter limitations remain the upstream's explicit
capability errors; the proxy does not convert cached searches to live access.

## Verification

```bash
.pixi/envs/default/bin/python responses-proxy/test_proxy.py
.pixi/envs/default/bin/python browser-search/test_references.py
```

The proxy suite covers tool filtering, preserved state/IDs, choices, compaction,
gzip, upstream errors, SSE byte identity/incremental delivery, concurrent clients,
and cancellation. The browser suite covers reference forms, per-session aliases,
cache eviction, restart-stale references and actionable errors.

Actual Codex CLI 0.162.1 + GPT-OSS-120B tests through this proxy successfully
performed search/open and local shell/file-edit round trips. The Mac TUI test
also exposed model-dependent calling errors and a cursor error, which motivated
the reference fix. An instruction is not a hard guarantee about model behavior;
the proxy does not reinterpret ordinary assistant JSON as an executable call,
rewrite shell commands into searches, or verify every factual claim/citation.
