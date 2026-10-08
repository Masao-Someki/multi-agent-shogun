#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This Pixi environment is for the remote Linux GPU host." >&2
    exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA driver tools were not found; run this on the allocated GPU node." >&2
    exit 1
fi
if [[ -z "${VLLM_API_KEY:-}" ]]; then
    echo "Set VLLM_API_KEY before starting the server." >&2
    exit 1
fi

if ! python -c 'import vllm' >/dev/null 2>&1; then
    echo "Installing vLLM with the CUDA backend selected from the host driver..."
    uv pip install --python "$CONDA_PREFIX/bin/python" vllm --torch-backend=auto
fi

exec vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
    --served-model-name shogun-worker \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.90 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes
