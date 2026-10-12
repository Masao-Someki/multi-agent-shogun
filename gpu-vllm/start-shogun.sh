#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NPM_PREFIX="$SCRIPT_DIR/.pixi/npm"
export PATH="$SCRIPT_DIR/bin:$NPM_PREFIX/node_modules/.bin:$PATH"
PIXI_SITE_PACKAGES="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
export PYTHONPATH="$PIXI_SITE_PACKAGES${PYTHONPATH:+:$PYTHONPATH}"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This Pixi environment is intended for a Linux GPU node." >&2
    exit 1
fi

if [[ ! -x "$NPM_PREFIX/node_modules/.bin/codex" || ! -x "$NPM_PREFIX/node_modules/.bin/claude" ]]; then
    echo "Installing the Shogun agent CLIs into the local Pixi workspace..."
    npm install --prefix "$NPM_PREFIX" --no-audit --no-fund \
        @openai/codex @anthropic-ai/claude-code
fi

tmux set-environment -g PATH "$PATH" 2>/dev/null || true
exec "$REPO_ROOT/shutsujin_departure.sh" --model-profile vllm-workers "$@"
