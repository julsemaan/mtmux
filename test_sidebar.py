import curses
import unittest
from unittest.mock import patch

from mtmux.discovery import RemoteSnapshot
from mtmux.names import Target
from mtmux.sidebar import (
    Entry,
    _bell_targets,
    _current_target,
    _draw,
    _fade,
    _entries,
    _entry_at_row,
    _filter_key,
    _mouse_mask,
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

    def clear(self):
        self.calls.append(("clear",))

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

    def move(self, *args):
        self.calls.append(("move", *args))

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

    def test_mouse_mask_registers_only_supported_events(self):
        expected = (
            curses.BUTTON1_PRESSED
            | curses.BUTTON1_CLICKED
            | curses.BUTTON1_DOUBLE_CLICKED
            | curses.BUTTON4_PRESSED
            | getattr(curses, "BUTTON5_PRESSED", 0)
        )
        with patch("mtmux.sidebar.curses.mousemask") as mousemask:
            _mouse_mask()

        mousemask.assert_called_once_with(expected)

    def test_mouse_mask_tolerates_missing_button5(self):
        with patch.object(curses, "BUTTON5_PRESSED", None), patch("mtmux.sidebar.curses.mousemask") as mousemask:
            _mouse_mask()

        self.assertFalse(mousemask.call_args.args[0] & 2097152)

    def test_entry_at_row_maps_visible_and_scrolled_rows(self):
        entries = [Entry(str(i), "session", Target("local", str(i))) for i in range(10)]

        self.assertEqual(_entry_at_row(entries, 0, 1, 8, 1), 0)
        start, _ = _viewport(entries, 9, 8)
        self.assertEqual(_entry_at_row(entries, 9, 2, 8, 1), start)

    def test_entry_at_row_ignores_non_selectable_and_non_entry_areas(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("offline", "unavailable"),
            Entry("work", "session", Target("local", "work")),
            Entry("new", "create", host=""),
            *[Entry(str(i), "session", Target("local", str(i))) for i in range(6)],
        ]

        self.assertIsNone(_entry_at_row(entries, 2, 0, 7, 1))  # title
        self.assertIsNone(_entry_at_row(entries, 2, 1, 7, 1))  # up marker
        self.assertIsNone(_entry_at_row(entries, 0, 1, 8, 1))  # header
        self.assertIsNone(_entry_at_row(entries, 0, 2, 8, 1))  # unavailable
        self.assertIsNone(_entry_at_row(entries, 0, 6, 7, 1))  # footer/down marker

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

    def test_title_adds_terminal_emoji_with_ascii_fallback(self):
        screen = FakeScreen(size=(5, 40))

        with patch("mtmux.sidebar._ascii", return_value=False):
            _draw(screen, [], 0, "ok", "")
        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].startswith(" 🖥️ MTMUX"))

        screen = FakeScreen(size=(5, 40))
        with patch("mtmux.sidebar._ascii", return_value=True):
            _draw(screen, [], 0, "ok", "")
        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].startswith(" MTMUX"))

    def test_draw_forces_full_repaint_so_shrinking_session_count_does_not_leave_digits(self):
        screen = FakeScreen(size=(5, 40))

        _draw(screen, [], 0, "ok", "")

        self.assertEqual(screen.calls[0], ("clear",))

    def test_normal_title_shows_brand_and_session_count(self):
        screen = FakeScreen(size=(5, 40))
        entries = [
            Entry("LOCAL", "header"),
            Entry("work", "session", Target("local", "work")),
            Entry("notes", "session", Target("local", "notes")),
            Entry("new local", "create", host=""),
        ]

        _draw(screen, entries, 1, "ok", "")

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(title[3], " 🖥️ MTMUX" + " " * 21 + "2 sessions")

    def test_title_count_uses_singular_labels(self):
        screen = FakeScreen(size=(5, 40))
        entries = [Entry("work", "session", Target("local", "work"))]

        _draw(screen, entries, 0, "ok", "")
        normal = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(normal[3].endswith("1 session"))

        screen = FakeScreen(size=(5, 40))
        _draw(screen, entries, 0, "filtering", "work", filtering=True)
        filtering = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(filtering[3].rstrip(), " 🖥️ MTMUX / work                 1 match")

    def test_filter_keeps_brand_query_count_and_cursor(self):
        screen = FakeScreen(size=(5, 40))
        entries = [Entry("work", "session", Target("local", "work"))]

        _draw(screen, entries, 0, "filtering", "work", filtering=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(title[3].rstrip(), " 🖥️ MTMUX / work                 1 match")
        self.assertIn(("move", 0, len(" 🖥️ MTMUX / work")), screen.calls)

    def test_empty_filter_has_visible_input_position(self):
        screen = FakeScreen(size=(5, 20))

        _draw(screen, [], 0, "filtering", "", filtering=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].startswith(" 🖥️ MTMUX / "))
        self.assertIn(("move", 0, len(" 🖥️ MTMUX / ")), screen.calls)

    def test_narrow_filter_drops_count_before_clipping_query(self):
        screen = FakeScreen(size=(5, 16))

        _draw(screen, [Entry("work", "session", Target("local", "work"))], 0, "filtering", "abcdefghij", filtering=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(title[3], " 🖥️ MTMUX / abcd")
        self.assertNotIn("match", title[3])
        cursor = next(call for call in screen.calls if call[0] == "move")
        self.assertEqual(cursor, ("move", 0, 15))
        self.assertLessEqual(cursor[2], 15)

    def test_title_colors_final_terminal_column(self):
        screen = FakeScreen(size=(5, 20))

        _draw(screen, [], 0, "ok", "")

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(len(title[3]), 20)
        self.assertEqual(title[4], 20)

    def test_title_uses_configured_style_and_dims_inactive_pane(self):
        screen = FakeScreen(size=(5, 20))

        with patch.dict("mtmux.sidebar._COLOR", {"title": 123}, clear=True):
            _draw(screen, [], 0, "ok", "", dimmed=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(title[4], 20)
        self.assertEqual(title[5], _fade(123))

    def test_title_monochrome_fallback_is_bold_reverse_video(self):
        screen = FakeScreen(size=(5, 20))

        with patch.dict("mtmux.sidebar._COLOR", {}, clear=True):
            _draw(screen, [], 0, "ok", "")

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[5] & curses.A_BOLD)
        self.assertTrue(title[5] & curses.A_REVERSE)

    def test_filter_key_updates_live_text(self):
        self.assertEqual(_filter_key("a", ord("b")), "ab")
        self.assertEqual(_filter_key("ab", 127), "a")
        self.assertIsNone(_filter_key("ab", 10))

    def test_bell_targets_reads_tmux_option_and_tmux_flags(self):
        with (
            patch("mtmux.sidebar.tmux.out", return_value="local:work") as out,
            patch("mtmux.sidebar.local_bell_sessions", return_value={"work"}),
        ):
            self.assertEqual(
                _bell_targets({"dev": RemoteSnapshot(True, ("chat",), frozenset({"chat"}))}),
                {"local:work", "ssh:dev:chat"},
            )

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
        self.assertTrue(any(call[3].rstrip() == "↵ go f star n new x kill / ?" for call in footer_calls))

    def test_run_sets_timeout_and_refreshes_on_timeout(self):
        screen = FakeScreen([-1, ord("q")])
        calls = []

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", side_effect=lambda filter_text="", *_: calls.append(filter_text) or [Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        self.assertIn(("timeout", 500), screen.calls)
        self.assertEqual(calls, [""])

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

    def test_single_click_selects_row(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("one", "session", Target("local", "one")),
            Entry("two", "session", Target("local", "two")),
        ]
        screen = FakeScreen([curses.KEY_MOUSE, 10, ord("q")], size=(8, 30))

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.mousemask"),
            patch("mtmux.sidebar.curses.getmouse", return_value=(0, 0, 3, 0, curses.BUTTON1_CLICKED)),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=entries),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
            patch("mtmux.sidebar.switch") as switch,
        ):
            run(screen)

        switch.assert_called_once_with(Target("local", "two"))

    def test_double_click_reuses_switch_path(self):
        target = Target("local", "work")
        screen = FakeScreen([curses.KEY_MOUSE, ord("q")], size=(8, 30))

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.mousemask"),
            patch("mtmux.sidebar.curses.getmouse", return_value=(0, 0, 1, 0, curses.BUTTON1_DOUBLE_CLICKED)),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", target)]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
            patch("mtmux.sidebar.switch") as switch,
        ):
            run(screen)

        switch.assert_called_once_with(target)

    def test_wheel_reuses_wrapping_navigation(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("one", "session", Target("local", "one")),
            Entry("two", "session", Target("local", "two")),
        ]
        screen = FakeScreen([curses.KEY_MOUSE, 10, ord("q")], size=(8, 30))

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.mousemask"),
            patch("mtmux.sidebar.curses.getmouse", return_value=(0, 0, 0, 0, curses.BUTTON4_PRESSED)),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=entries),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
            patch("mtmux.sidebar.switch") as switch,
        ):
            run(screen)

        switch.assert_called_once_with(Target("local", "two"))

    def test_malformed_mouse_event_is_ignored(self):
        screen = FakeScreen([curses.KEY_MOUSE, ord("q")])
        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.mousemask"),
            patch("mtmux.sidebar.curses.getmouse", side_effect=[(0, 0, None, 0, None), curses.error()]),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

    def test_live_filter_refreshes_then_clears_after_switch(self):
        screen = FakeScreen([ord("/"), ord("w"), 10, ord("q")])
        calls = []
        target = Target("local", "work")

        def entries(filter_text="", *_):
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

        def entries(filter_text="", *_):
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

        def entries(filter_text="", *_):
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

    def test_starred_entries_are_first_sorted_duplicated_and_stale(self):
        local = ["work"]
        remote = {"dev": RemoteSnapshot(True, ("notes",), frozenset())}
        favorites = {Target("ssh", "gone", "off"), Target("local", "work"), Target("ssh", "notes", "dev")}

        entries = _entries("", local, remote, favorites)

        self.assertEqual([entry.label for entry in entries[:4]], ["STARRED", "local:work", "ssh:dev:notes", "ssh:off:gone"])
        self.assertTrue(entries[3].unavailable_favorite)
        self.assertEqual(sum(entry.target == Target("local", "work") for entry in entries), 2)
        self.assertTrue(all(entry.starred for entry in entries if entry.target == Target("local", "work")))

    def test_headers_identify_local_hostname_and_ssh_alias(self):
        with patch("mtmux.sidebar.socket.gethostname", return_value="laptop"), patch(
            "mtmux.sidebar._ascii", return_value=False
        ):
            entries = _entries("", [], {"dev": None})

        self.assertEqual([entry.label for entry in entries if entry.kind == "header"], ["💻 laptop", "🔐 dev"])

    def test_ascii_headers_preserve_text_only_labels(self):
        with patch.dict("mtmux.sidebar.os.environ", {"MTMUX_ASCII": "1"}), patch(
            "mtmux.sidebar.socket.gethostname", return_value="laptop"
        ):
            entries = _entries("", [], {"dev": None})

        self.assertEqual([entry.label for entry in entries if entry.kind == "header"], ["LOCAL laptop", "SSH dev"])

    def test_starred_filter_matches_session_name_and_hides_empty_header(self):
        favorites = {Target("ssh", "work", "dev")}

        with patch("mtmux.sidebar.socket.gethostname", return_value="laptop"), patch(
            "mtmux.sidebar._ascii", return_value=False
        ):
            self.assertEqual(_entries("missing", [], {}, favorites)[0].label, "💻 laptop")
            self.assertEqual(_entries("WORK", [], {}, favorites)[0].label, "STARRED")

    def test_title_excludes_star_duplicates_and_stale_favorites(self):
        screen = FakeScreen(size=(5, 40))
        target = Target("local", "work")
        entries = [Entry("local:work", "session", target, starred=True), Entry("work", "session", target, starred=True), Entry("local:gone", "session", Target("local", "gone"), starred=True, unavailable_favorite=True)]

        _draw(screen, entries, 0, "ok", "")

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].endswith("1 session"))

    def test_rendered_star_uses_unicode_and_ascii_marker(self):
        target = Target("local", "work")
        entry = Entry("work", "session", target, starred=True)
        for ascii_mode, marker in ((False, "⭐"), (True, "*")):
            screen = FakeScreen(size=(6, 30))
            with self.subTest(ascii=ascii_mode), patch("mtmux.sidebar._ascii", return_value=ascii_mode):
                _draw(screen, [entry], 0, "ok", "")
            self.assertTrue(any(call[0] == "addnstr" and marker in call[3] for call in screen.calls))

    def test_f_stars_session_and_persists(self):
        screen = FakeScreen([ord("f"), ord("q")], size=(8, 30))
        target = Target("local", "work")

        with (
            patch("mtmux.sidebar.load_stars", return_value=set()),
            patch("mtmux.sidebar.save_stars") as save,
            patch("mtmux.sidebar.local_sessions", return_value=["work"]),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=target),
        ):
            run(screen)

        save.assert_called_once_with({target})

    def test_stale_favorite_cannot_switch_or_kill(self):
        screen = FakeScreen([10, ord("x"), ord("q")], size=(8, 30))
        target = Target("local", "gone")

        with (
            patch("mtmux.sidebar.load_stars", return_value={target}),
            patch("mtmux.sidebar.local_sessions", return_value=[]),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
            patch("mtmux.sidebar.switch") as switch,
            patch("mtmux.sidebar.kill") as kill,
        ):
            run(screen)

        switch.assert_not_called()
        kill.assert_not_called()

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

    def test_selected_index_prefers_session_over_earlier_create(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("new local", "create", host=""),
            Entry("SSH dev", "header"),
            Entry("work", "session", Target("ssh", "work", "dev"), "dev"),
        ]

        self.assertEqual(_selected_index(entries, Target("local", "missing")), 3)

    def test_selected_before_picks_previous_selectable_row(self):
        entries = [
            Entry("LOCAL", "header"),
            Entry("notes", "session", Target("local", "notes")),
            Entry("new local", "create", host=""),
        ]

        self.assertEqual(_selected_before(entries, 2), 1)

    def test_pending_remote_does_not_block_quit_and_poller_closes(self):
        screen = FakeScreen([ord("q")], size=(8, 30))
        poller = unittest.mock.Mock()
        poller.snapshots = {"dev": None}
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.RemotePoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=["dev"]),
            patch("mtmux.sidebar.local_sessions", return_value=[]),
            patch("mtmux.sidebar.local_bell_sessions", return_value=set()),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        poller.close.assert_called_once_with()
        self.assertTrue(any(call[0] == "addnstr" and "connecting" in call[3] for call in screen.calls))

    def test_snapshot_completion_updates_remote_rows(self):
        screen = FakeScreen([-1, ord("q")], size=(8, 30))
        poller = unittest.mock.Mock()
        poller.snapshots = {"dev": None}

        def tick():
            if poller.snapshots["dev"] is None:
                poller.snapshots["dev"] = RemoteSnapshot(True, ("work",), frozenset())
                return True
            return False

        poller.tick.side_effect = tick
        with (
            patch("mtmux.sidebar.RemotePoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=["dev"]),
            patch("mtmux.sidebar.local_sessions", return_value=[]),
            patch("mtmux.sidebar.local_bell_sessions", return_value=set()),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        self.assertTrue(any(call[0] == "addnstr" and "work" in call[3] for call in screen.calls))

    def test_poller_closes_after_keyboard_interrupt(self):
        screen = FakeScreen()
        screen.getch = unittest.mock.Mock(side_effect=KeyboardInterrupt)
        poller = unittest.mock.Mock()
        poller.snapshots = {}
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.RemotePoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.local_sessions", return_value=[]),
            patch("mtmux.sidebar.local_bell_sessions", return_value=set()),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run(screen)

        poller.close.assert_called_once_with()

    def test_current_target_falls_back_to_right_pane_command(self):
        def out(*args, **kwargs):
            if args[0] == "show-options":
                return ""
            return "env -u TMUX tmux new-session -A -s work"

        with patch("mtmux.sidebar.right_pane", return_value="%2"), patch("mtmux.sidebar.tmux.out", side_effect=out):
            self.assertEqual(_current_target(), Target("local", "work"))


if __name__ == "__main__":
    unittest.main()
