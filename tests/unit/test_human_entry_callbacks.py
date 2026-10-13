"""Offline regression checks for Karo's human-input callbacks (no live tmux)."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class HumanEntryCallbacks(unittest.TestCase):
    def hook(self, unread=False, active=False):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "queue/inbox").mkdir(parents=True)
            (base / "scripts").mkdir()
            (base / "bin").mkdir()
            (base / "queue/inbox/karo.yaml").write_text(
                "messages:\n  - content: review report\n    read: "
                + ("false" if unread else "true") + "\n"
            )
            marker = base / "unexpected-call"
            # Any notification or blocking wait is a regression for Karo.
            for target in (base / "scripts/inbox_write.sh", base / "bin/inotifywait"):
                target.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 9\n')
                target.chmod(0o700)
            env = dict(os.environ, __STOP_HOOK_SCRIPT_DIR=str(base),
                       __STOP_HOOK_AGENT_ID="karo", IDLE_FLAG_DIR=str(base),
                       PATH=str(base / "bin") + os.pathsep + os.environ["PATH"])
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/stop_hook_inbox.sh")], env=env,
                input=json.dumps({"stop_hook_active": active,
                                  "last_assistant_message": "任務完了でござる"}),
                text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "Karo self-notified or waited")
            return result.stdout

    def test_karo_completion_returns_without_self_report_or_wait(self):
        self.assertEqual(self.hook(), "")

    def test_karo_unread_is_still_delivered(self):
        output = json.loads(self.hook(unread=True))
        self.assertEqual(output["decision"], "block")
        self.assertIn("review report", output["reason"])

    def test_active_hook_returns_without_wait_or_loop(self):
        self.assertEqual(self.hook(active=True), "")
        self.assertEqual(self.hook(active=True, unread=True), "")

    def watcher_function(self, name):
        source = (ROOT / "scripts/inbox_watcher.sh").read_text()
        match = re.search(r"^" + name + r"\(\) \{\n.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(match)
        return match.group()

    def test_human_panes_reject_resets_models_and_cli_restarts(self):
        function = self.watcher_function("send_cli_command")
        for agent in ("karo", "shogun"):
            for command in ("/clear", "/model x", "__CLI_RESTART__:codex"):
                script = function + '\nget_effective_cli_type() { echo claude; }\n'
                script += 'tmux() { echo UNSAFE; return 9; }\n'
                script += 'send_cli_command "$1"; test "$?" = 1\n'
                result = subprocess.run(["bash", "-c", script, "test", command],
                                        env=dict(os.environ, AGENT_ID=agent),
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("UNSAFE", result.stdout)

    def test_human_escape_escalation_uses_only_plain_nudge(self):
        function = self.watcher_function("send_wakeup_with_escape")
        for agent in ("karo", "shogun"):
            script = function + '\nget_effective_cli_type() { echo claude; }\n'
            script += 'send_wakeup() { echo "NUDGE:$1"; }\n'
            script += 'tmux() { echo UNSAFE; return 9; }\nsend_wakeup_with_escape 2\n'
            result = subprocess.run(["bash", "-c", script],
                                    env=dict(os.environ, AGENT_ID=agent),
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "NUDGE:2")

    def test_ntfy_target_default_and_explicit_legacy(self):
        source = (ROOT / "scripts/ntfy_listener.sh").read_text()
        selection = source[source.index('SETTINGS='):source.index('TOPIC=')]
        for legacy in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                settings = Path(directory) / "settings.yaml"
                settings.write_text("cli:\n  agents:\n    karo: {}\n"
                                    + ("    shogun: {}\n" if legacy else ""))
                env = dict(os.environ, SCRIPT_DIR=str(ROOT),
                           SHOGUN_SETTINGS_FILE=str(settings))
                result = subprocess.run(["bash", "-c", selection + '\necho "$NTFY_TARGET"'],
                                        env=env, text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "shogun" if legacy else "karo")


if __name__ == "__main__":
    unittest.main()
