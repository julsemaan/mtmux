import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.sidebar import _draw, _filter_key, _prompt, _read_key, run


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


class SidebarDrawTest(unittest.TestCase):
    def test_status_line_pads_shorter_message(self):
        screen = FakeScreen()

        _draw(screen, [("LOCAL", None, None)], 0, "created b", "")

        status_call = screen.calls[-2]
        self.assertEqual(status_call[0], "addnstr")
        self.assertEqual(status_call[3], "created b".ljust(19))

    def test_prompt_blanks_line_after_input(self):
        screen = FakeScreen()

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertEqual(_prompt(screen, "session: "), "b")

        self.assertEqual(screen.calls[0], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-2], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-1], ("refresh",))

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
            return [("LOCAL", None, None), ("  work", None, target)]

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._entries", side_effect=entries),
            patch("mtmux.sidebar.switch"),
        ):
            run(screen)

        self.assertEqual(calls, ["", "w", ""])


if __name__ == "__main__":
    unittest.main()
