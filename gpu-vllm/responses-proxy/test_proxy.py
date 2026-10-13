import asyncio
import copy
import gzip
import json
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL
from proxy import apply_policy, make_app, PolicyError, CONFLICTING_NAMESPACE, GUIDANCE


def search_namespace():
    return {'type': 'namespace', 'name': CONFLICTING_NAMESPACE, 'description': 'Search',
            'tools': [{'type': 'function', 'name': '_web_run',
                       'parameters': {'type': 'object', 'properties': {'q': {'type': 'string'}}}}]}


class PolicyTests(unittest.TestCase):
    def test_only_conflicting_function_removed_and_all_state_preserved(self):
        shell = {'type': 'function', 'name': 'exec_command', 'description': 'shell',
                 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}
        other = {'type': 'namespace', 'name': 'workspace', 'description': 'files',
                 'tools': [{'type': 'function', 'name': 'edit', 'parameters': {'type': 'object'}}]}
        body = {'model': 'shogun-worker', 'input': [{'type': 'function_call_output',
                'call_id': 'call_original', 'output': '{"nested":[1,2]}'}],
                'tools': [shell, search_namespace(), other], 'tool_choice': 'auto',
                'previous_response_id': 'resp_original', 'store': True,
                'stream': True, 'parallel_tool_calls': True, 'metadata': {'x': 'unchanged'}}
        original = copy.deepcopy(body)
        result, audit = apply_policy(body, guidance=False)
        self.assertEqual(body, original)
        self.assertEqual(result['tools'][:2], [shell, other])
        self.assertEqual(result['tools'][2], {'type': 'web_search_preview'})
        for key in body.keys() - {'tools'}:
            self.assertEqual(result[key], body[key])
        self.assertEqual(audit['removed'], [CONFLICTING_NAMESPACE + '._web_run'])

    def test_existing_web_tool_flags_preserved(self):
        for live in [True, False]:
            web_tool = {'type': 'web_search', 'external_web_access': live,
                        'filters': {'allowed_domains': ['example.com']}}
            result, audit = apply_policy({'input': 'test', 'tools': [web_tool, search_namespace()]})
            self.assertEqual(result['tools'], [web_tool])
            self.assertFalse(audit['added_server_tool'])

    def test_tool_free_compaction_is_not_given_search_or_guidance(self):
        for tools in [None, []]:
            body = {'input': 'Summarize the previous conversation', 'store': False}
            if tools is not None:
                body['tools'] = tools
            result, audit = apply_policy(body)
            self.assertEqual(result['input'], body['input'])
            self.assertEqual(result['tools'], [])
            self.assertFalse(audit['added_server_tool'])

    def test_other_functions_with_similar_names_preserved(self):
        tools = [{'type': 'function', 'name': '_web_run'},
                 {'type': 'namespace', 'name': 'other_search_service',
                  'tools': [{'type': 'function', 'name': '_web_run'}]}]
        result, _ = apply_policy({'input': 'x', 'tools': tools}, guidance=False)
        self.assertEqual(result['tools'][:2], tools)

    def test_other_children_in_search_namespace_preserved(self):
        ns = search_namespace()
        retained = {'type': 'function', 'name': 'unrelated', 'parameters': {'type': 'object'}}
        ns['tools'].append(retained)
        result, _ = apply_policy({'input': 'x', 'tools': [ns]}, guidance=False)
        self.assertEqual(result['tools'][0], {**ns, 'tools': [retained]})

    def test_none_and_required_choices_unchanged(self):
        for choice in ['none', 'required']:
            result, _ = apply_policy({'input': 'x', 'tools': [search_namespace()], 'tool_choice': choice})
            self.assertEqual(result['tool_choice'], choice)
            if choice == 'none':
                self.assertEqual(result['tools'], [])
                self.assertEqual(result['input'], 'x')

    def test_removed_named_and_allowed_choices_are_explicit_errors(self):
        ref = {'type': 'function', 'name': '_web_run', 'namespace': CONFLICTING_NAMESPACE}
        for choice in [ref, {'type': 'allowed_tools', 'mode': 'required', 'tools': [ref]}]:
            with self.assertRaisesRegex(PolicyError, 'not silently broadened'):
                apply_policy({'input': 'x', 'tools': [search_namespace()], 'tool_choice': choice})

    def test_surviving_named_choice_is_not_rewritten(self):
        choice = {'type': 'function', 'name': '_web_run'}
        tools = [search_namespace(), {'type': 'function', 'name': '_web_run'}]
        result, _ = apply_policy({'input': 'x', 'tools': tools, 'tool_choice': choice})
        self.assertEqual(result['tool_choice'], choice)

    def test_guidance_preserves_history_and_deduplicates(self):
        history = [{'role': 'user', 'content': 'original'}, {'type': 'function_call',
                   'name': 'exec_command', 'call_id': 'call_1', 'arguments': '{"cmd":"ls"}'}]
        result, _ = apply_policy({'input': history, 'instructions': 'Original instructions',
                                  'tools': [{'type': 'web_search'}]})
        self.assertEqual(result['input'][:-1], history)
        self.assertEqual(result['instructions'], 'Original instructions')
        self.assertEqual(result['input'][-1], {'role': 'developer', 'content': GUIDANCE})
        second, _ = apply_policy(result)
        self.assertEqual(second, result)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.cancelled = asyncio.Event()
        self.stream_finished = asyncio.Event()
        self.fragments = [b'event: response.output_item.added\ndata: {"call_id":"call_unchanged"}\n\n',
                          'data: {"arguments":"日本語\\n","namespace":"workspace"}\n\n'.encode(),
                          b'event: response.completed\ndata: {"id":"resp_unchanged"}\n\n']

        async def upstream(request):
            raw = await request.read()
            self.received.append((request.method, request.raw_path, dict(request.headers), raw))
            mode = request.headers.get('X-Test-Mode')
            if mode in ['sse', 'cancel']:
                response = web.StreamResponse(headers={'Content-Type': 'text/event-stream',
                                                      'X-Request-Id': 'upstream-id'})
                await response.prepare(request)
                try:
                    if mode == 'cancel':
                        while True:
                            await response.write(b'data: {}\n\n')
                            await asyncio.sleep(0.02)
                    for fragment in self.fragments:
                        await response.write(fragment)
                        await asyncio.sleep(0.03)
                    self.stream_finished.set()
                except (ConnectionResetError, asyncio.CancelledError):
                    self.cancelled.set()
                return response
            if mode == 'error':
                return web.Response(status=429, body=b'{"error":{"code":429}}',
                                    headers={'Retry-After': '5', 'Content-Type': 'application/json'})
            if mode == 'compressed':
                return web.Response(body=gzip.compress(b'{"id":"resp_compressed"}'),
                                    headers={'Content-Encoding': 'gzip', 'Content-Type': 'application/json'})
            return web.Response(body=raw or b'{"object":"list"}', content_type='application/json')

        app = web.Application()
        app.router.add_route('*', '/{path:.*}', upstream)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.proxy = TestServer(make_app(str(self.upstream.make_url('')).rstrip('/')),
                                handler_cancellation=True)
        self.client = TestClient(self.proxy)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()

    async def test_auth_query_ids_and_state_forwarded(self):
        body = {'input': 'hello', 'tools': [search_namespace()], 'previous_response_id': 'resp_old'}
        r = await self.client.post(URL('/v1/responses?x=encoded%2Fvalue', encoded=True), json=body,
                                   headers={'Authorization': 'Bearer test-secret', 'X-Request-Id': 'client-id'})
        data = await r.json()
        self.assertEqual(data['previous_response_id'], 'resp_old')
        _, path, headers, _ = self.received[-1]
        self.assertEqual(path, '/v1/responses?x=encoded%2Fvalue')
        self.assertEqual(headers['Authorization'], 'Bearer test-secret')
        self.assertEqual({k.lower(): v for k, v in headers.items()}['x-request-id'], 'client-id')

    async def test_sse_bytes_ids_and_incremental_delivery(self):
        r = await self.client.post('/v1/responses', json={'input': 'x'}, headers={'X-Test-Mode': 'sse'})
        first = await r.content.readexactly(len(self.fragments[0]))
        self.assertFalse(self.stream_finished.is_set(), 'SSE must not buffer the full response')
        rest = await r.read()
        self.assertEqual(first + rest, b''.join(self.fragments))
        self.assertEqual(r.headers['X-Request-Id'], 'upstream-id')

    async def test_upstream_error_is_unchanged(self):
        r = await self.client.post('/v1/responses', json={'input': 'x'}, headers={'X-Test-Mode': 'error'})
        self.assertEqual(r.status, 429)
        self.assertEqual(r.headers['Retry-After'], '5')
        self.assertEqual(await r.read(), b'{"error":{"code":429}}')

    async def test_gzip_request_and_response(self):
        body = json.dumps({'input': 'x', 'tools': [search_namespace()]}).encode()
        r = await self.client.post('/v1/responses', data=gzip.compress(body),
                                   headers={'Content-Encoding': 'gzip', 'X-Test-Mode': 'compressed'})
        self.assertEqual(await r.json(), {'id': 'resp_compressed'})
        self.assertNotIn('Content-Encoding', self.received[-1][2])
        self.assertEqual(json.loads(self.received[-1][3])['tools'], [{'type': 'web_search_preview'}])

    async def test_get_and_delete_history_routes_are_transparent(self):
        for method in ['GET', 'DELETE']:
            r = await self.client.request(method, '/v1/responses/resp_original')
            self.assertEqual(r.status, 200)
            await r.read()
            self.assertEqual(self.received[-1][:2], (method, '/v1/responses/resp_original'))

    async def test_three_concurrent_requests(self):
        async def request(i):
            r = await self.client.post('/v1/responses', json={'input': str(i), 'metadata': {'worker': i}})
            return await r.json()
        values = await asyncio.gather(*(request(i) for i in range(3)))
        self.assertEqual([v['metadata']['worker'] for v in values], [0, 1, 2])

    async def test_client_disconnect_closes_upstream(self):
        r = await self.client.post('/v1/responses', json={'input': 'x'}, headers={'X-Test-Mode': 'cancel'})
        await r.content.readany()
        r.close()
        await asyncio.wait_for(self.cancelled.wait(), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
