"""Lifecycle regressions without starting a GPU process or accessing the Web."""
import os
import signal
import subprocess
import tempfile
import unittest
import io
from unittest.mock import Mock, patch
import service_stack as stack


class LifecycleTests(unittest.TestCase):
    def run_stack(self, ready, occupied=False, failing=None):
        with tempfile.TemporaryDirectory() as directory:
            handlers = {}
            process = Mock()
            process.poll.return_value = None
            if failing:
                process.poll.return_value = 7
                process.returncode = 7

            def record(sig, callback):
                handlers[sig] = callback

            def sleep(_delay):
                handlers[signal.SIGTERM](signal.SIGTERM, None)

            with patch.dict(os.environ, {'VLLM_API_KEY': 'test-private-key', 'VLLM_STATE_DIR': directory}), \
                 patch('sys.argv', ['service_stack.py']), \
                 patch.object(stack, 'ready', side_effect=ready), \
                 patch.object(stack, 'port_open', return_value=occupied), \
                 patch.object(stack, 'ensure_patch') as compatibility, \
                 patch.object(stack.subprocess, 'run') as run, \
                 patch.object(stack.subprocess, 'Popen', return_value=process) as spawn, \
                 patch.object(stack.signal, 'signal', side_effect=record), \
                 patch.object(stack.time, 'sleep', side_effect=sleep):
                if occupied or failing:
                    with self.assertRaises(RuntimeError):
                        stack.main()
                else:
                    stack.main()
                return spawn, process, compatibility, run

    def test_adoption_never_starts_patches_or_signals(self):
        spawn, process, compatibility, run = self.run_stack(lambda _name: True)
        spawn.assert_not_called()
        process.terminate.assert_not_called()
        compatibility.assert_not_called()
        run.assert_not_called()

    def test_occupied_unhealthy_port_refuses_duplicate(self):
        spawn, process, compatibility, run = self.run_stack(lambda _name: False, occupied=True)
        spawn.assert_not_called()
        compatibility.assert_not_called()

    def test_only_new_sidecar_is_cleaned_up(self):
        counts = {}

        def ready(name):
            counts[name] = counts.get(name, 0) + 1
            return name != 'browser' or counts[name] > 1

        spawn, process, compatibility, run = self.run_stack(ready)
        self.assertEqual(spawn.call_count, 1)
        process.terminate.assert_called_once()
        compatibility.assert_not_called()

    def test_child_failure_cleans_up(self):
        spawn, process, compatibility, run = self.run_stack(lambda _name: False, failing=True)
        self.assertEqual(spawn.call_count, 1)
        process.wait.assert_called_once()

    def test_model_configuration(self):
        command = stack.commands()['model']
        self.assertIn('openai/gpt-oss-120b', command)
        self.assertEqual(command[command.index('--tensor-parallel-size') + 1], '2')
        self.assertEqual(command[command.index('--tool-server') + 1], '127.0.0.1:8765')
        self.assertNotIn('--api-key', command)

    def test_dry_run_needs_no_key_or_gpu(self):
        with patch.dict(os.environ, {'VLLM_API_KEY': ''}), \
             patch('sys.argv', ['service_stack.py', '--dry-run']), \
             patch.object(stack.subprocess, 'Popen') as spawn, \
             patch.object(stack, 'ensure_patch') as compatibility, \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            stack.main()
        self.assertIn('openai/gpt-oss-120b', output.getvalue())
        spawn.assert_not_called()
        compatibility.assert_not_called()

    def test_missing_key_fails_before_any_service(self):
        for key in ['', 'REPLACE_WITH_PRIVATE_WORKER_API_KEY']:
            with self.subTest(key=key), \
                 patch.dict(os.environ, {'VLLM_API_KEY': key}), \
                 patch('sys.argv', ['service_stack.py']), \
                 patch.object(stack.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError, 'VLLM_API_KEY'):
                    stack.main()
                spawn.assert_not_called()

    def test_wrong_vllm_version_cannot_patch(self):
        with patch.object(stack.importlib.metadata, 'version', return_value='0.32.0'), \
             patch.object(stack.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, '0.31.0'):
                stack.ensure_patch()
            run.assert_not_called()

    def test_tunnel_forwards_only_proxy_via_login(self):
        script = stack.ROOT.parent / 'scripts/babel-tunnel.sh'
        result = subprocess.run(
            ['bash', '-c', 'ssh() { printf "%s\\n" "$@"; }; '
             'exec() { "$@"; }; export -f ssh exec; '
             'bash "$1" babel-m5-28 32424', 'test', str(script)],
            text=True, capture_output=True,
            env={**os.environ, 'BABEL_SSH_LOGIN': 'user@login.babel.cs.cmu.edu',
                 'BABEL_SSH_USER': 'user'}, check=True)
        args = result.stdout.splitlines()
        self.assertIn('127.0.0.1:32424:127.0.0.1:8003', args)
        self.assertIn('user@login.babel.cs.cmu.edu', args)
        self.assertEqual(args[-1], 'user@babel-m5-28')
        self.assertNotIn('8765', result.stdout)

    def test_tunnel_rejects_invalid_targets_before_ssh(self):
        script = stack.ROOT.parent / 'scripts/babel-tunnel.sh'
        for arguments in [[], ['-oProxyCommand=bad'], ['node', '0'],
                          ['node', '65536'], ['node', 'invalid']]:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    ['bash', '-c', 'ssh() { echo UNEXPECTED_SSH; }; '
                     'exec() { "$@"; }; export -f ssh exec; '
                     'bash "$@"', 'test', str(script), *arguments],
                    text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('UNEXPECTED_SSH', result.stdout)


if __name__ == '__main__':
    unittest.main()
