import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.sidebar import Entry, _current_target, _draw, _filter_key, _prompt, _read_key, _selected_index, _viewport, run


class FakeScreen:
    def __init__(self, keys=None, size=(5, 20)):
        self.calls = []
        self.keys = list(keys or [])
        self.key = ord("y")
        self.size = size

    def erase(self):
        self.calls.append(("erase",))

    def getmaxyx(self):
        return self.size

    def addnstr(self, *args):
        self.calls.append(("addnstr", *args))

    def addstr(self, *args):
        self.calls.append(("addstr", *args))

    def getch(self):
        self.calls.append(("getch",))
        if self.keys:
            return self.keys.pop(0)
        return self.key

    def refresh(self):
        self.calls.append(("refresh",))


class SidebarDrawTest(unittest.TestCase):
    def test_status_line_pads_shorter_message(self):
        screen = FakeScreen()

        _draw(screen, [Entry("LOCAL", "header")], 0, "created b", "")

        status_call = screen.calls[-2]
        self.assertEqual(status_call[0], "addnstr")
        self.assertEqual(status_call[3], "created b".ljust(19))

    def test_prompt_blanks_line_after_input(self):
        screen = FakeScreen([ord("b"), 10])

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertEqual(_prompt(screen, "session: "), "b")

        self.assertEqual(screen.calls[0], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-2], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-1], ("refresh",))

    def test_prompt_esc_cancels(self):
        screen = FakeScreen([27])

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertIsNone(_prompt(screen, "session: "))

    def test_read_key_gets_one_char_without_enter(self):
        screen = FakeScreen()

        self.assertEqual(_read_key(screen, "kill work? y/N"), ord("y"))

        self.assertEqual(screen.calls[1], ("addnstr", 4, 0, "kill work? y/N", 19))
        self.assertEqual(screen.calls[3], ("getch",))

    def test_filter_key_updates_live_text(self):
        self.assertEqual(_filter_key("a", ord("b")), "ab")
        self.assertEqual(_filter_key("ab", 127), "a")
        self.assertIsNone(_filter_key("ab", 10))

    def test_live_filter_refreshes_then_clears_after_switch(self):
        screen = FakeScreen([ord("/"), ord("w"), 10, ord("q")])
        calls = []
        target = Target("local", "work")

        def entries(filter_text=""):
            calls.append(filter_text)
            return [Entry("LOCAL", "header"), Entry("work", "session", target)]

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", side_effect=entries),
            patch("mtmux.sidebar.switch"),
        ):
            run(screen)

        self.assertEqual(calls, ["", "w", ""])

    def test_esc_clears_filter(self):
        screen = FakeScreen([ord("/"), ord("w"), 27, ord("q")])
        calls = []

        def entries(filter_text=""):
            calls.append(filter_text)
            return [Entry("LOCAL", "header"), Entry("work", "session", Target("local", "work"))]

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", side_effect=entries),
        ):
            run(screen)

        self.assertEqual(calls, ["", "w", ""])

    def test_ctrl_c_cancels_filter_without_exiting(self):
        screen = FakeScreen([ord("/"), ord("w"), 3, ord("q")])
        calls = []

        def entries(filter_text=""):
            calls.append(filter_text)
            return [Entry("LOCAL", "header"), Entry("work", "session", Target("local", "work"))]

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", side_effect=entries),
        ):
            run(screen)

        self.assertEqual(calls, ["", "w", ""])

    def test_rendered_rows_include_icons(self):
        screen = FakeScreen(size=(6, 30))

        with patch("mtmux.sidebar._ascii", return_value=False):
            _draw(screen, [Entry("LOCAL", "header"), Entry("work", "session", Target("local", "work")), Entry("new local", "create", host="")], 1, "ok", "")

        text = "\n".join(str(call) for call in screen.calls)
        self.assertIn("● work", text)
        self.assertIn("＋ new local", text)

    def test_selected_row_gets_selected_attr(self):
        screen = FakeScreen(size=(6, 30))

        with patch.dict("mtmux.sidebar._COLOR", {"selected": 123}, clear=True):
            _draw(screen, [Entry("LOCAL", "header"), Entry("work", "session", Target("local", "work"))], 1, "ok", "")

        self.assertTrue(any(call[0] == "addnstr" and len(call) > 5 and call[3].endswith("work") and call[5] == 123 for call in screen.calls))

    def test_scrolling_keeps_selected_visible(self):
        entries = [Entry(str(i), "session", Target("local", str(i))) for i in range(10)]

        start, end = _viewport(entries, 9, 5)

        self.assertLessEqual(start, 9)
        self.assertLess(9, end)

    def test_selected_index_prefers_current_target(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("notes", "session", Target("local", "notes")),
            Entry("work", "session", Target("local", "work")),
        ]

        self.assertEqual(_selected_index(entries, Target("local", "work")), 2)

    def test_current_target_falls_back_to_right_pane_command(self):
        def out(*args, **kwargs):
            if args[0] == "show-options":
                return ""
            return "env -u TMUX tmux new-session -A -s work"

        with patch("mtmux.sidebar.right_pane", return_value="%2"), patch("mtmux.sidebar.tmux.out", side_effect=out):
            self.assertEqual(_current_target(), Target("local", "work"))


if __name__ == "__main__":
    unittest.main()
