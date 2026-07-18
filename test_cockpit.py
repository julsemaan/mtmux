import unittest
from unittest.mock import patch

from mtmux import cockpit


class CockpitLayoutTest(unittest.TestCase):
    def test_fix_layout_pins_sidebar_to_30_columns(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._fix_layout("%1")

        self.assertEqual(
            calls,
            [
                ("set-window-option", "-t", cockpit.TARGET, "main-pane-width", "30"),
                ("select-pane", "-t", "%1"),
                ("select-layout", "-t", cockpit.TARGET, "main-vertical"),
            ],
        )

    def test_existing_cockpit_gets_layout_reapplied(self):
        with (
            patch.object(cockpit, "_valid", return_value=True),
            patch.object(cockpit, "_option", return_value="%1"),
            patch.object(cockpit, "_fix_layout") as fix_layout,
        ):
            cockpit.ensure_cockpit()

        fix_layout.assert_called_once_with("%1")


if __name__ == "__main__":
    unittest.main()
