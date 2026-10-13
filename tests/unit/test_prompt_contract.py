"""The default Karo intake contract survives instruction generation."""
from pathlib import Path
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]


class PromptContract(unittest.TestCase):
    def test_auto_loaded_hierarchy_and_queue_compatibility(self):
        for name in ['CLAUDE.md', 'AGENTS.md', '.github/copilot-instructions.md',
                     'agents/default/system.md']:
            with self.subTest(name=name):
                source = (ROOT / name).read_text()
                self.assertIn('Lord (human) → Karo → Ashigaru 1-3', source)
                self.assertNotIn('Lord (human) → Shogun → Karo', source)
                self.assertIn('Legacy filename; Karo records direct human commands', source)
                self.assertNotIn('shogun: { pane_0: shogun }', source)

    def test_generated_karo_can_receive_and_reply_directly(self):
        for path in (ROOT / 'instructions/generated').glob('*karo.md'):
            with self.subTest(path=path.name):
                source = path.read_text()
                self.assertTrue(source.startswith('---\n'))
                config = yaml.safe_load(source.split('---', 2)[1])
                self.assertEqual(config['role'], 'karo')
                self.assertEqual(config['workflow'][0]['from'], 'lord')
                self.assertIn("the human's direct entry point", source)
                self.assertIn('no Shogun or Kumigashira', source)
                self.assertIn('Direct human replies are allowed', source)
                self.assertNotIn('action: direct_user_report', source)
                self.assertNotIn('Report directly to the human (bypass shogun)', source)
                self.assertIn('Tanya → Gunshi', source)
                self.assertIn('Metsuke → Karo', source)
                self.assertIn('Gunshi → Karo', source)

    def test_worker_questions_and_tanya_ownership_preserved(self):
        worker = (ROOT / 'instructions/generated/codex-ashigaru.md').read_text()
        strategist = (ROOT / 'instructions/generated/gunshi.md').read_text()
        self.assertIn('question ashigaru{N}', worker)
        self.assertIn('scripts/qc_target.sh', worker)
        self.assertIn('Karo must never assign Tanya', strategist)
        self.assertIn('type: answer', strategist)


if __name__ == '__main__':
    unittest.main()
