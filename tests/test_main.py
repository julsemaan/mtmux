import unittest
from unittest.mock import patch

from mtmux.__main__ import main


class MainTest(unittest.TestCase):
    def test_create_ssh_rejects_option_like_hosts(self):
        for host in ("-V", "-F", "--help"):
            with self.subTest(host=host):
                with patch("mtmux.__main__.create_remote") as create_remote:
                    with self.assertRaisesRegex(SystemExit, rf"Invalid host: {host!r}"):
                        main(["create", "ssh", "--", host, "work"])
                    create_remote.assert_not_called()

    def test_create_local_keeps_option_like_session_support(self):
        with patch("mtmux.__main__.create_local") as create_local:
            main(["create", "local", "--", "-V"])

        create_local.assert_called_once_with("-V")


if __name__ == "__main__":
    unittest.main()
