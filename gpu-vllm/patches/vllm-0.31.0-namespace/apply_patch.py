"""Apply only to an exact, unmodified vLLM 0.31.0 installation; keep backups."""
import importlib.metadata
import subprocess
import sysconfig
from pathlib import Path

directory = Path(__file__).resolve().parent
site = Path(sysconfig.get_paths()['purelib'])
if importlib.metadata.version('vllm') != '0.31.0':
    raise SystemExit('This patch targets vLLM 0.31.0 only.')
for original in (directory / 'original').rglob('*.py'):
    target = site / original.relative_to(directory / 'original')
    if target.read_bytes() != original.read_bytes():
        raise SystemExit(f'Already patched or different source: {target}')
patch = directory / 'vllm-0.31.0-namespace.patch'
command = ['patch', '--batch', '--forward', '-p1', '-d', str(site), '-i', str(patch)]
subprocess.run(command + ['--dry-run'], check=True)
subprocess.run(command + ['--backup', '--suffix=.before-namespace'], check=True)
print('Applied. Restart the existing vLLM server to load the changed Python files.')
