"""Client integration test using real Codex and vLLM adapters, scripted inference.

This does NOT validate GPT-OSS inference or the interactive TUI. It verifies
the actual client executes shell calls, edits a fixture, and returns results.
"""
import json
import asyncio
import argparse
import os
import subprocess
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from openai_harmony import Message, Role
from vllm.entrypoints.openai.parser.harmony_utils import (
    get_developer_message, validate_harmony_web_search_tools,
)
from vllm.entrypoints.openai.responses.harmony import (
    harmony_to_response_output, response_input_to_harmony,
)
from vllm.entrypoints.openai.responses.protocol import ResponsesRequest
from vllm.entrypoints.openai.responses.utils import extract_function_tool_names
from vllm.entrypoints.openai.responses.streaming_events import (
    StreamingState, emit_content_delta_events, emit_previous_item_done_events,
    emit_browser_tool_events,
)
from vllm.entrypoints.mcp.tool_server import MCPToolServer
from vllm.entrypoints.openai.responses.context import HarmonyContext
from vllm.parser.harmony import Segment

directory = Path(__file__).resolve().parent
commands = ['cat probe.txt', "sed -i '1s/^before$/after/' probe.txt", 'cat probe.txt']


async def live_search(message):
    backend = MCPToolServer()
    await backend.add_tool_server('127.0.0.1:8765')
    async with backend.new_session('browser', 'codex-browser-regression') as session:
        results = await HarmonyContext.call_search_tool(SimpleNamespace(called_tools=set()), session, message)
        data = json.loads(results[0].content[0].text)
        assert data['results'], data
        return data


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"openai/gpt-oss-120b"}]}')

    def do_POST(self):
        try:
            request = ResponsesRequest(**json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            validate_harmony_web_search_tools(request.tools, SimpleNamespace(has_tool=lambda name: name == 'browser'))
            get_developer_message(tools=request.tools)
            names = extract_function_tool_names(request.tools)
            previous = []
            for item in request.input:
                response_input_to_harmony(item, previous)
                kind = item.get('type') if isinstance(item, dict) else item.type
                if kind == 'function_call':
                    previous.append(item)
            turn = self.server.turn
            self.server.turn += 1
            state = StreamingState()
            browser_events = []
            browser_output = []
            if turn == 0 and self.server.live_browser:
                search = Message.from_role_and_content(Role.ASSISTANT, '{"query":"OpenAI GPT OSS 120b","topn":3}').with_recipient('browser.search').with_channel('analysis')
                self.server.browser_result = asyncio.run(live_search(search))
                browser_events = emit_browser_tool_events(search, state)
                browser_output = [browser_events[-1].item.model_dump(exclude_none=True)]
                state.reset_for_new_item()
            if turn < len(commands):
                arguments = json.dumps({'cmd': commands[turn], 'yield_time_ms': 1000})
                message = (Message.from_role_and_content(Role.ASSISTANT, arguments)
                           .with_channel('commentary').with_recipient('functions.exec_command'))
                events = emit_content_delta_events(Segment('commentary', message.recipient, arguments), state, names)
                events += emit_previous_item_done_events(message, state, names)
                output = [events[-1].item.model_dump(exclude_none=True)]
            else:
                results = [i.get('output') if isinstance(i, dict) else i.output
                           for i in request.input
                           if (i.get('type') if isinstance(i, dict) else i.type) == 'function_call_output']
                assert results, 'Codex did not return shell results'
                text = str(results[-1])
                position = text.index('result-')
                secret = text[position:].split()[0].strip('"\\,}')
                message = Message.from_role_and_content(Role.ASSISTANT, secret).with_channel('final')
                item = harmony_to_response_output(message, names)[0].model_dump(exclude_none=True)
                output = [item]
                events = []
                added = dict(item, content=[])
                events = [
                    dict(type='response.output_item.added', output_index=0, item=added),
                    dict(type='response.output_text.delta', output_index=0, content_index=0,
                         item_id=item['id'], delta=secret),
                    dict(type='response.output_item.done', output_index=0, item=item),
                ]
            events = browser_events + events
            output = browser_output + output
            response = dict(id='resp_test_' + str(turn), object='response',
                            created_at=1, status='completed', model=request.model,
                            output=output, usage=dict(input_tokens=100, output_tokens=10,
                                                     total_tokens=110, input_tokens_details={'cached_tokens': 0},
                                                     output_tokens_details={'reasoning_tokens': 0}))
            start = dict(response, status='in_progress', output=[])
            records = [dict(type='response.created', response=start)]
            records += [e.model_dump(exclude_none=True) if hasattr(e, 'model_dump') else e for e in events]
            records.append(dict(type='response.completed', response=response))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for sequence, record in enumerate(records):
                record['sequence_number'] = sequence
                self.wfile.write(('event: ' + record['type'] + '\ndata: ' + json.dumps(record) + '\n\n').encode())
            self.wfile.flush()
        except Exception as exc:
            self.server.error = repr(exc)
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({'error': {'message': str(exc)}}).encode())

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-browser', action='store_true')
    args = parser.parse_args()
    server = HTTPServer(('127.0.0.1', 0), Handler)
    server.turn = 0
    server.live_browser = args.live_browser
    threading.Thread(target=server.serve_forever, daemon=True).start()
    environment = dict(os.environ, GPTOSS_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1')
    result = subprocess.run([
        str(directory.parents[1] / '.pixi/envs/default/bin/python'),
        str(directory / 'live_roundtrip.py'),
    ], env=environment, capture_output=True, text=True, timeout=260)
    server.shutdown()
    print('SCRIPTED INFERENCE — not GPT-OSS model verification')
    print(result.stdout)
    if args.live_browser:
        print('Live browser returned', len(getattr(server, 'browser_result', {}).get('results', [])), 'results')
    if result.returncode:
        print(result.stderr)
        print('Server error:', getattr(server, 'error', None))
    raise SystemExit(result.returncode)
