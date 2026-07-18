import unittest

from mtmux.names import Target
from mtmux.switcher import _command


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


if __name__ == "__main__":
    unittest.main()
