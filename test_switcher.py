import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.switcher import _command, show_help, switch


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
        self.assertIn("Select a session from mtmux sidebar", calls[0][4])


if __name__ == "__main__":
    unittest.main()
