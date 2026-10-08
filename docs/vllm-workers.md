# Remote vLLM worker profile

The `vllm-workers` model profile routes Ashigaru 1–3, Tanya, and Metsuke to a
remote OpenAI-compatible vLLM endpoint through OpenCode. Shogun, Karo, and
Gunshi keep the CLI and model configured in `config/settings.yaml`.

This guide starts with one allocated NVIDIA L40S and
`Qwen/Qwen2.5-Coder-7B-Instruct`. The model card documents vLLM serving, and
vLLM documents the `hermes` parser for Qwen2.5 tool calls. The chosen served
name is `shogun-worker`; the launcher must use that exact API model ID.

## 1. Start vLLM on the allocated L40S

Run these commands in a shell on the allocated GPU node. Install the
[Pixi CLI](https://pixi.sh/latest/installation/) on that Linux host first if it
is not already available. Pixi creates the Python environment and installs
vLLM on its first run, choosing the PyTorch CUDA backend from the installed
NVIDIA driver. Replace the SSH host and user in the next section with the
cluster's allocated compute-node address and your account.

```bash
export VLLM_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf 'Copy this inference-only key to the Shogun host: %s\n' "$VLLM_API_KEY"
cd gpu-vllm
pixi run start
```

`pixi run start` resolves and installs the Linux environment, installs vLLM
with `uv` if needed, then starts the server. The Pixi workspace and lock file
are isolated under `gpu-vllm/`, so the Mac Shogun host does not try to install
CUDA or vLLM. The server binds to loopback; keep this process running while
using the workers. If the model fails to start or leaves too little cache for
your workload, lower `--max-model-len` in `gpu-vllm/start-vllm.sh` and set the
same value for `limit.context` in `config/opencode-vllm.json`.

## 2. Forward the endpoint to the Shogun host

For Babel, where your laptop authenticates to the login node and the login node
has passwordless SSH access to the allocated compute node, run this on the
Shogun host and leave it running. Replace only the compute-node placeholder;
that node name must resolve from the login node:

```bash
ssh -t -o ExitOnForwardFailure=yes \
  -L 8000:127.0.0.1:8001 \
  msomeki@login.babel.cs.cmu.edu \
  'ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8001:127.0.0.1:8000 <allocated-compute-host>'
```

Enter your login password at SSH's hidden prompt. The password is not saved in
shell history or a file. The nested SSH runs from the login node to the compute
node, so it uses Babel's passwordless inter-node access. This creates the path
laptop `localhost:8000` → login `localhost:8001` → compute `localhost:8000`,
where vLLM is bound. If the nested connection asks for a compute-node password,
verify the host name and test `ssh <allocated-compute-host>` from an interactive
login-node shell first.

Do not put the password in this command or a plaintext file. `sshpass` is not
needed for this interactive tunnel; SSH prompts for the login password itself.

The simpler `ssh -J` form authenticates both SSH hops using keys available to
the laptop's SSH client. Use it only if your local SSH key is configured for
the compute node, as described in the [Babel HPC guide](https://www.lti.cmu.edu/misc-pages/hpc1/hpc-guide.html#connecting-to-a-compute-node).

If the cluster provides an authenticated private HTTPS gateway instead, use
that gateway's `/v1` URL and skip the SSH tunnel. Do not expose an unauthenticated
vLLM server to the public internet. vLLM's `--api-key`/`VLLM_API_KEY` does not
authenticate every server endpoint, so keep the server loopback-bound or behind
a protected gateway.

## 3. Configure and verify the Shogun host

In a third terminal on the Shogun host, from the repository root, set the
endpoint and model ID. Paste the inference-only key printed in step 1 when
prompted; `read` does not put it in shell history.

```bash
export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
export VLLM_MODEL_ID="shogun-worker"
read -rs VLLM_API_KEY
export VLLM_API_KEY
```

Verify that the tunnel, authentication, and served model name are correct:

```bash
curl --fail-with-body --max-time 10 \
  -H "Authorization: Bearer ${VLLM_API_KEY}" \
  "${VLLM_BASE_URL}/models"
```

The response should include an entry whose `id` is `shogun-worker`. If you
change `--served-model-name`, set `VLLM_MODEL_ID` to the new ID. For a private
endpoint without API-key authentication, leave `VLLM_API_KEY` unset and omit
the `Authorization` header from the curl command.

## 4. Launch the worker profile

Install and authenticate OpenCode on the Shogun host if it is not already
available, then start the formation from the repository root:

```bash
./shutsujin_departure.sh --model-profile vllm-workers
```

The profile uses the OpenCode provider alias `vllm/worker`; the provider config
maps it to `VLLM_MODEL_ID`. Its context and output limits are 32,768 and 8,192
tokens. The server's `--max-model-len` must be at least the configured context
limit.

Use a dedicated inference-only key. OpenCode worker processes receive this key
in their environment, which a worker can inspect; never reuse Git, cluster, or
cloud credentials. The profile does not install vLLM, request GPU allocations,
start the server, or change the configured CLI/model for Shogun, Karo, or
Gunshi.

References: [vLLM Qwen2.5 tool-calling guidance](https://docs.vllm.ai/en/stable/features/tool_calling/),
[Qwen2.5-Coder-7B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct),
[vLLM OpenAI-compatible server security note](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/).
