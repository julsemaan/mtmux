import curses
import unittest
from unittest.mock import patch

from mtmux.names import Target
from mtmux.sidebar import (
    Entry,
    _bell_targets,
    _current_target,
    _draw,
    _fade,
    _filter_key,
    _pane_active,
    _prompt,
    _read_key,
    _selected_before,
    _selected_index,
    _viewport,
    main,
    run,
)


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

    def attron(self, *args):
        self.calls.append(("attron", *args))

    def attroff(self, *args):
        self.calls.append(("attroff", *args))

    def getch(self):
        self.calls.append(("getch",))
        if self.keys:
            return self.keys.pop(0)
        return self.key

    def refresh(self):
        self.calls.append(("refresh",))

    def timeout(self, *args):
        self.calls.append(("timeout", *args))


class SidebarDrawTest(unittest.TestCase):
    def test_inactive_sidebar_dims_existing_colors(self):
        faded = _fade(curses.A_COLOR | curses.A_BOLD)

        self.assertEqual(faded & curses.A_COLOR, curses.A_COLOR)
        self.assertTrue(faded & curses.A_DIM)
        self.assertTrue(faded & curses.A_BOLD)

    def test_pane_active_reads_current_tmux_pane_state(self):
        with patch.dict("mtmux.sidebar.os.environ", {"TMUX_PANE": "%1"}), patch(
            "mtmux.sidebar.tmux.out", return_value="1"
        ) as out:
            self.assertTrue(_pane_active())

        out.assert_called_once_with("display-message", "-p", "-t", "%1", "#{pane_active}", check=False)

    def test_main_restarts_after_keyboard_interrupt(self):
        with patch("mtmux.sidebar.curses.wrapper", side_effect=[KeyboardInterrupt, None]) as wrapper:
            self.assertEqual(main(), 0)

        self.assertEqual(wrapper.call_count, 2)

    def test_status_line_pads_shorter_message(self):
        screen = FakeScreen()

        _draw(screen, [Entry("LOCAL", "header")], 0, "created b", "")

        status_call = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 4)
        self.assertEqual(status_call[3], "created b".ljust(19))

    def test_long_footer_wraps_and_reserves_bottom_rows_at_40_columns(self):
        screen = FakeScreen(size=(6, 40))
        entries = [Entry(str(i), "session", Target("local", str(i))) for i in range(8)]
        status = "↵ switch  n new  x kill  / filter  r refresh  ? help"

        _draw(screen, entries, 0, status, "")

        footer_calls = [call for call in screen.calls if call[0] == "addnstr" and call[1] in (4, 5)]
        self.assertEqual([call[1] for call in footer_calls], [4, 5])
        self.assertIn("refresh  ? help", "".join(call[3] for call in footer_calls))
        self.assertFalse(any(call[0] == "addnstr" and call[1] >= 4 and call[3].lstrip().startswith(tuple(str(i) for i in range(8))) for call in screen.calls))

    def test_prompt_blanks_line_after_input(self):
        screen = FakeScreen([ord("b"), 10])

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertEqual(_prompt(screen, "session: "), "b")

        self.assertEqual(screen.calls[1], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-3], ("addnstr", 4, 0, " " * 19, 19))
        self.assertEqual(screen.calls[-2], ("refresh",))

    def test_prompt_uses_blocking_input_despite_sidebar_timeout(self):
        screen = FakeScreen([ord("y"), 10])

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertEqual(_prompt(screen, "session: "), "y")

        self.assertEqual(screen.calls[0], ("timeout", -1))
        self.assertEqual(screen.calls[-1], ("timeout", 500))

    def test_prompt_esc_cancels(self):
        screen = FakeScreen([27])

        with patch("mtmux.sidebar.curses.echo"), patch("mtmux.sidebar.curses.noecho"):
            self.assertIsNone(_prompt(screen, "session: "))

    def test_read_key_gets_one_char_without_enter(self):
        screen = FakeScreen()

        self.assertEqual(_read_key(screen, "kill work? y/N"), ord("y"))

        self.assertEqual(screen.calls[2], ("addnstr", 4, 0, "kill work? y/N", 19))
        self.assertEqual(screen.calls[4], ("getch",))
        self.assertEqual(screen.calls[0], ("timeout", -1))
        self.assertEqual(screen.calls[-1], ("timeout", 500))

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
            self.assertEqual(_current_target(), Target("local", "work"))

        out.assert_called_once_with("show-options", "-v", "-t", "mtmux", "@mtmux_current_target", check=False)

    def test_draw_marks_matching_bell_target(self):
        screen = FakeScreen()
        target = Target("ssh", "work", "dev")

        _draw(screen, [Entry("work", "session", target)], 0, "", "", bell_targets={"ssh:dev:work"})

        self.assertTrue(any(call[0] == "addnstr" and "work 🔔" in call[3] for call in screen.calls))

    def test_draw_does_not_mark_current_target_bell(self):
        screen = FakeScreen()
        target = Target("local", "work")

        _draw(screen, [Entry("work", "session", target)], 0, "", "", bell_targets={"local:work"}, current_target=target)

        self.assertFalse(any(call[0] == "addnstr" and "🔔" in call[3] for call in screen.calls))

    def test_default_footer_fits_one_40_column_row(self):
        screen = FakeScreen([ord("q")], size=(6, 40))

        with (
            patch("mtmux.sidebar._ascii", return_value=False),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        footer_calls = [call for call in screen.calls if call[0] == "addnstr" and call[1] == 5]
        self.assertTrue(any(call[3].rstrip() == "↵ switch n new x kill / filter ? help" for call in footer_calls))

    def test_run_sets_timeout_and_refreshes_on_timeout(self):
        screen = FakeScreen([-1, ord("q")])
        calls = []

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", side_effect=lambda filter_text="": calls.append(filter_text) or [Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
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
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", target)]),
            patch("mtmux.sidebar._bell_targets", return_value={"local:work"}),
            patch("mtmux.sidebar._current_target", return_value=Target("local", "shell")),
        ):
            run(screen)

        beep.assert_called_once_with()

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
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
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
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
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
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
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

    def test_selected_before_picks_previous_selectable_row(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("notes", "session", Target("local", "notes")),
            Entry("new local", "create", host=""),
        ]

        self.assertEqual(_selected_before(entries, 2), 1)

    def test_current_target_falls_back_to_right_pane_command(self):
        def out(*args, **kwargs):
            if args[0] == "show-options":
                return ""
            return "env -u TMUX tmux new-session -A -s work"

        with patch("mtmux.sidebar.right_pane", return_value="%2"), patch("mtmux.sidebar.tmux.out", side_effect=out):
            self.assertEqual(_current_target(), Target("local", "work"))


if __name__ == "__main__":
    unittest.main()
