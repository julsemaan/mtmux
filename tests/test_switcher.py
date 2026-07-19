import subprocess
import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.switcher import _command, create_local, create_remote, kill, show_help, switch


class SwitcherCommandTest(unittest.TestCase):
    def test_local_switch_unsets_tmux(self):
        self.assertEqual(
            _command(Target("local", "work")),
            "env -u TMUX tmux -T clipboard new-session -A -s work",
        )

    def test_remote_switch_uses_ssh(self):
        self.assertEqual(
            _command(Target("ssh", "work", "dev")),
            "ssh -t dev 'tmux -T clipboard new-session -A -s work'",
        )

    def test_switch_selects_right_pane_after_respawn(self):
        calls = []

        with (
            patch("mtmux.switcher._pane", return_value="%2"),
            patch("mtmux.switcher.tmux.tmux", side_effect=lambda *args, **kwargs: calls.append(args)),
        ):
            switch(Target("local", "work"))

        self.assertEqual(
            calls,
            [
                ("set-option", "-t", "mtmux", "@mtmux_current_target", "local:work"),
                ("set-option", "-u", "-t", "mtmux", "@mtmux_bell_target"),
                ("respawn-pane", "-k", "-t", "%2", "env -u TMUX tmux -T clipboard new-session -A -s work"),
                ("select-pane", "-t", "%2"),
            ],
        )

    def test_show_help_respawns_right_pane_without_leaving_sidebar(self):
        calls = []

        with (
            patch("mtmux.switcher._pane", return_value="%2"),
            patch("mtmux.switcher.load_prefix", return_value="C-x") as load_prefix,
            patch("mtmux.switcher.tmux.tmux", side_effect=lambda *args, **kwargs: calls.append(args)),
        ):
            show_help()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:4], ("respawn-pane", "-k", "-t", "%2"))
        self.assertIn("mtmux cockpit", calls[0][4])
        self.assertIn("C-x s  focus/open sidebar", calls[0][4])
        load_prefix.assert_called_once_with()

    def test_kill_local_session_uses_default_server(self):
        calls = []

        with (
            patch.dict("mtmux.switcher.os.environ", {"TMUX": "/tmp/mtmux,1,0", "PATH": "x"}, clear=True),
            patch("mtmux.switcher.subprocess.run", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))),
        ):
            kill(Target("local", "work"))

        self.assertEqual(
            calls,
            [((("tmux", "kill-session", "-t", "work"),), {"check": True, "capture_output": True, "text": True, "env": {"PATH": "x"}})],
        )

    def test_create_local_session_uses_default_server(self):
        calls = []

        with (
            patch.dict("mtmux.switcher.os.environ", {"TMUX": "/tmp/mtmux,1,0", "PATH": "x"}, clear=True),
            patch("mtmux.switcher.subprocess.run", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))),
            patch("mtmux.switcher.switch"),
        ):
            create_local("work")

        self.assertEqual(
            calls,
            [((["tmux", "new-session", "-Ad", "-s", "work"],), {"check": True, "capture_output": True, "text": True, "env": {"PATH": "x"}})],
        )

    def test_kill_remote_session(self):
        calls = []

        with patch("mtmux.switcher.subprocess.run", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
            kill(Target("ssh", "work", "dev"))

        self.assertEqual(
            calls,
            [((("ssh", "dev", "tmux kill-session -t work"),), {"check": True, "capture_output": True, "text": True})],
        )

    def test_command_failures_exit_with_operation_target_and_reason(self):
        cases = (
            ("create", "local:work", lambda: create_local("work")),
            ("create", "ssh:dev:work", lambda: create_remote("dev", "work")),
            ("kill", "local:work", lambda: kill(Target("local", "work"))),
            ("kill", "ssh:dev:work", lambda: kill(Target("ssh", "work", "dev"))),
        )
        error = subprocess.CalledProcessError(1, ["command"], stderr="permission denied\n")

        for operation, target, action in cases:
            with self.subTest(operation=operation, target=target):
                with patch("mtmux.switcher.subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(
                        SystemExit,
                        rf"^{operation} {target} failed: permission denied$",
                    ):
                        action()


if __name__ == "__main__":
    unittest.main()
