"""Launch the unchanged Codex CLI with explicit local-backend capabilities.

Usage: GPTOSS_BASE_URL=http://server:8000/v1 pixi run python codex-gptoss.py
Optional: GPTOSS_API_KEY, GPTOSS_MODEL, GPTOSS_WEB_SEARCH (default live).
All CLI arguments are forwarded. The vLLM server must configure a browser tool.
"""
import json
import os
import sys
import shutil
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parent
base_url = os.environ.get('GPTOSS_BASE_URL')
if not base_url or urlsplit(base_url).scheme not in ('http', 'https'):
    raise SystemExit('Set GPTOSS_BASE_URL to the existing vLLM Responses API base URL, ending in /v1.')
provider = '{name="GPT-OSS vLLM",base_url=%s,wire_api="responses",env_key="GPTOSS_API_KEY",requires_openai_auth=false}' % json.dumps(base_url)
# A local vLLM server may not require authentication. Never borrow OpenAI credentials.
os.environ.setdefault('GPTOSS_API_KEY', 'local-no-auth')
arguments = [
    os.environ.get('GPTOSS_CODEX_BIN') or shutil.which('codex') or str(root / '.pixi/envs/default/bin/codex'),
    *sys.argv[1:],
    '-c', 'model_provider="gptoss_vllm"',
    '-c', 'model_providers.gptoss_vllm=' + provider,
    '-c', 'web_search=' + json.dumps(os.environ.get('GPTOSS_WEB_SEARCH', 'live')),
    '-m', os.environ.get('GPTOSS_MODEL', 'openai/gpt-oss-120b'),
]
print('GPT-OSS backend: Web search mode=' + os.environ.get('GPTOSS_WEB_SEARCH', 'live')
      + '; function and namespace tools enabled.', file=sys.stderr)
os.execv(arguments[0], arguments)
