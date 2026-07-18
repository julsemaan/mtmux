import unittest
from unittest.mock import Mock, patch

from mtmux.discovery import _bell_sessions, _clean_env, bell_targets, local_bell_sessions, remote_bell_sessions


class DiscoveryBellTest(unittest.TestCase):
    def test_clean_env_removes_current_tmux_socket(self):
        with patch.dict("mtmux.discovery.os.environ", {"TMUX": "/tmp/tmux,1,0", "PATH": "x"}, clear=True):
            self.assertEqual(_clean_env(), {"PATH": "x"})

    def test_bell_sessions_parses_window_bell_flags(self):
        self.assertEqual(_bell_sessions("work:1\nwork:0\nmtmux:cockpit:1\nbad name:1\nchat:1"), {"work", "chat"})

    def test_local_bell_sessions_only_lists_windows(self):
        run = Mock(return_value=Mock(returncode=0, stdout="work:1:!\nidle:0:-\n"))

        with patch("mtmux.discovery.subprocess.run", run):
            self.assertEqual(local_bell_sessions(), {"work"})

        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["tmux", "list-windows", "-a"])
        self.assertNotIn("set-option", command)
        self.assertNotIn("set-window-option", command)
        run.assert_called_once()

    def test_remote_bell_sessions_only_lists_windows(self):
        run = Mock(return_value=Mock(returncode=0, stdout="work:0:!\nchat:1\nidle:0:-\n"))

        with patch("mtmux.discovery.subprocess.run", run):
            self.assertEqual(remote_bell_sessions("dev"), {"work", "chat"})

        remote_command = run.call_args.args[0][-1]
        self.assertIn("tmux list-windows", remote_command)
        self.assertNotIn("set-option", remote_command)
        self.assertNotIn("set-window-option", remote_command)
        run.assert_called_once()

    def test_bell_targets_includes_local_and_remote_sessions(self):
        def run(cmd, **kwargs):
            class Proc:
                returncode = 0
                stdout = "work:1\nidle:0\n"

            return Proc()

        with (
            patch("mtmux.discovery.subprocess.run", side_effect=run),
            patch("mtmux.discovery.load_hosts", return_value=["dev"]),
        ):
            self.assertEqual(bell_targets(), {"local:work", "ssh:dev:work"})


if __name__ == "__main__":
    unittest.main()
