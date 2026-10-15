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
                                     'ashigaru4', 'metsuke', 'gunshi'])
            self.assertFalse(any('new-session' in call and '-s shogun' in call
                                 for call in calls))
            self.assertIn('select-pane -t multiagent:agents.0', calls)
            effective = yaml.safe_load((root / 'runtime/model_profiles/default.yaml').read_text())
            self.assertEqual(set(effective['cli']['agents']), set(roles))

    def shell(self, command, **environment):
        defaults = {
            'CLI_ADAPTER_SETTINGS': str(PROFILE),
            'AGENT_REGISTRY_SETTINGS': str(PROFILE),
            'CLI_ADAPTER_SKIP_STARTUP_PROMPT': 'true',
        }
        env = {**os.environ, **defaults, **environment}
        return subprocess.check_output(["bash", "-c", command], cwd=ROOT,
                                       env=env, text=True).strip()

    def cli(self, agent, **environment):
        return shlex.split(self.shell(
            f'source lib/cli_adapter.sh; build_cli_command {agent}', **environment))

    def test_default_is_seven_agents_with_karo_first(self):
        actual = self.shell('source lib/agent_registry.sh; agent_registry_agents').splitlines()
        self.assertEqual(actual, ['karo', 'ashigaru1', 'ashigaru2', 'ashigaru3',
                                  'ashigaru4', 'metsuke', 'gunshi'])
        fallback = self.shell('AGENT_REGISTRY_SETTINGS=/nonexistent; '
                              'source lib/agent_registry.sh; agent_registry_agents').splitlines()
        self.assertEqual(fallback, actual)
        self.assertEqual(self.shell('source lib/agent_registry.sh; '
                                    'agent_registry_pane_for_agent karo 1'),
                         'multiagent:agents.1')

    def test_all_ashigaru_use_vibe_with_no_persona(self):
        for agent in ['ashigaru1', 'ashigaru2', 'ashigaru3', 'ashigaru4']:
            with self.subTest(agent=agent):
                # A fresh launch (startup prompt NOT suppressed) primes the
                # plain-mechanics protocol, with no persona/identity wording.
                args = self.cli(agent, CLI_ADAPTER_SKIP_STARTUP_PROMPT='false')
                self.assertEqual(args[:4], ['vibe', '--agent', 'plan', '--auto-approve'])
                self.assertIn('--trust', args)
                joined = ' '.join(args)
                self.assertNotIn('ashigaru', joined.lower())
                self.assertNotIn('足軽', joined)
                self.assertIn('vibe_minimal_protocol.md', joined)

                # A resumed/pooled session (startup prompt suppressed) gets
                # the bare command, same as every other CLI type.
                resumed_args = self.cli(agent)
                self.assertEqual(resumed_args, ['vibe', '--agent', 'plan', '--auto-approve', '--trust'])

                instruction_file = self.shell(
                    f'source lib/cli_adapter.sh; get_instruction_file {agent} vibe'
                )
                self.assertEqual(instruction_file, 'instructions/common/vibe_minimal_protocol.md')

    def test_resume_pool_is_provider_and_endpoint_scoped(self):
        # session_pool_path's endpoint-scoping only applies to an agent
        # whose config declares base_url_env - none of the default
        # profile's agents do anymore (no babel/vLLM worker), so this
        # exercises the library function directly via a synthetic agent
        # rather than depending on the current default formation's shape.
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as f:
            yaml.safe_dump({
                'cli': {'agents': {
                    'scoped_worker': {
                        'type': 'codex',
                        'provider': 'babel',
                        'base_url_env': 'SHOGUN_VLLM_BASE_URL',
                    },
                    'metsuke': {'type': 'codex'},
                }}
            }, f)
            synthetic_settings = f.name
        try:
            command = ('source lib/cli_adapter.sh; source lib/session_pool.sh; '
                       'session_pool_path scoped_worker codex')
            first = self.shell(command, CLI_ADAPTER_SETTINGS=synthetic_settings,
                               SHOGUN_VLLM_BASE_URL='http://127.0.0.1:8003/v1')
            second = self.shell(command, CLI_ADAPTER_SETTINGS=synthetic_settings,
                                SHOGUN_VLLM_BASE_URL='http://127.0.0.1:32424/v1')
            self.assertNotEqual(first, second)
            commercial = self.shell(
                'source lib/cli_adapter.sh; source lib/session_pool.sh; '
                'session_pool_path metsuke codex',
                CLI_ADAPTER_SETTINGS=synthetic_settings,
            )
            self.assertTrue(commercial.endswith('/metsuke.codex.id'))
            self.assertFalse(first.endswith('/scoped_worker.codex.id'))
        finally:
            os.unlink(synthetic_settings)

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
        self.assertEqual(profile['formation']['ashigaru_count'], 4)


if __name__ == '__main__':
    unittest.main()
