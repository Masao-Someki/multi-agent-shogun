"""Live MCP reference/error regression. Uses an existing browser server, no model."""
import argparse
import asyncio
import json
from vllm.entrypoints.mcp.tool_server import MCPToolServer


async def main(port):
    backend = MCPToolServer()
    await backend.add_tool_server(f'127.0.0.1:{port}')
    async with backend.new_session('browser', 'live-reference-check') as session:
        reply = await session.call_tool('search', {'query': 'Sacabambaspis Wikipedia', 'topn': 2})
        assert not reply.is_error, reply.content
        first = json.loads(reply.content[0].text)['results'][0]
        reply = await session.call_tool('open', {'ref_id': first['search_ref']})
        assert not reply.is_error, reply.content
        document = json.loads(reply.content[0].text)
        reply = await session.call_tool('find', {'ref_id': document['ref_id'], 'pattern': 'Sacabambaspis'})
        assert not reply.is_error and json.loads(reply.content[0].text)['matches'], reply.content
        for bad in [{}, {'cursor': 999999}, {'ref_id': 'browser:oldrun:0'}]:
            reply = await session.call_tool('open', bad)
            assert reply.is_error, reply
            message = reply.content[0].text
            assert 'source' in message or 'url=' in message, message
        print(json.dumps({'passed': True, 'port': port, 'source_url': document['url'],
                          'search_ref': first['search_ref'], 'ref_id': document['ref_id'],
                          'actionable_errors': 3}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    asyncio.run(main(args.port))
