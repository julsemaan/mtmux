import subprocess
import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.sessions import attach_command, create, kill


class SessionOperationsTest(unittest.TestCase):
    def test_attach_commands_quote_local_and_remote_targets(self):
        self.assertEqual(
            attach_command(Target("local", "work")),
            "env -u TMUX tmux -T clipboard new-session -A -s work",
        )
        self.assertEqual(
            attach_command(Target("ssh", "work", "dev")),
            "ssh -t dev 'tmux -T clipboard new-session -A -s work'",
        )

    def test_kill_local_session_uses_default_server(self):
        with (
            patch.dict("mtmux.sessions.os.environ", {"TMUX": "/tmp/mtmux,1,0", "PATH": "x"}, clear=True),
            patch("mtmux.sessions.subprocess.run") as run,
        ):
            kill(Target("local", "work"))

        run.assert_called_once_with(
            ("tmux", "kill-session", "-t", "work"),
            check=True,
            capture_output=True,
            text=True,
            env={"PATH": "x"},
        )

    def test_create_mutates_without_cockpit_dependency(self):
        target = Target("local", "work")
        with (
            patch.dict("mtmux.sessions.os.environ", {"TMUX": "/tmp/mtmux,1,0", "PATH": "x"}, clear=True),
            patch("mtmux.sessions.subprocess.run") as run,
        ):
            create(target)

        run.assert_called_once_with(
            ("tmux", "new-session", "-Ad", "-s", "work"),
            check=True,
            capture_output=True,
            text=True,
            env={"PATH": "x"},
        )

    def test_remote_create_and_kill_quote_session(self):
        target = Target("ssh", "work.one", "dev")
        with patch("mtmux.sessions.subprocess.run") as run:
            create(target)
            kill(target)

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ("ssh", "dev", "tmux new-session -Ad -s work.one"),
                ("ssh", "dev", "tmux kill-session -t work.one"),
            ],
        )

    def test_command_failures_include_operation_and_target(self):
        error = subprocess.CalledProcessError(1, ["command"], stderr="permission denied\n")
        for operation, action in (
            ("create", lambda: create(Target("local", "work"))),
            ("kill", lambda: kill(Target("ssh", "work", "dev"))),
        ):
            with self.subTest(operation=operation), patch("mtmux.sessions.subprocess.run", side_effect=error):
                with self.assertRaisesRegex(SystemExit, rf"^{operation} .* failed: permission denied$"):
                    action()


if __name__ == "__main__":
    unittest.main()
