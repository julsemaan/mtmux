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

        self.assertEqual(cfg.read_text(), 'hosts = []\nprefix = "C-s"\n')
        self.assertNotIn("prefix", wrapper.read_text())
        self.assertNotIn("send-prefix", wrapper.read_text())

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


if __name__ == "__main__":
    unittest.main()
