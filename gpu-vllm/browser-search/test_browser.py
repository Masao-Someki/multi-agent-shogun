"""Live-browser regression via the existing vLLM MCP and Harmony adapters.

Run with server.py already listening at 127.0.0.1:8765. Makes real Web requests.
"""
import asyncio
import json
from types import SimpleNamespace
from openai_harmony import Message, Role
from vllm.entrypoints.mcp.tool_server import MCPToolServer
from vllm.entrypoints.openai.parser.harmony_utils import validate_harmony_web_search_tools
from vllm.entrypoints.openai.responses.protocol import ResponsesRequest
from vllm.entrypoints.openai.responses.context import HarmonyContext
from vllm.entrypoints.openai.responses.harmony import harmony_to_response_output


async def main():
    server = MCPToolServer()
    await server.add_tool_server('127.0.0.1:8765')
    assert server.has_tool('browser')
    description = server.get_tool_description('browser')
    assert {tool.name for tool in description.tools} == {'search', 'open', 'find'}
    request = ResponsesRequest(model='openai/gpt-oss-120b', input='search',
                               tools=[dict(type='web_search', external_web_access=True)])
    validate_harmony_web_search_tools(request.tools, server)
    async with server.new_session('browser', 'browser-regression') as session:
        query = 'OpenAI GPT OSS 120b'
        message = (Message.from_role_and_content(Role.ASSISTANT, json.dumps({'query': query, 'topn': 3}))
                   .with_channel('analysis').with_recipient('browser.search'))
        context = SimpleNamespace(called_tools=set())
        messages = await HarmonyContext.call_search_tool(context, session, message)
        result = json.loads(messages[0].content[0].text)
        assert result['results'] and result['query'] == query
        assert all(row['title'] and row['url'].startswith('http') for row in result['results'])
        assert messages[0].author.name == 'browser.search'
        assert messages[0].recipient == 'assistant'
        assert harmony_to_response_output(message, frozenset())[0].type == 'web_search_call'
        opened = await session.call_tool('open', {'url': 'https://example.com'})
        assert not opened.is_error, opened.content
        document = json.loads(opened.content[0].text)
        assert document['title'] == 'Example Domain' and document['text']
        found = await session.call_tool('find', {'cursor': document['cursor'], 'pattern': 'documentation'})
        assert not found.is_error, found.content
        assert json.loads(found.content[0].text)['matches']
        failed = await session.call_tool('open', {'cursor': -1})
        assert failed.is_error, 'Unknown cursors must produce explicit errors'
        print(json.dumps({'passed': True, 'search_results': result['results'],
                          'opened_url': document['url'], 'find': 'passed',
                          'error_handling': 'passed',
                          'path': 'Playwright → MCP → vLLM Harmony tool result'}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
