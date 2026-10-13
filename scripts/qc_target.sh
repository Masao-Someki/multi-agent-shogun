#!/usr/bin/env bash
# Resolve the completion QC recipient using the same effective formation as launch.
set -euo pipefail
registry_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$registry_root/lib/agent_registry.sh"
formation=$(agent_registry_agents)
if printf '%s\n' "$formation" | grep -Fxq metsuke; then
    printf '%s\n' metsuke
elif printf '%s\n' "$formation" | grep -Fxq gunshi; then
    printf '%s\n' gunshi
else
    echo 'No QC recipient configured: enable Metsuke or Gunshi.' >&2
    exit 1
fi
