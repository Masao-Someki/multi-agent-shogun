import json
import unittest
from pathlib import Path

from openai_harmony import Message, Role
from vllm.entrypoints.openai.parser.harmony_utils import (
    get_developer_message, validate_harmony_web_search_tools,
)
from types import SimpleNamespace
from vllm.renderers.online_renderer import OnlineRenderer
from vllm.entrypoints.serve import create_error_response
from vllm.entrypoints.openai.responses.protocol import ResponsesRequest
from vllm.entrypoints.openai.responses.utils import extract_function_tool_names, extract_tool_types
from vllm.entrypoints.openai.responses.harmony import (
    harmony_to_response_output, response_input_to_harmony,
)
from vllm.entrypoints.openai.responses.streaming_events import (
    StreamingState, emit_function_call_delta_events,
    emit_previous_item_done_events, emit_content_delta_events,
)
from vllm.parser.harmony import Segment
from vllm.exceptions import VLLMValidationError


def function(name):
    return dict(type='function', name=name, description='Run ' + name,
                parameters={'type': 'object', 'properties': {
                    'cmd': {'type': 'string'}}, 'required': ['cmd']})


class NamespaceTests(unittest.TestCase):
    def request(self, tools):
        return ResponsesRequest(model='openai/gpt-oss-120b', input='hello', tools=tools)

    def call(self, recipient, text='{"cmd":"ls"}', channel='commentary'):
        return (Message.from_role_and_content(Role.ASSISTANT, text)
                .with_channel(channel).with_recipient(recipient))

    def namespace(self, name='functions'):
        return dict(type='namespace', name=name, description='Local tools',
                    tools=[function('exec_command'), function('read_file')])

    def test_existing_function(self):
        req = self.request([function('exec_command')])
        msg = get_developer_message(tools=req.tools)
        self.assertEqual(msg.content[0].tools['functions'].tools[0].name, 'exec_command')
        call = harmony_to_response_output(self.call('functions.exec_command'), extract_function_tool_names(req.tools))[0]
        self.assertEqual(call.name, 'exec_command')
        self.assertIsNone(call.namespace)

    def test_namespace_multiple_functions_and_schema(self):
        req = self.request([self.namespace()])
        ns = get_developer_message(tools=req.tools).content[0].tools['functions']
        self.assertEqual(ns.description, 'Local tools')
        self.assertEqual([t.name for t in ns.tools], ['exec_command', 'read_file'])
        self.assertEqual(ns.tools[0].parameters, function('exec_command')['parameters'])
        self.assertEqual(ns.tools[0].description, 'Run exec_command')

    def test_json_and_result_roundtrip(self):
        for namespace in ['functions', 'workspace']:
            req = self.request([self.namespace(namespace)])
            args = json.dumps({'cmd': 'printf "hello"', 'nested': [1, {'x': True}]})
            call = harmony_to_response_output(self.call(namespace + '.exec_command', args), extract_function_tool_names(req.tools))[0]
            self.assertEqual((call.namespace, call.name, call.arguments), (namespace, 'exec_command', args))
            history = response_input_to_harmony(call, [])
            self.assertEqual(history.recipient, namespace + '.exec_command')
            result = response_input_to_harmony(dict(type='function_call_output', call_id=call.call_id, output='hello'), [call])
            self.assertEqual(result.author.name, namespace + '.exec_command')
            self.assertEqual(result.content[0].text, 'hello')
            final = Message.from_role_and_content(Role.ASSISTANT, 'Done').with_channel('final')
            self.assertEqual(harmony_to_response_output(final, extract_function_tool_names(req.tools))[0].content[0].text, 'Done')

    def test_reasoning_with_tool_call(self):
        names = extract_function_tool_names(self.request([self.namespace()]).tools)
        analysis = Message.from_role_and_content(Role.ASSISTANT, 'Check file').with_channel('analysis')
        self.assertEqual(harmony_to_response_output(analysis, names)[0].type, 'reasoning')
        self.assertEqual(harmony_to_response_output(self.call('functions.read_file', channel='analysis'), names)[0].type, 'function_call')

    def test_streaming_names_and_ids(self):
        names = extract_function_tool_names(self.request([self.namespace()]).tools)
        state = StreamingState()
        events = emit_content_delta_events(Segment('analysis', 'functions.exec_command', '{"cmd":'), state, names)
        added = events[0].item
        done = emit_previous_item_done_events(self.call('functions.exec_command'), state, names)[-1].item
        self.assertEqual((added.namespace, added.name), ('functions', 'exec_command'))
        self.assertEqual((done.namespace, done.name), ('functions', 'exec_command'))
        self.assertEqual((added.id, added.call_id), (done.id, done.call_id))
        self.assertEqual(done.arguments, '{"cmd":"ls"}')

    def test_unsupported_not_dropped(self):
        ns = self.namespace()
        ns['tools'] = [dict(type='custom', name='apply_patch', description='edit')]
        with self.assertRaises(VLLMValidationError):
            get_developer_message(tools=self.request([ns]).tools)

    def test_dotted_existing_function_is_not_namespace(self):
        req = self.request([function('workspace.exec')])
        call = harmony_to_response_output(self.call('functions.workspace.exec'), extract_function_tool_names(req.tools))[0]
        self.assertEqual(call.name, 'workspace.exec')
        self.assertIsNone(call.namespace)

    def test_namespace_names_with_separator_are_preserved(self):
        ns = self.namespace('mcp__apps')
        ns['tools'] = [function('exec__command')]
        req = self.request([ns])
        call = harmony_to_response_output(self.call('mcp__apps.exec__command'), extract_function_tool_names(req.tools))[0]
        self.assertEqual((call.namespace, call.name), ('mcp__apps', 'exec__command'))

    def test_actual_codex_request(self):
        path = Path(__file__).with_name('codex-tools.sanitized.json')
        self.assertTrue(path.exists(), 'Sanitized Codex-shape fixture is required')
        req = self.request(json.loads(path.read_text()))
        developer = get_developer_message(tools=req.tools)
        names = extract_function_tool_names(req.tools)
        for tool in req.tools:
            if tool.type == 'namespace':
                ns = developer.content[0].tools[tool.name]
                self.assertEqual(ns.description, tool.description)
                for definition, nested in zip(ns.tools, tool.tools, strict=True):
                    self.assertEqual(definition.parameters, nested.parameters)
                    call = harmony_to_response_output(self.call(tool.name + '.' + nested.name), names)[0]
                    self.assertEqual((call.namespace, call.name), (tool.name, nested.name))

    def test_reject_conflicting_namespace(self):
        for namespace in ['browser', 'python', 'container', 'has.dot']:
            with self.assertRaises(VLLMValidationError):
                get_developer_message(tools=self.request([self.namespace(namespace)]).tools)
        with self.assertRaises(VLLMValidationError):
            get_developer_message(tools=self.request([function('exec'), self.namespace()]).tools)

    def test_missing_tool_call_id_rejected(self):
        with self.assertRaises(VLLMValidationError):
            response_input_to_harmony(dict(type='function_call_output', call_id='unknown', output='x'), [])

    def test_modern_search_requires_supported_mode_and_browser(self):
        for kind in ['web_search', 'web_search_2025_08_26']:
            for access in [True, False]:
                req = self.request([dict(type=kind, external_web_access=access)])
                with self.assertRaises(VLLMValidationError):
                    validate_harmony_web_search_tools(req.tools)
                backend = SimpleNamespace(has_tool=lambda name: name == 'browser')
                if access:
                    validate_harmony_web_search_tools(req.tools, backend)
                    get_developer_message(tools=req.tools)
                else:
                    with self.assertRaisesRegex(VLLMValidationError, 'cache-only'):
                        validate_harmony_web_search_tools(req.tools, backend)

    def test_modern_search_routes_only_harmony_to_browser(self):
        req = self.request([dict(type='web_search', external_web_access=True), function('exec'), self.namespace('workspace')])
        self.assertEqual(extract_tool_types(req.tools), {'web_search', 'function', 'namespace'})
        self.assertEqual(extract_tool_types(req.tools, harmony=True), {'web_search_preview', 'function', 'namespace'})
        self.assertEqual(req.tools[0].type, 'web_search')
        self.assertTrue(req.tools[0].external_web_access)

    def test_search_options_not_silently_dropped(self):
        for options in [dict(filters={'allowed_domains': ['example.com']}),
                        dict(user_location={'type': 'approximate', 'country': 'US'}),
                        dict(search_context_size='high')]:
            req = self.request([dict(type='web_search', **options)])
            with self.assertRaisesRegex(VLLMValidationError, 'cannot enforce'):
                validate_harmony_web_search_tools(req.tools, SimpleNamespace(has_tool=lambda name: True))

    def test_legacy_preview_requires_real_capability(self):
        req = self.request([dict(type='web_search_preview')])
        with self.assertRaisesRegex(VLLMValidationError, 'No browser backend'):
            validate_harmony_web_search_tools(req.tools)
        with self.assertRaises(VLLMValidationError):
            validate_harmony_web_search_tools(req.tools, SimpleNamespace(has_tool=lambda name: False))
        validate_harmony_web_search_tools(req.tools, SimpleNamespace(has_tool=lambda name: name == 'browser'))

    def test_search_rejection_before_history_reuse(self):
        renderer = SimpleNamespace(create_error_response=create_error_response)
        for previous in [None, [Message.from_role_and_content(Role.USER, 'hello')]]:
            req = self.request([function('exec_command'), self.namespace('workspace'), dict(type='web_search')])
            original = req.model_dump()
            result = OnlineRenderer._render_responses_with_harmony(
                renderer, req, previous_messages=previous,
                previous_response_outputs=None, tool_server=None,
            )
            self.assertEqual(result.error.param, 'tools')
            self.assertEqual(result.error.code, 400)
            self.assertIn('server-side browser', result.error.message)
            self.assertEqual(req.model_dump(), original, 'Request tools must not be dropped or rewritten')

    def test_actual_codex_search_modes(self):
        records = json.loads(Path(__file__).with_name('codex-web-search.sanitized.json').read_text())
        self.assertEqual(records['cached']['web_tools'], [{'type': 'web_search', 'external_web_access': False}])
        self.assertEqual(records['live']['web_tools'], [{'type': 'web_search', 'external_web_access': True}])
        self.assertEqual(records['disabled']['web_tools'], [])
        for mode in ['cached', 'live']:
            self.assertEqual(records[mode]['functions'], records['disabled']['functions'])
            self.assertEqual(records[mode]['namespaces'], records['disabled']['namespaces'])

    def test_completed_search_history_preserved_without_reexecution(self):
        item = dict(type='web_search_call', id='ws_original', status='completed',
                    action=dict(type='search', query='original query'))
        message = response_input_to_harmony(item, [])
        self.assertIsNone(message.recipient, 'Replaying history must not execute another search')
        self.assertEqual(message.channel, 'commentary')
        self.assertIn('ws_original', message.content[0].text)
        self.assertIn('original query', message.content[0].text)
        with self.assertRaises(VLLMValidationError):
            response_input_to_harmony(dict(item, status='in_progress'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
