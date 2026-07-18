import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.sidebar import _bell_targets, _current_target, _draw, _filter_key, _prompt, _read_key, run


class FakeScreen:
    def __init__(self, keys=None):
        self.calls = []
        self.keys = list(keys or [])
        self.key = ord("y")

    def erase(self):
        self.calls.append(("erase",))

    def getmaxyx(self):
        return (5, 20)

    def addnstr(self, *args):
        self.calls.append(("addnstr", *args))

    def addstr(self, *args):
        self.calls.append(("addstr", *args))

    def getstr(self, *args):
        self.calls.append(("getstr", *args))
        return b"b"

    def getch(self):
        self.calls.append(("getch",))
        if self.keys:
            return self.keys.pop(0)
        return self.key

    def move(self, *args):
        self.calls.append(("move", *args))

    def clrtoeol(self):
        self.calls.append(("clrtoeol",))

    def refresh(self):
        self.calls.append(("refresh",))

    def timeout(self, *args):
        self.calls.append(("timeout", *args))


class SidebarDrawTest(unittest.TestCase):
    def test_status_line_pads_shorter_message(self):
        screen = FakeScreen()

        _draw(screen, [("LOCAL", None, None)], 0, "created b", "", "")

        status_call = screen.calls[-2]
        self.assertEqual(status_call[0], "addnstr")
        self.assertEqual(status_call[3], "created b".ljust(19))

    def test_prompt_blanks_line_after_input(self):
        screen = FakeScreen()

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertEqual(_prompt(screen, "session: "), "b")

        self.assertEqual(screen.calls[1], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-3], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-2], ("refresh",))

    def test_prompt_uses_blocking_input_despite_sidebar_timeout(self):
        screen = FakeScreen()

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertEqual(_prompt(screen, "session: "), "b")

        self.assertEqual(screen.calls[0], ("timeout", -1))
        self.assertEqual(screen.calls[-1], ("timeout", 500))

    def test_read_key_gets_one_char_without_enter(self):
        screen = FakeScreen()

        self.assertEqual(_read_key(screen, "kill work? y/N"), ord("y"))

        self.assertEqual(screen.calls[1], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[2], ("addnstr", 4, 0, "kill work? y/N", 19))
        self.assertEqual(screen.calls[4], ("getch",))

    def test_filter_key_updates_live_text(self):
        self.assertEqual(_filter_key("a", ord("b")), "ab")
        self.assertEqual(_filter_key("ab", 127), "a")
        self.assertIsNone(_filter_key("ab", 10))

    def test_bell_targets_reads_tmux_option_and_tmux_flags(self):
        with (
            patch("mtmux.sidebar.tmux.out", return_value="local:work") as out,
            patch("mtmux.sidebar.discovered_bell_targets", return_value={"ssh:dev:chat"}),
        ):
            self.assertEqual(_bell_targets(), {"local:work", "ssh:dev:chat"})

        out.assert_called_once_with("show-options", "-v", "-t", "mtmux", "@mtmux_bell_target", check=False)

    def test_current_target_reads_tmux_option(self):
        with patch("mtmux.sidebar.tmux.out", return_value="local:work") as out:
            self.assertEqual(_current_target(), "local:work")

        out.assert_called_once_with("show-options", "-v", "-t", "mtmux", "@mtmux_current_target", check=False)

    def test_draw_marks_matching_bell_target(self):
        screen = FakeScreen()
        target = Target("ssh", "work", "dev")

        _draw(screen, [("REMOTE dev", None, None), ("  work", None, target)], 1, "", "", {"ssh:dev:work"}, "local:shell")

        self.assertIn(("addnstr", 2, 0, "  work 🔔", 19, 262144), screen.calls)

    def test_draw_does_not_mark_current_target_bell(self):
        screen = FakeScreen()
        target = Target("local", "work")

        _draw(screen, [("  work", None, target)], 0, "", "", {"local:work"}, "local:work")

        self.assertIn(("addnstr", 1, 0, "  work", 19, 262144), screen.calls)
        self.assertNotIn(("addnstr", 1, 0, "  work 🔔", 19, 262144), screen.calls)

    def test_run_sets_timeout_and_refreshes_on_timeout(self):
        screen = FakeScreen([-1, ord("q")])
        calls = []

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._entries", side_effect=lambda filter_text="": calls.append(filter_text) or [("LOCAL", None, None)]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=""),
        ):
            run(screen)

        self.assertIn(("timeout", 500), screen.calls)
        self.assertEqual(calls, ["", ""])

    def test_run_beeps_once_for_new_background_bell(self):
        screen = FakeScreen([ord("q")])
        target = Target("local", "work")

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.beep") as beep,
            patch("mtmux.sidebar._entries", return_value=[("  work", None, target)]),
            patch("mtmux.sidebar._bell_targets", return_value={"local:work"}),
            patch("mtmux.sidebar._current_target", return_value="local:shell"),
        ):
            run(screen)

        beep.assert_called_once_with()

    def test_live_filter_refreshes_then_clears_after_switch(self):
        screen = FakeScreen([ord("/"), ord("w"), 10, ord("q")])
        calls = []
        target = Target("local", "work")

        def entries(filter_text=""):
            calls.append(filter_text)
            return [("LOCAL", None, None), ("  work", None, target)]

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._entries", side_effect=entries),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=""),
            patch("mtmux.sidebar.switch"),
        ):
            run(screen)

        self.assertEqual(calls, ["", "w", ""])


if __name__ == "__main__":
    unittest.main()
