import unittest
from unittest.mock import patch

from mtmux.sidebar import _draw, _prompt


class FakeScreen:
    def __init__(self):
        self.calls = []

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


if __name__ == "__main__":
    unittest.main()
