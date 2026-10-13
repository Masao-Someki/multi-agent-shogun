"""Verify real Codex tool execution against an already-running GPT-OSS server.

Uses the unchanged Codex exec engine (shared with its TUI). This is not a mock.
Environment: GPTOSS_BASE_URL, optionally GPTOSS_API_KEY and GPTOSS_MODEL.
Artifacts remain in a new temporary directory for inspection.
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

directory = Path(__file__).resolve().parent
root = directory.parents[1]
url = os.environ.get('GPTOSS_BASE_URL', '').rstrip('/')
if not url:
    raise SystemExit('GPTOSS_BASE_URL is required: no server is launched by this test.')
headers = {'Authorization': 'Bearer ' + os.environ.get('GPTOSS_API_KEY', 'local-no-auth')}
with urlopen(Request(url + '/models', headers=headers), timeout=10) as response:
    models = json.load(response)
model = os.environ.get('GPTOSS_MODEL', 'openai/gpt-oss-120b')
if model not in {m['id'] for m in models['data']}:
    raise SystemExit('Expected GPT-OSS model is not listed by the server. Set GPTOSS_MODEL to its served name.')
work = Path(tempfile.mkdtemp(prefix='codex-gptoss-roundtrip-'))
secret = 'result-' + uuid.uuid4().hex
probe = work / 'probe.txt'
probe.write_text('before\n' + secret + '\n')
prompt = (
    'Use exec_command to read probe.txt. Edit only its first line from before to after, '
    'leaving its second line unchanged. Use exec_command again to read the edited file. '
    'In your final answer, quote the second line exactly. Do not inspect any other files.'
)
result = subprocess.run([
    str(root / '.pixi/envs/default/bin/python'), str(root / 'codex-gptoss.py'),
    'exec', '--ephemeral', '--skip-git-repo-check', '--json',
    '--sandbox', 'workspace-write', '-c', 'approval_policy="never"',
    '-C', str(work), prompt,
], capture_output=True, text=True, timeout=240)
(work / 'codex-events.jsonl').write_text(result.stdout)
(work / 'codex-stderr.txt').write_text(result.stderr)
events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
completed = [e['item'] for e in events if e.get('type') == 'item.completed']
commands = [i for i in completed if i.get('type') == 'command_execution']
answers = [i.get('text', '') for i in completed if i.get('type') == 'agent_message']
report = dict(
    backend=url, model=model, client='Codex CLI exec (TUI shared tool engine)',
    artifact_directory=str(work), returncode=result.returncode,
    successful_shell_calls=sum(i.get('exit_code') == 0 for i in commands),
    file_edited=probe.read_text() == 'after\n' + secret + '\n',
    tool_result_used_in_answer=any(secret in answer for answer in answers),
)
report['passed'] = (report['returncode'] == 0 and report['successful_shell_calls'] >= 2
                    and report['file_edited'] and report['tool_result_used_in_answer'])
(work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
sys.exit(0 if report['passed'] else 1)
