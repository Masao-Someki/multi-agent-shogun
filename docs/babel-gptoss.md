# Babel GPT-OSS service stack and seven-agent default

The default formation talks directly to Karo (Codex gpt-6-luna medium). Ashigaru 1–3
and Tanya use Codex with GPT-OSS medium through Babel; Metsuke uses Claude Opus
medium; Gunshi uses Fable high. There is no default Shogun or Kumigashira.
Gunshi still directs Tanya. The worker host needs access only to the Babel API;
the browser and its Internet access remain on Babel.

## Babel setup (once, on the allocated GPU node)

The existing Pixi Python environment must contain vLLM 0.31.0 and MCP 2.x.
The launcher does not install/upgrade Python packages or request GPUs. Its
existing GPT-OSS configuration requires two suitable GPUs; no model is started
by installation or the offline tests.

```bash
cd /data/user_data/msomeki/30_shared/multi-agent-shogun/gpu-vllm
pixi install
pixi run npm ci --prefix browser-search --ignore-scripts
PLAYWRIGHT_BROWSERS_PATH="$PWD/browser-search/browsers" \
  pixi run node browser-search/node_modules/playwright/cli.js install chromium --only-shell
```

Create `~/vllm.key` using `gpu-vllm/vllm.key.example` only if it does not exist;
fill `export HF_TOKEN=` and `export VLLM_API_KEY=` locally and set its mode to
600. Never commit this file. Use a dedicated inference key, not a commercial
OpenAI key. The client `SHOGUN_VLLM_API_KEY` must equal `VLLM_API_KEY`.

The installed `~/start-vllm.sh` forwards to the repository script. After moving
the repository, override its path; if the wrapper is missing, call the repository
script directly:

```bash
export SHOGUN_GPU_VLLM_DIR=/path/to/multi-agent-shogun/gpu-vllm
bash "$SHOGUN_GPU_VLLM_DIR/start-vllm.sh" --dry-run
```

The wrapper sources `~/vllm.key` (override with `VLLM_KEY_FILE`) and selects the
Pixi Python interpreter (override with `VLLM_PYTHON`). `HF_HOME` defaults to
`gpu-vllm/hub`; Playwright downloads stay in `browser-search/browsers`.

## Start later, when the GPU allocation is ready

```bash
bash ~/start-vllm.sh --dry-run  # print configuration; no service or GPU access
bash ~/start-vllm.sh           # foreground supervisor, background children
```

The supervisor starts browser MCP on loopback 8765, GPT-OSS on loopback 8000,
then the Responses proxy on loopback 8003. It keeps the existing model alias
`shogun-worker`, TP=2, context=131072, openai tool parser, openai_gptoss reasoning
parser and inference tuning. vLLM receives authentication via `VLLM_API_KEY`;
the key is not printed or placed in the process command line.

The exact vLLM 0.31.0 namespace/Web-search compatibility patch is applied with
backups before a new model process starts. A previously applied patch passes a
reverse dry-run check; different versions/source fail rather than being blindly
patched. For manual reapplication after reinstalling vLLM:

```bash
.pixi/envs/default/bin/python patches/vllm-0.31.0-namespace/apply_patch.py
```

Ready existing services are adopted, not restarted. An occupied but unhealthy
port causes an error rather than a duplicate 120B instance. On exit only child
processes created by this supervisor are stopped; adopted services remain.
Use Ctrl-C or the scheduler's normal job shutdown. Logs and the singleton lock
are under `gpu-vllm/.service-state` (`VLLM_STATE_DIR` override). Do not run a
second supervisor with another state directory against the same ports.
The maximum model readiness wait defaults to 1800 seconds and is configurable
with `--ready-timeout`. A foreground supervisor is intended for a scheduler job
or a persistent terminal, not an untracked `nohup` model process.

## Worker/Mac connection

On the worker host, keep this tunnel in a separate terminal. Replace the node
with the current allocation; do not hard-code an old allocation hostname:

```bash
bash scripts/babel-tunnel.sh babel-m5-28       # worker default local port 8003
# Or on the Mac:
bash scripts/babel-tunnel.sh babel-m5-28 32424
```

The helper uses the Babel login node as SSH jump host. It exposes only the
authenticated proxy, not browser MCP or the raw model API. Standard SSH keys
or interactive password authentication work; there is no embedded password.
Override `BABEL_SSH_LOGIN` or `BABEL_SSH_USER` for a different account.

In the terminal that launches the formation:

```bash
export SHOGUN_VLLM_BASE_URL=http://127.0.0.1:8003/v1
# Mac with the 32424 tunnel: export SHOGUN_VLLM_BASE_URL=http://127.0.0.1:32424/v1
read -rs SHOGUN_VLLM_API_KEY; export SHOGUN_VLLM_API_KEY
curl --fail --max-time 10 -H "Authorization: Bearer $SHOGUN_VLLM_API_KEY" \
  "$SHOGUN_VLLM_BASE_URL/models"
bash shutsujin_departure.sh
```

The `/models` response must contain `shogun-worker`. Do not point Codex at raw
8000/32423: the proxy on 8003/32424 supplies the server-search compatibility
policy. The Codex adapter configures the Responses wire API, context 131072,
auto-compaction 110000, medium reasoning and live Web search for GPT-OSS roles.
No commercial Codex credentials are reused as the inference key.

## Offline verification

```bash
cd gpu-vllm
.pixi/envs/default/bin/python test_service_stack.py
bash -n start-vllm.sh ../scripts/babel-tunnel.sh ~/start-vllm.sh
bash start-vllm.sh --dry-run
```

These tests cover safe adoption, unhealthy-port refusal, cleanup of owned
children, failure handling, dry-run without keys/GPUs, key preflight and exact
vLLM version gating. They do not claim a live model/TUI test. Earlier live
round-trip results and proxy limitations are recorded in
`gpu-vllm/responses-proxy/RESULTS.md`. Search-engine access may be blocked;
live Playwright search is not OpenAI's hosted cached search/index and unsupported
cache/filter semantics produce explicit errors rather than dropped tools.
The tunnel tests also check the exact proxy-only forwarding target and reject
invalid hostnames/ports without attempting SSH.
