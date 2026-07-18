import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mtmux import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.env = patch.dict("mtmux.config.os.environ", {"MTMUX_CONFIG_DIR": self.tempdir.name}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def write_config(self, text):
        path = Path(self.tempdir.name) / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_fresh_config_contains_default_prefix(self):
        cfg, wrapper = config.ensure_config()

        self.assertEqual(cfg.read_text(), 'hosts = []\nprefix = "C-s"\nsidebar_width = 40\n')
        self.assertNotIn("prefix", wrapper.read_text())
        self.assertNotIn("send-prefix", wrapper.read_text())
        self.assertIn("set -g mouse on", wrapper.read_text())

    def test_existing_wrapper_is_preserved(self):
        wrapper = Path(self.tempdir.name) / "wrapper.tmux.conf"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("set -g mouse off\n")

        config.ensure_config()

        self.assertEqual(wrapper.read_text(), "set -g mouse off\n")

    def test_missing_prefix_uses_default(self):
        self.write_config("hosts = []\n")

        self.assertEqual(config.load_prefix(), "C-s")

    def test_custom_prefix_loads(self):
        self.write_config('hosts = []\nprefix = "C-g"\n')

        self.assertEqual(config.load_prefix(), "C-g")

    def test_invalid_prefix_values_fail_clearly(self):
        for value in ("42", '""', '"C x"', '"C-\\t"'):
            with self.subTest(value=value):
                self.write_config(f"hosts = []\nprefix = {value}\n")
                with self.assertRaisesRegex(SystemExit, "prefix must be a non-empty, printable, whitespace-free string"):
                    config.load_prefix()

    def test_sidebar_width_defaults_to_40_and_accepts_custom_value(self):
        self.write_config("hosts = []\n")
        self.assertEqual(config.load_sidebar_width(), 40)

        self.write_config("sidebar_width = 52\n")
        self.assertEqual(config.load_sidebar_width(), 52)

    def test_invalid_sidebar_width_fails_clearly(self):
        for value in ("0", "-1", '"40"', "true"):
            with self.subTest(value=value):
                self.write_config(f"sidebar_width = {value}\n")
                with self.assertRaisesRegex(SystemExit, "sidebar_width must be a positive integer"):
                    config.load_sidebar_width()

    def test_missing_stars_file_loads_empty(self):
        self.assertEqual(config.load_stars(), set())

    def test_stars_ignore_blanks_and_parse_targets(self):
        stars = Path(self.tempdir.name) / "stars"
        stars.write_text("\nlocal:work\nssh:dev:notes\n\n")

        self.assertEqual(config.load_stars(), {config.parse_target("local:work"), config.parse_target("ssh:dev:notes")})

    def test_invalid_star_reports_file_context(self):
        stars = Path(self.tempdir.name) / "stars"
        stars.write_text("bad target\n")

        with self.assertRaisesRegex(SystemExit, rf"Invalid favorite in {stars}"):
            config.load_stars()

    def test_save_stars_sorts_targets(self):
        favorites = {config.parse_target("ssh:dev:work"), config.parse_target("local:notes")}

        config.save_stars(favorites)

        self.assertEqual((Path(self.tempdir.name) / "stars").read_text(), "local:notes\nssh:dev:work\n")


if __name__ == "__main__":
    unittest.main()
