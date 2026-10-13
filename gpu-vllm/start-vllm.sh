#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
key_file=${VLLM_KEY_FILE:-$HOME/vllm.key}
if [[ -f "$key_file" ]]; then
    set -a
    source "$key_file"
    set +a
fi
export HF_HOME=${HF_HOME:-$PWD/hub}
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-$PWD/browser-search/browsers}
exec "${VLLM_PYTHON:-$PWD/.pixi/envs/default/bin/python}" "$PWD/service_stack.py" "$@"
