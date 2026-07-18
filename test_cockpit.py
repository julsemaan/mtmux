import unittest
from unittest.mock import patch

from mtmux import cockpit


class CockpitLayoutTest(unittest.TestCase):
    def test_fix_layout_pins_sidebar_to_40_columns(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._fix_layout("%1")

        self.assertEqual(
            calls,
            [
                ("set-window-option", "-t", cockpit.TARGET, "main-pane-width", "40"),
                ("set-window-option", "-u", "-t", cockpit.TARGET, "window-style"),
                ("set-window-option", "-u", "-t", cockpit.TARGET, "window-active-style"),
                ("set-window-option", "-t", cockpit.TARGET, "pane-border-style", "fg=terminal"),
                ("set-window-option", "-t", cockpit.TARGET, "pane-active-border-style", "fg=terminal"),
                ("set-window-option", "-t", cockpit.TARGET, "pane-border-lines", "single"),
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
            patch.object(cockpit, "_enable_mouse") as enable_mouse,
            patch.object(cockpit, "_enable_clipboard") as enable_clipboard,
            patch.object(cockpit, "_install_bell_hook") as install_bell_hook,
            patch.object(cockpit, "_install_right_pane_reset") as install_right_pane_reset,
            patch.object(cockpit, "load_prefix", return_value="C-x"),
            patch.object(cockpit.tmux, "tmux") as tmux_call,
        ):
            cockpit.ensure_cockpit()

        fix_layout.assert_called_once_with("%1")
        install_layout_hooks.assert_called_once_with("%1")
        install_bell_hook.assert_called_once_with()
        install_right_pane_reset.assert_called_once_with("%1", "%1", "C-x")
        install_bindings.assert_called_once_with("C-x")
        enable_mouse.assert_called_once_with()
        enable_clipboard.assert_called_once_with()
        tmux_call.assert_called_once_with("set-option", "-t", "mtmux", "prefix", "C-x")

    def test_layout_hooks_repin_sidebar_after_attach_or_resize(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._install_layout_hooks("%1")

        command = "set-window-option -t mtmux:cockpit main-pane-width 40 ; select-pane -t %1 ; select-layout -t mtmux:cockpit main-vertical"
        self.assertEqual(
            calls,
            [
                ("set-hook", "-t", "mtmux", "client-attached", command),
                ("set-hook", "-t", "mtmux", "client-resized", command),
            ],
        )

    def test_enable_mouse_sets_runtime_session_option(self):
        with patch.object(cockpit.tmux, "tmux") as tmux_call:
            cockpit._enable_mouse()

        tmux_call.assert_called_once_with("set-option", "-t", "mtmux", "mouse", "on")

    def test_enable_clipboard_sets_runtime_server_option(self):
        with patch.object(cockpit.tmux, "tmux") as tmux_call:
            cockpit._enable_clipboard()

        tmux_call.assert_called_once_with("set-option", "-s", "set-clipboard", "on")

    def test_bindings_include_sidebar_focus_shortcut(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._install_bindings("C-x")

        self.assertEqual(
            calls,
            [
                ("bind-key", "C-x", "send-prefix"),
                ("bind-key", "s", "run-shell", cockpit.FOCUS_SIDEBAR),
            ],
        )

    def test_right_pane_reset_restores_startup_help_and_focuses_sidebar(self):
        calls = []

        with patch.object(cockpit.tmux, "tmux", side_effect=lambda *args, **kwargs: calls.append(args)):
            cockpit._install_right_pane_reset("%1", "%2", "C-x")

        command = f"if-shell -F '#{{==:#{{hook_pane}},%2}}' {{ set-option -u -t mtmux @mtmux_current_target ; set-option -u -t mtmux @mtmux_bell_target ; respawn-pane -k -t %2 {cockpit.shlex.quote(cockpit.help_command('C-x'))} ; select-pane -t %1 }}"
        self.assertEqual(
            calls,
            [
                ("set-option", "-p", "-t", "%2", "remain-on-exit", "on"),
                ("set-hook", "-t", "mtmux", "pane-died", command),
            ],
        )

    def test_help_uses_configured_prefix(self):
        command = cockpit.help_command("C-x")

        self.assertIn("C-x s  focus/open sidebar", command)
        self.assertIn("C-x d  detach cockpit", command)

    def test_new_cockpit_sets_configured_prefix_and_startup_help(self):
        calls = []

        def tmux_call(*args, **kwargs):
            calls.append((args, kwargs))
            return type("Result", (), {"returncode": 1})()

        with (
            patch.object(cockpit, "ensure_config", return_value=(None, "wrapper")),
            patch.object(cockpit.tmux, "tmux", side_effect=tmux_call),
            patch.object(cockpit.tmux, "out", side_effect=["%2", "%1"]),
            patch.object(cockpit, "_fix_layout"),
            patch.object(cockpit, "_set_markers"),
            patch.object(cockpit, "_install_layout_hooks"),
            patch.object(cockpit, "_install_bell_hook"),
            patch.object(cockpit, "_install_right_pane_reset"),
            patch.object(cockpit, "_install_bindings"),
            patch.object(cockpit, "_enable_clipboard") as enable_clipboard,
        ):
            cockpit._build("C-x")

        enable_clipboard.assert_called_once_with()
        self.assertIn((("set-option", "-t", "mtmux", "prefix", "C-x"), {}), calls)
        self.assertIn((("set-option", "-t", "mtmux", "mouse", "on"), {}), calls)
        new_session = next(args for args, _ in calls if args[0] == "new-session")
        self.assertIn("C-x s  focus/open sidebar", new_session[-1])

    def test_missing_sidebar_recreation_reapplies_mouse(self):
        with (
            patch.object(cockpit, "load_prefix", return_value="C-x"),
            patch.object(cockpit, "_valid", return_value=False),
            patch.object(cockpit, "_option", side_effect=lambda name: "1" if name == "@mtmux_cockpit" else "%2"),
            patch.object(cockpit.tmux, "has_pane", return_value=True),
            patch.object(cockpit.tmux, "out", return_value="%1"),
            patch.object(cockpit.tmux, "tmux"),
            patch.object(cockpit, "_fix_layout"),
            patch.object(cockpit, "_set_markers"),
            patch.object(cockpit, "_install_layout_hooks"),
            patch.object(cockpit, "_install_bell_hook"),
            patch.object(cockpit, "_install_right_pane_reset"),
            patch.object(cockpit, "_install_bindings"),
            patch.object(cockpit, "_enable_mouse") as enable_mouse,
            patch.object(cockpit, "_enable_clipboard") as enable_clipboard,
        ):
            cockpit.ensure_cockpit()

        enable_mouse.assert_called_once_with()
        enable_clipboard.assert_called_once_with()

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
