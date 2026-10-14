"""Babel-side live-search policy and byte-streaming Responses API proxy."""
import argparse
import asyncio
import copy
import gzip
import io
import json
import logging
import uuid
import zlib

import aiohttp
from aiohttp import web
from yarl import URL

LOGGER = logging.getLogger('responses_proxy')
CONFLICTING_NAMESPACE = 'mcp__codex_apps__search_service'
SEARCH_FUNCTION = '_web_run'
WEB_TYPES = {'web_search', 'web_search_2025_08_26',
             'web_search_preview', 'web_search_preview_2025_03_11'}
MAX_BODY = 16 * 1024 * 1024
GUIDANCE = (
    '[Babel server-side Web search policy]\n'
    'Live Web search is provided by the server-side browser tools declared in '
    'the system message. Call browser.search with JSON arguments such as '
    '{"query":"Sacabambaspis Wikipedia"}; read sources with browser.open and '
    'browser.find. These are native assistant tool recipients, NOT executable '
    'programs. Never pass browser.search, browser.open or browser.find to '
    'exec_command, a shell, bash, zsh or another local command runner. '
    'The browser runs on Babel independently of the local shell sandbox; local '
    'network restrictions do not imply that it is unavailable. If asked whether '
    'Web access works, verify with browser.search and report the actual result. '
    'For scientific facts or requested literature, verify claims using these '
    'browser tools rather than guessing from memory. '
    'Do not use the client-side Codex Apps search_service for Web search. '
    'On an actual browser error, describe the error instead of inventing sources '
    'or facts. Keep using all other declared tools normally.'
)
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate',
               'proxy-authorization', 'te', 'trailer', 'transfer-encoding',
               'upgrade', 'host', 'content-length'}
SESSION = web.AppKey('upstream_session', aiohttp.ClientSession)
UPSTREAM = web.AppKey('upstream_url', str)
POLICY = web.AppKey('policy', dict)


class PolicyError(ValueError):
    pass


def apply_policy(body, *, server_tool='web_search_preview', guidance=True):
    """Replace only the identified client search capability, preserving other data."""
    if not isinstance(body, dict):
        raise PolicyError('The Responses request must be a JSON object.')
    tools = body.get('tools', [])
    if not isinstance(tools, list):
        raise PolicyError('tools must be an array.')
    result = copy.deepcopy(body)
    kept = []
    removed = []
    qualified_names = {
        f'{CONFLICTING_NAMESPACE}.{SEARCH_FUNCTION}',
        f'{CONFLICTING_NAMESPACE}__{SEARCH_FUNCTION}',
    }
    for tool in tools:
        if not isinstance(tool, dict):
            raise PolicyError('Each tools entry must be an object.')
        if tool.get('type') == 'namespace' and tool.get('name') == CONFLICTING_NAMESPACE:
            children = tool.get('tools')
            if not isinstance(children, list):
                raise PolicyError('Search namespace tools must be an array.')
            surviving = []
            for child in children:
                if isinstance(child, dict) and child.get('type') == 'function' and child.get('name') == SEARCH_FUNCTION:
                    removed.append(f'{CONFLICTING_NAMESPACE}.{SEARCH_FUNCTION}')
                else:
                    surviving.append(copy.deepcopy(child))
            if surviving:
                kept.append({**copy.deepcopy(tool), 'tools': surviving})
        elif tool.get('type') == 'function' and tool.get('name') in qualified_names:
            removed.append(tool['name'])
        else:
            kept.append(copy.deepcopy(tool))

    def removed_reference(ref):
        if not isinstance(ref, dict) or ref.get('type') != 'function':
            return False
        function = ref.get('function')
        name = ref.get('name') or (function.get('name') if isinstance(function, dict) else None)
        if name in qualified_names:
            return bool(removed)
        if ref.get('namespace') == CONFLICTING_NAMESPACE and name == SEARCH_FUNCTION:
            return bool(removed)
        # A bare name must not hide an unrelated surviving function.
        surviving_names = [t.get('name') for t in kept if t.get('type') == 'function']
        surviving_names += [c.get('name') for t in kept if t.get('type') == 'namespace'
                            for c in t.get('tools', []) if isinstance(c, dict)]
        return bool(removed) and name == SEARCH_FUNCTION and name not in surviving_names

    choice = body.get('tool_choice', 'auto')
    refs = [choice]
    if isinstance(choice, dict) and choice.get('type') == 'allowed_tools':
        allowed = choice.get('tools')
        if allowed is None:
            nested = choice.get('allowed_tools', {})
            if not isinstance(nested, dict):
                raise PolicyError('tool_choice.allowed_tools must be an object.')
            allowed = nested.get('tools', [])
        if not isinstance(allowed, list):
            raise PolicyError('tool_choice allowed tools must be an array.')
        refs += allowed
    if any(removed_reference(ref) for ref in refs):
        raise PolicyError('tool_choice references a client search tool replaced by '
                          'the Babel search policy. Use auto or a supported server '
                          'Web search choice; the choice was not silently broadened.')
    added = False
    # Preserve tool_choice=none, cached-access flags and existing tool options.
    # Tool-free requests include Codex's internal context compaction calls.
    # Never inject executable capabilities or browser guidance into those calls.
    if (choice != 'none' and bool(removed)
            and not any(t.get('type') in WEB_TYPES for t in kept)):
        tool = {'type': server_tool}
        if server_tool == 'web_search':
            tool['external_web_access'] = True
        kept.append(tool)
        added = True
    result['tools'] = kept
    if guidance and choice != 'none' and any(t.get('type') in WEB_TYPES for t in kept):
        value = body.get('input')
        if isinstance(value, str):
            result['input'] = [{'role': 'user', 'content': value}]
        elif not isinstance(value, list):
            raise PolicyError('input must be text or an array when guidance is enabled.')
        if not any(isinstance(item, dict) and item.get('role') == 'developer'
                   and item.get('content') == GUIDANCE for item in result['input']):
            result['input'].append({'role': 'developer', 'content': GUIDANCE})
    return result, {'removed': removed, 'added_server_tool': added,
                    'tools_before': len(tools), 'tools_after': len(kept)}


def forwarded_headers(headers):
    excluded = HOP_HEADERS | {token.strip().lower()
                              for token in headers.get('Connection', '').split(',')}
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


def error_response(message, status=400):
    return web.json_response({'error': {'message': message, 'type': 'invalid_request_error',
                                       'param': 'tools', 'code': status}}, status=status)


async def relay(request):
    data = await request.read()
    headers = forwarded_headers(request.headers)
    if request.method == 'POST' and request.path == '/v1/responses':
        try:
            encoding = request.headers.get('Content-Encoding', 'identity').lower()
            if encoding == 'gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                    decoded = compressed.read(MAX_BODY + 1)
            elif encoding == 'deflate':
                decompressor = zlib.decompressobj()
                decoded = decompressor.decompress(data, MAX_BODY + 1)
                if decompressor.unconsumed_tail:
                    return error_response('Decoded request is too large.', 413)
            elif encoding in ('identity', ''):
                decoded = data
            else:
                return error_response(f'Unsupported request Content-Encoding {encoding!r}; '
                                      'use identity or gzip for the search policy.', 415)
            if len(decoded) > MAX_BODY:
                return error_response('Decoded request is too large.', 413)
            body, audit = apply_policy(json.loads(decoded), **request.app[POLICY])
            data = json.dumps(body, ensure_ascii=False).encode()
            headers = {k: v for k, v in headers.items()
                       if k.lower() not in ('content-encoding', 'content-type')}
            headers['Content-Type'] = 'application/json'
            # No credentials, user text, tool arguments or reasoning are logged.
            LOGGER.info('policy %s', json.dumps({'request_id': uuid.uuid4().hex, **audit}))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return error_response(str(exc))
    downstream = None
    try:
        url = URL(request.app[UPSTREAM] + request.raw_path, encoded=True)
        async with request.app[SESSION].request(
            request.method, url, data=data if data else None,
            headers=headers, allow_redirects=False,
        ) as upstream:
            downstream = web.StreamResponse(status=upstream.status,
                                            headers=forwarded_headers(upstream.headers))
            await downstream.prepare(request)
            async for chunk in upstream.content.iter_any():
                await downstream.write(chunk)
            await downstream.write_eof()
            return downstream
    except asyncio.CancelledError:
        # Closing the upstream context propagates client cancellation to vLLM.
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
        if downstream is not None and downstream.prepared:
            downstream.force_close()
            return downstream
        return web.json_response({'error': {'message': 'The vLLM upstream is unavailable.',
                                           'type': 'upstream_error', 'code': 502}}, status=502)


def make_app(upstream='http://127.0.0.1:8000', *, guidance=True,
             server_tool='web_search_preview'):
    app = web.Application(client_max_size=MAX_BODY, handler_args={'auto_decompress': False})
    app[UPSTREAM] = upstream.rstrip('/')
    app[POLICY] = {'guidance': guidance, 'server_tool': server_tool}

    async def lifespan(app):
        timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=300)
        async with aiohttp.ClientSession(timeout=timeout, auto_decompress=False,
                                         trust_env=False) as session:
            app[SESSION] = session
            yield
    app.cleanup_ctx.append(lifespan)
    async def health(_request):
        return web.json_response({'status': 'ok'})

    app.router.add_get('/healthz', health)
    app.router.add_route('*', '/{path:.*}', relay)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', default='http://127.0.0.1:8000')
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--server-tool', choices=['web_search', 'web_search_preview'],
                        default='web_search_preview')
    parser.add_argument('--no-guidance', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    web.run_app(make_app(args.upstream, guidance=not args.no_guidance,
                         server_tool=args.server_tool), host='127.0.0.1',
                port=args.port, handler_cancellation=True, access_log=None)
