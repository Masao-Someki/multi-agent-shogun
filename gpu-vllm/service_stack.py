"""Foreground Babel supervisor; loopback sidecars, exact patch, safe adoption."""
import argparse
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import sysconfig
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
PROXY_PORT = int(os.environ.get('SHOGUN_PROXY_PORT', '33987'))


def commands():
    return {
        'browser': [sys.executable, str(ROOT / 'browser-search/server.py')],
        'model': [str(Path(sys.executable).parent / 'vllm'), 'serve', 'openai/gpt-oss-120b',
                  '--served-model-name', 'shogun-worker', '--host', '127.0.0.1', '--port', '8000',
                  '--tensor-parallel-size', '2', '--max-model-len', '131072',
                  '--max-num-seqs', '4', '--max-num-batched-tokens', '4096',
                  '--gpu-memory-utilization', '0.95', '--enable-prefix-caching',
                  '--kv-cache-dtype', 'fp8', '--enable-auto-tool-choice',
                  '--tool-call-parser', 'openai', '--reasoning-parser', 'openai_gptoss',
                  '--async-scheduling', '--cudagraph-capture-sizes', '1',
                  '--tool-server', '127.0.0.1:8765'],
        'proxy': [sys.executable, str(ROOT / 'responses-proxy/proxy.py'),
                  '--upstream', 'http://127.0.0.1:8000', '--port', str(PROXY_PORT)],
    }


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def ready(name):
    port = {'browser': 8765, 'model': 8000, 'proxy': PROXY_PORT}[name]
    headers = {}
    if name != 'browser' and os.environ.get('VLLM_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['VLLM_API_KEY']
    path = {'browser': '/sse', 'model': '/v1/models', 'proxy': '/healthz'}[name]
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers=headers)
        with urllib.request.urlopen(req, timeout=3) as response:
            if name == 'browser':
                return 'text/event-stream' in response.headers.get('Content-Type', '')
            if name == 'proxy':
                return json.load(response).get('status') == 'ok'
            return any(x.get('id') == 'shogun-worker' for x in json.load(response).get('data', []))
    except (OSError, ValueError):
        return False


def ensure_patch():
    if importlib.metadata.version('vllm') != '0.31.0':
        raise RuntimeError('Namespace patch requires vLLM 0.31.0; no upgrade attempted.')
    directory = ROOT / 'patches/vllm-0.31.0-namespace'
    original = directory / 'original'
    site = Path(sysconfig.get_paths()['purelib'])
    files = list(original.rglob('*.py'))
    if not files:
        raise RuntimeError('Patch originals are missing.')
    if all((site / p.relative_to(original)).read_bytes() == p.read_bytes() for p in files):
        subprocess.run([sys.executable, str(directory / 'apply_patch.py')], check=True)
    else:
        subprocess.run(['patch', '--batch', '--reverse', '--dry-run', '-p1', '-d', str(site),
                        '-i', str(directory / 'vllm-0.31.0-namespace.patch')], check=True,
                       stdout=subprocess.DEVNULL)


def start_sidecars():
    """Launch Browser MCP and the proxy detached; do not wait for readiness."""
    state = Path(os.environ.get('VLLM_STATE_DIR', str(ROOT / '.service-state')))
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_patch()
    plan = commands()
    sidecars = [('browser', 8765), ('proxy', PROXY_PORT)]
    for name, port in sidecars:
        if port_open(port):
            raise RuntimeError(f'Port {port} is occupied; refusing to start duplicate {name}.')
    for name, port in sidecars:
        log_path = state / f'{name}.log'
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'ab') as log:
            subprocess.Popen(plan[name], cwd=ROOT, stdout=log, stderr=log,
                             start_new_session=True)
        print(f'Launched {name} asynchronously on localhost:{port}; log: {log_path}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--start-sidecars', action='store_true')
    parser.add_argument('--ready-timeout', type=float, default=1800)
    args = parser.parse_args()
    plan = commands()
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    if args.start_sidecars:
        start_sidecars()
        return
    if not os.environ.get('VLLM_API_KEY') or os.environ['VLLM_API_KEY'].startswith('REPLACE_'):
        raise RuntimeError('Set VLLM_API_KEY in ~/vllm.key before startup.')
    state = Path(os.environ.get('VLLM_STATE_DIR', str(ROOT / '.service-state')))
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (state / 'supervisor.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another supervisor owns this state directory.')
    children, logs = [], []
    stopped = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def check_children():
        for name, process in children:
            if process.poll() is not None:
                raise RuntimeError(f'{name} exited ({process.returncode}); see {state}/{name}.log')

    try:
        for name, port in [('browser', 8765), ('model', 8000), ('proxy', PROXY_PORT)]:
            if ready(name):
                print(f'Adopting ready {name} on localhost:{port}; ownership remains external.', flush=True)
                continue
            if port_open(port):
                raise RuntimeError(f'Port {port} occupied but readiness failed; refusing duplicate service.')
            if name == 'model':
                subprocess.run(['nvidia-smi'], check=True, stdout=subprocess.DEVNULL)
                ensure_patch()
            fd = os.open(state / f'{name}.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            log = os.fdopen(fd, 'ab')
            logs.append(log)
            process = subprocess.Popen(plan[name], cwd=ROOT, stdout=log, stderr=log)
            children.append((name, process))
            deadline = time.monotonic() + (args.ready_timeout if name == 'model' else 60)
            while not ready(name):
                check_children()
                if stopped:
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'{name} readiness timed out; see {state}/{name}.log')
                time.sleep(1)
            print(f'Ready {name} on localhost:{port}', flush=True)
        print(f'Stack ready; worker URL http://127.0.0.1:{PROXY_PORT}/v1', flush=True)
        while not stopped:
            check_children()
            for name in plan:
                if not ready(name):
                    raise RuntimeError(f'{name} readiness was lost.')
            time.sleep(3)
    finally:
        # Signal only the child handles created here, never adopted services.
        for _, process in reversed(children):
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 20
        for _, process in reversed(children):
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'Stack failed: {error}', file=sys.stderr)
        sys.exit(1)
