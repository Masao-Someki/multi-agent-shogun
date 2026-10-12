# Remote vLLM worker profile

The `vllm-workers` model profile routes Ashigaru 1–10, Tanya and Tanya2 to
remote OpenAI-compatible vLLM endpoints through Codex, in a 4x4 grid of 16
panes. Shogun, Karo, Metsuke, Kumigashira and Gunshi keep the CLI and model
configured in `config/settings.yaml`.

The vLLM server can use any model supported by the installed vLLM build. Set
its served name to `shogun-worker`, or export the exact ID reported by
`GET /v1/models` as `VLLM_MODEL_ID` on the Shogun host.

## 1. Make an OpenAI-compatible model endpoint available

The Shogun Pixi environment does not install or start a model server. Make the
OpenAI-compatible endpoint available to the GPU node where Shogun will run.
Use the cluster's existing model service or a separately managed vLLM
environment, and note its `/v1` URL, model ID, and inference-only API key.

## 2. Configure endpoint access from the GPU node

If the endpoint is on the same node, use its loopback URL. For a remote Babel
compute-node endpoint, create a tunnel from the GPU node or use the cluster's
protected gateway. The endpoint URL must be reachable from the GPU node where
Shogun runs.

```bash
export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
export VLLM_MODEL_ID="shogun-worker"
read -rs VLLM_API_KEY
export VLLM_API_KEY
```

If the endpoint is remote, replace these values with its reachable URL, served
model ID, and key. Do not expose an unauthenticated model server to the public
internet.

### Two servers (one per GPU)

With two GPUs, run one server per GPU instead of one large server:

```bash
CUDA_VISIBLE_DEVICES=0 vllm serve <model> --served-model-name shogun-worker --port 8000 ...
CUDA_VISIBLE_DEVICES=1 vllm serve <model> --served-model-name shogun-worker --port 8001 ...
export VLLM_BASE_URL_2="http://127.0.0.1:8001/v1"
```

Each worker is pinned to one server so that server's prefix cache keeps
hitting: Ashigaru 1, 3, 5, 7, 9 and Tanya use `VLLM_BASE_URL`; Ashigaru 2, 4,
6, 8, 10 and Tanya2 use `VLLM_BASE_URL_2`. Six workers go to each server, so
give each server at least six parallel sequences (`--max-num-seqs`). If
`VLLM_BASE_URL_2` is unset, every worker uses `VLLM_BASE_URL`; that single
server then needs at least twelve. Both servers must serve the same model ID
and accept the same `VLLM_API_KEY`.

## 3. Verify endpoint access

Verify that the endpoint, authentication, and served model name are correct:

```bash
curl --fail-with-body --max-time 10 \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  "${VLLM_BASE_URL}/models"
```

The response should include an entry whose `id` is `shogun-worker`. If you
change `--served-model-name`, set `VLLM_MODEL_ID` to the new ID. The profile
requires `VLLM_API_KEY` and sends it as a bearer token, matching the server's
`--api-key` value.

## 4. Launch Shogun on the GPU node

The Pixi environment includes the Linux runtime tools for the Shogun formation
and bootstraps Codex CLI and Claude Code into the local Pixi workspace on first
launch. From the repository root on the GPU node, run:

```bash
cd gpu-vllm
pixi run start
```

Set `VLLM_API_KEY` before starting. The Pixi environment does not install the
vLLM Python server; it starts the Shogun system and routes the worker agents to
the configured OpenAI-compatible endpoint.

The profile configures Codex to use the `vllm` provider with `VLLM_MODEL_ID`,
`VLLM_BASE_URL`, and `VLLM_API_KEY`. It sets the context window to 131,072
tokens and the maximum output to 32,000 tokens. The server's
`--max-model-len` must be at least 131,072 for requests to use the full context.

Use a dedicated inference-only key. Codex worker processes receive this key
in their environment, which a worker can inspect; never reuse Git, cluster, or
cloud credentials. The profile does not install vLLM, request GPU allocations,
start the server, or change the configured CLI/model for Shogun, Karo, or
Gunshi.

References: [vLLM Qwen2.5 tool-calling guidance](https://docs.vllm.ai/en/stable/features/tool_calling/),
[Qwen2.5-Coder-7B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct),
[vLLM OpenAI-compatible server security note](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/).
