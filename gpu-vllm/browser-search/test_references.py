import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import server
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError


class Session:
    pass


class ReferenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server.pages.clear()
        server.next_cursor = 0
        server.session_references.clear()
        server.transport_references.clear()
        self.document = {'url': 'https://example.com/article', 'title': 'Article',
                         'text': 'actual source\nsecond line'}
        self.cursor = server.remember({'url': self.document['url'], 'title': 'Article'})

    async def test_integer_string_prefixed_and_opaque_references(self):
        for kwargs in [{'cursor': self.cursor}, {'cursor': str(self.cursor)},
                       {'cursor': f'cursor:{self.cursor}'}, {'ref_id': server.reference_id(self.cursor)},
                       {'id': self.cursor}, {'url': f'cursor:{self.cursor}'}]:
            with patch.object(server, 'worker', AsyncMock(return_value=dict(self.document))) as worker:
                document = json.loads(await server.open(**kwargs))
                self.assertEqual(document['url'], self.document['url'])
                self.assertTrue(document['ref_id'].startswith(f'browser:{server.run_id}:'))
                self.assertIn('0: actual source', document['text'])
                worker.assert_awaited_once_with({'action': 'open', 'url': self.document['url']})

    async def test_direct_url_in_ref_id_needs_no_cached_page(self):
        server.pages.clear()
        with patch.object(server, 'worker', AsyncMock(return_value=dict(self.document))):
            result = json.loads(await server.open(ref_id=self.document['url']))
        self.assertEqual(result['url'], self.document['url'])

    async def test_empty_unknown_and_stale_are_recoverable_without_network(self):
        for kwargs in [{}, {'cursor': 999}, {'ref_id': 'turn99search0'},
                       {'ref_id': 'browser:oldrun:0'}]:
            with patch.object(server, 'worker', AsyncMock()) as worker:
                with self.assertRaises(ToolError) as error:
                    await server.open(**kwargs)
                self.assertRegex(str(error.exception), 'URL|url|source')
                worker.assert_not_awaited()

    async def test_conflicting_references_are_not_guessed(self):
        with patch.object(server, 'worker', AsyncMock()) as worker:
            with self.assertRaisesRegex(ToolError, 'Conflicting'):
                await server.open(url='https://other.example.com', cursor=self.cursor)
            worker.assert_not_awaited()

    async def test_search_aliases_are_session_specific(self):
        contexts = [SimpleNamespace(session=Session()), SimpleNamespace(session=Session())]
        for i, ctx in enumerate(contexts):
            result = {'query': str(i), 'results': [{'url': f'https://example.com/{i}', 'title': str(i)}]}
            with patch.object(server, 'worker', AsyncMock(return_value=result)):
                found = json.loads(await server.search(str(i), ctx=ctx))
            self.assertEqual(found['results'][0]['search_ref'], 'turn0search0')
        for i, ctx in enumerate(contexts):
            self.assertEqual(server.resolve_reference(ref_id='turn0search0', ctx=ctx)[0],
                             f'https://example.com/{i}')
        with self.assertRaises(ToolError):
            server.resolve_reference(ref_id='turn0search0', ctx=SimpleNamespace(session=Session()))

    async def test_evicted_references_do_not_open_another_page(self):
        for i in range(501):
            server.remember({'url': f'https://example.com/new/{i}'})
        with self.assertRaises(ToolError):
            server.resolve_reference(cursor=self.cursor)

    async def test_mcp2_per_request_session_proxies_share_transport_scope(self):
        def context():
            return SimpleNamespace(session=Session(), request_context=SimpleNamespace(
                request=SimpleNamespace(query_params={'session_id': 'same-http-session'})))
        found = {'query': 'q', 'results': [{'url': 'https://example.com/mcp2', 'title': 'MCP2'}]}
        with patch.object(server, 'worker', AsyncMock(return_value=found)):
            result = json.loads(await server.search('q', ctx=context()))
        alias = result['results'][0]['search_ref']
        self.assertEqual(server.resolve_reference(ref_id=alias, ctx=context())[0],
                         'https://example.com/mcp2')

    async def test_sse_initial_get_uses_stable_connection(self):
        connection = Session()
        def context():
            return SimpleNamespace(session=SimpleNamespace(_connection=connection),
                                   request_context=SimpleNamespace(request=None))
        result = {'query': 'q', 'results': [{'url': 'https://example.com/sse', 'title': 'SSE'}]}
        with patch.object(server, 'worker', AsyncMock(return_value=result)):
            found = json.loads(await server.search('q', ctx=context()))
        self.assertEqual(server.resolve_reference(ref_id=found['results'][0]['search_ref'],
                                                 ctx=context())[0], 'https://example.com/sse')

    async def test_find_opens_search_result_and_reuses_document_text(self):
        with patch.object(server, 'worker', AsyncMock(return_value=dict(self.document))) as worker:
            found = json.loads(await server.find('actual', ref_id=server.reference_id(self.cursor)))
            self.assertTrue(found['matches'])
            worker.assert_awaited_once()
            opened_cursor = server.next_cursor - 1
            found = json.loads(await server.find('second', cursor=opened_cursor))
            self.assertTrue(found['matches'])
            worker.assert_awaited_once()

    async def test_mcp_preserves_actionable_error_message(self):
        for arguments in [{}, {'cursor': 999}]:
            with self.assertRaises(ToolError) as raised:
                await server.server.call_tool('open', arguments)
            self.assertNotIsInstance(raised.exception, UnexpectedToolError)
            text = str(raised.exception)
            self.assertRegex(text, 'No page reference|Unknown or expired')
            self.assertNotEqual(text, 'Error executing tool open')


if __name__ == '__main__':
    unittest.main(verbosity=2)
