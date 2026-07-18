import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.switcher import _command, kill, show_help, switch


class SwitcherCommandTest(unittest.TestCase):
    def test_local_switch_unsets_tmux(self):
        self.assertEqual(
            _command(Target("local", "work")),
            "env -u TMUX tmux new-session -A -s work",
        )

    def test_remote_switch_uses_ssh(self):
        self.assertEqual(
            _command(Target("ssh", "work", "dev")),
            "ssh -t dev 'tmux new-session -A -s work'",
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
                ("respawn-pane", "-k", "-t", "%2", "env -u TMUX tmux new-session -A -s work"),
                ("select-pane", "-t", "%2"),
            ],
        )

    def test_show_help_respawns_right_pane(self):
        calls = []

        with (
            patch("mtmux.switcher._pane", return_value="%2"),
            patch("mtmux.switcher.tmux.tmux", side_effect=lambda *args, **kwargs: calls.append(args)),
        ):
            show_help()

        self.assertEqual(calls[0][:4], ("respawn-pane", "-k", "-t", "%2"))
        self.assertEqual(calls[1], ("select-pane", "-t", "%2"))
        self.assertIn("mtmux cockpit", calls[0][4])

    def test_kill_local_session(self):
        calls = []

        with patch("mtmux.switcher.subprocess.run", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
            kill(Target("local", "work"))

        self.assertEqual(calls, [((("tmux", "kill-session", "-t", "work"),), {"check": False})])

    def test_kill_remote_session(self):
        calls = []

        with patch("mtmux.switcher.subprocess.run", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
            kill(Target("ssh", "work", "dev"))

        self.assertEqual(calls, [((("ssh", "dev", "tmux kill-session -t work"),), {"check": False})])


if __name__ == "__main__":
    unittest.main()
