"""Capture only tool declarations from a disposable local Codex request."""
import json
import argparse
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.captured_tools = request.get('tools', [])
        self.send_response(400)
        self.end_headers()
        self.wfile.write(b'{"error":{"message":"Local tool capture complete"}}')

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--web-search', choices=['cached', 'live', 'disabled'], default='disabled')
    args = parser.parse_args()
    server = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    result = subprocess.run([
        '.pixi/envs/default/bin/codex', 'exec', '--ephemeral', '--skip-git-repo-check',
        '-c', 'model_provider="capture"',
        '-c', 'web_search="%s"' % args.web_search,
        '-c', 'model_providers.capture={name="capture",base_url="http://127.0.0.1:%s/v1",wire_api="responses"}' % server.server_port,
        '-m', 'openai/gpt-oss-120b', 'Reply with OK without using any tools.',
    ], capture_output=True, text=True, timeout=45)
    server.shutdown()
    tools = getattr(server, 'captured_tools', None)
    if tools is None:
        raise RuntimeError(result.stderr)
    if args.web_search == 'disabled':
        Path(__file__).with_name('codex-tools.json').write_text(json.dumps(tools, indent=2) + '\n')
    path = Path(__file__).with_name('codex-web-search.json')
    records = json.loads(path.read_text()) if path.exists() else {}
    records[args.web_search] = {
        'web_tools': [t for t in tools if t['type'].startswith('web_search')],
        'tool_types': sorted({t['type'] for t in tools}),
        'functions': [t['name'] for t in tools if t['type'] == 'function'],
        'namespaces': [t['name'] for t in tools if t['type'] == 'namespace'],
    }
    path.write_text(json.dumps(records, indent=2) + '\n')
    print(args.web_search, records[args.web_search]['web_tools'])
