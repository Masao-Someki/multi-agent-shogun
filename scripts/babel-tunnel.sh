#!/usr/bin/env bash
# Foreground tunnel; browser MCP remains private on the allocation node.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo 'Usage: bash scripts/babel-tunnel.sh ALLOCATION_NODE [LOCAL_PORT]' >&2
    exit 2
fi
node=$1
port=${2:-8003}
[[ "$node" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || { echo 'Invalid allocation hostname' >&2; exit 2; }
[[ "$port" =~ ^[0-9]+$ ]] && (( port > 0 && port < 65536 )) || { echo 'Invalid local port' >&2; exit 2; }
login=${BABEL_SSH_LOGIN:-msomeki@login.babel.cs.cmu.edu}
echo "Worker URL: http://127.0.0.1:$port/v1 (keep this tunnel open)" >&2
exec ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 -J "$login" \
    -L "127.0.0.1:$port:127.0.0.1:8003" "${BABEL_SSH_USER:-msomeki}@$node"
