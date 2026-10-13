#!/usr/bin/env bash
#set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
key_file=${VLLM_KEY_FILE:-$HOME/vllm.key}
if [[ -f "$key_file" ]]; then
    set -a
    if ! source "$key_file"; then
        echo "Could not load key file: $key_file" >&2
        exit 1
    fi
    set +a
fi
export HF_HOME=${HF_HOME:-$PWD/hub}
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-$PWD/browser-search/browsers}
python_bin=${VLLM_PYTHON:-$PWD/.pixi/envs/default/bin/python}
vllm_bin=${VLLM_BIN:-$(dirname -- "$python_bin")/vllm}

if [[ ${1:-} == --dry-run ]]; then
    exec "$python_bin" "$PWD/service_stack.py" --dry-run
fi
if (($#)); then
    echo 'Usage: bash start-vllm.sh [--dry-run]' >&2
    exit 2
fi
if [[ -z ${VLLM_API_KEY:-} || $VLLM_API_KEY == REPLACE_* ]]; then
    echo 'Set VLLM_API_KEY in ~/vllm.key before startup.' >&2
    exit 1
fi

# Start only the two lightweight sidecars asynchronously. Keep vLLM in this
# foreground process so Slurm owns its lifetime and streams its startup logs.
if ! "$python_bin" "$PWD/service_stack.py" --start-sidecars; then
    echo 'Browser MCP/proxy startup failed; vLLM was not started.' >&2
    exit 1
fi
exec "$vllm_bin" serve openai/gpt-oss-120b \
    --served-model-name shogun-worker \
    --host 127.0.0.1 --port 8000 \
    --tensor-parallel-size 2 \
    --max-model-len 131072 \
    --max-num-seqs 4 \
    --max-num-batched-tokens 4096 \
    --gpu-memory-utilization 0.95 \
    --enable-prefix-caching \
    --kv-cache-dtype fp8 \
    --enable-auto-tool-choice \
    --tool-call-parser openai \
    --reasoning-parser openai_gptoss \
    --async-scheduling \
    --cudagraph-capture-sizes 1 \
    --tool-server 127.0.0.1:8765
