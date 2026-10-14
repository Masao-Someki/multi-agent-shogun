"""Default formation and provider commands, without starting tmux or any CLI."""
import os
from pathlib import Path
import shlex
import subprocess
import shutil
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "config/model_profiles/default.yaml"


class DefaultFormationTests(unittest.TestCase):
    def test_departure_setup_with_mock_tmux_and_old_config(self):
        # Isolated copy: every write stays under TemporaryDirectory and tmux
        # only records calls. No CLI, server, or existing session is touched.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in ['lib', 'config/model_profiles', 'scripts']:
                shutil.copytree(ROOT / directory, root / directory)
            shutil.copy2(ROOT / 'shutsujin_departure.sh', root)
            (root / 'logs').mkdir()
            (root / 'scripts/mcp_health_check.sh').write_text('#!/usr/bin/env bash\nexit 0\n')
            (root / 'config/settings.yaml').write_text(yaml.safe_dump({
                'cli': {'agents': {'shogun': {'type': 'claude'},
                                  'ashigaru8': {'type': 'claude'}}}}))
            python_dir = root / '.venv/bin'
            python_dir.mkdir(parents=True)
            (python_dir / 'python3').symlink_to(sys.executable)
            binaries = root / 'bin'
            binaries.mkdir()
            mock = binaries / 'tmux'
            mock.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$MOCK_TMUX_LOG"
case "$1" in
list-panes) echo '0 200 80';;
show-options) echo 0;;
esac
''')
            mock.chmod(0o755)
            for name in ['sleep', 'pkill', 'rm', 'clear']:
                stub = binaries / name
                stub.write_text('#!/usr/bin/env bash\nexit 0\n')
                stub.chmod(0o755)
            log = root / 'tmux.log'
            env = dict(os.environ, PATH=str(binaries) + ':' + os.environ['PATH'],
                       HOME=str(root), MOCK_TMUX_LOG=str(log))
            result = subprocess.run(['bash', str(root / 'shutsujin_departure.sh'), '-s'],
                                    env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = log.read_text().splitlines()
            roles = [call.split()[-1] for call in calls if ' @agent_id ' in call]
            self.assertEqual(roles, ['karo', 'ashigaru1', 'ashigaru2', 'ashigaru3',
                                     'metsuke', 'tanya', 'gunshi'])
            self.assertFalse(any('new-session' in call and '-s shogun' in call
                                 for call in calls))
            self.assertIn('select-pane -t multiagent:agents.0', calls)
            effective = yaml.safe_load((root / 'runtime/model_profiles/default.yaml').read_text())
            self.assertEqual(set(effective['cli']['agents']), set(roles))

    def shell(self, command, **environment):
        env = dict(os.environ, CLI_ADAPTER_SETTINGS=str(PROFILE),
                   AGENT_REGISTRY_SETTINGS=str(PROFILE),
                   CLI_ADAPTER_SKIP_STARTUP_PROMPT="true", **environment)
        return subprocess.check_output(["bash", "-c", command], cwd=ROOT,
                                       env=env, text=True).strip()

    def cli(self, agent, **environment):
        return shlex.split(self.shell(
            f'source lib/cli_adapter.sh; build_cli_command {agent}', **environment))

    def test_default_is_seven_agents_with_karo_first(self):
        actual = self.shell('source lib/agent_registry.sh; agent_registry_agents').splitlines()
        self.assertEqual(actual, ['karo', 'ashigaru1', 'ashigaru2', 'ashigaru3',
                                  'metsuke', 'tanya', 'gunshi'])
        fallback = self.shell('AGENT_REGISTRY_SETTINGS=/nonexistent; '
                              'source lib/agent_registry.sh; agent_registry_agents').splitlines()
        self.assertEqual(fallback, actual)
        self.assertEqual(self.shell('source lib/agent_registry.sh; '
                                    'agent_registry_pane_for_agent karo 1'),
                         'multiagent:agents.1')

    def test_workers_use_babel_responses_and_medium(self):
        for agent in ['ashigaru1', 'ashigaru2', 'ashigaru3', 'tanya']:
            with self.subTest(agent=agent):
                args = self.cli(agent, SHOGUN_VLLM_BASE_URL='http://127.0.0.1:32424/v1')
                self.assertEqual(args[0], 'codex')
                self.assertIn('shogun-worker', args)
                self.assertIn('model_provider="babel"', args)
                self.assertIn('model_providers.babel.wire_api="responses"', args)
                self.assertIn('model_providers.babel.base_url="http://127.0.0.1:32424/v1"', args)
                self.assertIn('model_providers.babel.env_key="SHOGUN_VLLM_API_KEY"', args)
                self.assertIn('model_reasoning_effort="medium"', args)
                self.assertIn('model_context_window=131072', args)
                self.assertIn('model_auto_compact_token_limit=110000', args)
                self.assertIn('web_search=live', args)

    def test_resume_pool_is_provider_and_endpoint_scoped(self):
        command = ('source lib/cli_adapter.sh; source lib/session_pool.sh; '
                   'session_pool_path ashigaru1 codex')
        first = self.shell(command, SHOGUN_VLLM_BASE_URL='http://127.0.0.1:8003/v1')
        second = self.shell(command, SHOGUN_VLLM_BASE_URL='http://127.0.0.1:32424/v1')
        self.assertNotEqual(first, second)
        commercial = self.shell('source lib/cli_adapter.sh; source lib/session_pool.sh; '
                                'session_pool_path metsuke codex')
        self.assertTrue(commercial.endswith('/metsuke.codex.id'))
        self.assertFalse(first.endswith('/ashigaru1.codex.id'))

    def test_commercial_role_models_and_efforts(self):
        karo = self.cli('karo')
        self.assertEqual(karo[:3], ['codex', '--model', 'gpt-6-luna'])
        self.assertIn('model_reasoning_effort=medium', karo)
        gunshi = self.cli('gunshi')
        self.assertEqual(gunshi[:5], ['claude', '--model', 'claude-fable-5-1', '--effort', 'high'])
        metsuke = self.cli('metsuke')
        self.assertEqual(metsuke[:5], ['claude', '--model', 'sonnet', '--effort', 'medium'])

    def test_profile_declares_exact_runtime_formation(self):
        profile = yaml.safe_load(PROFILE.read_text())
        self.assertEqual(set(profile['formation']['agents']), set(profile['cli']['agents']))
        self.assertEqual(profile['formation']['ashigaru_count'], 3)


if __name__ == '__main__':
    unittest.main()
