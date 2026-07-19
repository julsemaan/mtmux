import unittest

from mtmux.names import Target


class TargetTest(unittest.TestCase):
    def test_accepts_valid_local_and_ssh_targets(self):
        self.assertEqual(Target("local", "-V").format(), "local:-V")
        self.assertEqual(Target("ssh", "work", "dev").format(), "ssh:dev:work")

    def test_rejects_invalid_construction(self):
        cases = (
            (("other", "work", None), "Invalid target kind"),
            (("local", "bad name", None), "Invalid session"),
            (("local", "work", "dev"), "Local target must not have host"),
            (("ssh", "work", None), "Invalid host"),
            (("ssh", "work", "-V"), "Invalid host"),
        )
        for args, message in cases:
            with self.subTest(args=args), self.assertRaisesRegex(SystemExit, message):
                Target(*args)


if __name__ == "__main__":
    unittest.main()
