import unittest
from unittest.mock import patch

from mtmux.__main__ import main
from mtmux.names import Target


class MainTest(unittest.TestCase):
    def test_create_ssh_rejects_option_like_hosts(self):
        for host in ("-V", "-F", "--help"):
            with self.subTest(host=host):
                with patch("mtmux.__main__.sessions.create") as create:
                    with self.assertRaisesRegex(SystemExit, rf"Invalid host: {host!r}"):
                        main(["create", "ssh", "--", host, "work"])
                    create.assert_not_called()

    def test_create_local_keeps_option_like_session_support(self):
        target = Target("local", "-V")
        with (
            patch("mtmux.__main__.sessions.create") as create,
            patch("mtmux.__main__.sessions.attach_command", return_value="attach") as attach_command,
            patch("mtmux.__main__.cockpit.switch") as switch,
        ):
            main(["create", "local", "--", "-V"])

        create.assert_called_once_with(target)
        attach_command.assert_called_once_with(target)
        switch.assert_called_once_with(target, "attach")

    def test_failed_create_never_switches(self):
        with (
            patch("mtmux.__main__.sessions.create", side_effect=SystemExit("create failed")),
            patch("mtmux.__main__.cockpit.switch") as switch,
        ):
            with self.assertRaisesRegex(SystemExit, "create failed"):
                main(["create", "local", "work"])

        switch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
