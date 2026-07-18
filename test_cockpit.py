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
            patch.object(cockpit, "_install_layout_hooks") as install_layout_hooks,
            patch.object(cockpit, "_install_bindings") as install_bindings,
            patch.object(cockpit, "_install_bell_hook") as install_bell_hook,
        ):
            cockpit.ensure_cockpit()

        fix_layout.assert_called_once_with("%1")
        install_layout_hooks.assert_called_once_with("%1")
        install_bell_hook.assert_called_once_with()
        install_bindings.assert_called_once_with()

    def test_layout_hooks_repin_sidebar_after_attach_or_resize(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._install_layout_hooks("%1")

        command = "set-window-option -t mtmux:cockpit main-pane-width 30 ; select-pane -t %1 ; select-layout -t mtmux:cockpit main-vertical"
        self.assertEqual(
            calls,
            [
                ("set-hook", "-t", "mtmux", "client-attached", command),
                ("set-hook", "-t", "mtmux", "client-resized", command),
            ],
        )

    def test_bindings_include_sidebar_focus_shortcut(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._install_bindings()

        self.assertEqual(
            calls,
            [
                ("bind-key", "C-g", "send-prefix"),
                ("bind-key", "s", "run-shell", cockpit.FOCUS_SIDEBAR),
            ],
        )

    def test_install_bell_hook_enables_outer_tmux_bells(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._install_bell_hook()

        self.assertEqual(
            calls,
            [
                ("set-window-option", "-t", "mtmux:cockpit", "monitor-bell", "on"),
                ("set-option", "-t", "mtmux", "bell-action", "any"),
                (
                    "set-hook",
                    "-t",
                    "mtmux",
                    "alert-bell",
                    "set-option -F -t mtmux @mtmux_bell_target '#{@mtmux_current_target}'",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
