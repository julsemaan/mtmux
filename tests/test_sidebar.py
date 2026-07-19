import curses
import unittest
from unittest.mock import call, patch

import mtmux.sidebar as sidebar
from mtmux.discovery import SessionSnapshot, SourceSnapshot
from mtmux.names import Target


def source(kind, sessions=(), bells=(), host=None, available=True, error=None):
    targets = tuple(Target(kind, session, host) for session in sessions)
    bell_targets = frozenset(Target(kind, session, host) for session in bells)
    return SourceSnapshot(available, targets, bell_targets, error)


def snapshot(local=(), remotes=None, local_bells=(), local_available=True, local_error=None):
    return SessionSnapshot(
        source("local", local, local_bells, available=local_available, error=local_error),
        remotes or {},
    )


from mtmux.sidebar import (
    Effect,
    Entry,
    SidebarState,
    _bell_targets,
    _draw,
    _fade,
    _entries,
    _entry_at_row,
    _entry_lines,
    _filter_key,
    _init_colors,
    _mouse_mask,
    _prompt,
    _read_key,
    _selected_index,
    _sync_selection,
    _transition,
    _execute,
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

    def chgat(self, *args):
        self.calls.append(("chgat", *args))

    def attron(self, *args):
        self.calls.append(("attron", *args))

    def attroff(self, *args):
        self.calls.append(("attroff", *args))

    def getch(self):
        self.calls.append(("getch",))
        if self.keys:
            return self.keys.pop(0)
        return self.key

    def redrawln(self, *args):
        self.calls.append(("redrawln", *args))

    def refresh(self):
        self.calls.append(("refresh",))

    def move(self, *args):
        self.calls.append(("move", *args))

    def timeout(self, *args):
        self.calls.append(("timeout", *args))


class SidebarStateTest(unittest.TestCase):
    def test_pending_selection_waits_for_discovery_then_selects_target(self):
        target = Target("ssh", "new", "dev")
        state = SidebarState(selected_index=2, pending_selection=target)
        pending_entries = _entries("", snapshot(remotes={"dev": source("ssh", ("work",), host="dev")}))

        _sync_selection(state, pending_entries)
        self.assertEqual(state.pending_selection, target)
        self.assertIsNone(state.selected_target)

        ready_entries = _entries("", snapshot(remotes={"dev": source("ssh", ("work", "new"), host="dev")}))
        _sync_selection(state, ready_entries)
        self.assertEqual(state.selected_target, target)
        self.assertIsNone(state.pending_selection)

    def test_unrelated_snapshot_preserves_user_selection(self):
        selected = Target("local", "notes")
        state = SidebarState(selected_target=selected, selected_index=2)
        entries = _entries("", snapshot(local=("work", "notes"), remotes={"dev": source("ssh", ("chat",), host="dev")}))

        _sync_selection(state, entries)

        self.assertEqual(entries[state.selected_index].target, selected)

    def test_transition_returns_effect_without_running_operations(self):
        target = Target("local", "work")
        state = SidebarState(selected_target=target)

        effect = _transition(state, "switch")

        self.assertEqual(effect, Effect("switch", target=target))

    def test_toggle_favorite_updates_state_and_returns_save_effect(self):
        target = Target("local", "work")
        state = SidebarState(selected_target=target)

        effect = _transition(state, "toggle_favorite")

        self.assertEqual(state.favorites, {target})
        self.assertEqual(effect, Effect("save_favorites", favorites=frozenset({target}), message="starred local:work"))

    def test_successful_create_switches_and_sets_pending_selection(self):
        target = Target("ssh", "new", "dev")
        state = SidebarState()
        poller = unittest.mock.Mock()
        with (
            patch("mtmux.sidebar.sessions.create") as create,
            patch("mtmux.sidebar.sessions.attach_command", return_value="attach"),
            patch("mtmux.sidebar.cockpit.switch") as switch,
        ):
            self.assertFalse(_execute(Effect("create", target=target), state, poller, 5))

        create.assert_called_once_with(target)
        switch.assert_called_once_with(target, "attach")
        self.assertEqual(state.pending_selection, target)
        poller.refresh.assert_called_once_with()

    def test_successful_kill_discards_target_before_refresh(self):
        target = Target("ssh", "work", "dev")
        state = SidebarState(selected_target=target)
        poller = unittest.mock.Mock()

        with patch("mtmux.sidebar.sessions.kill"):
            _execute(Effect("kill", target=target), state, poller, 5)

        poller.assert_has_calls([unittest.mock.call.discard(target), unittest.mock.call.refresh()])
        self.assertIsNone(state.selected_target)

    def test_failed_create_neither_switches_nor_sets_pending_selection(self):
        target = Target("ssh", "new", "dev")
        state = SidebarState()
        poller = unittest.mock.Mock()
        with (
            patch("mtmux.sidebar.sessions.create", side_effect=SystemExit("create failed")),
            patch("mtmux.sidebar.cockpit.switch") as switch,
        ):
            self.assertFalse(_execute(Effect("create", target=target), state, poller, 5))

        switch.assert_not_called()
        self.assertIsNone(state.pending_selection)
        self.assertEqual(state.status, "create failed")


class SidebarColorTest(unittest.TestCase):
    def setUp(self):
        original = sidebar._COLOR
        self.addCleanup(setattr, sidebar, "_COLOR", original)
        sidebar._COLOR = {}

    def test_256_color_terminal_uses_logo_palette(self):
        with (
            patch("mtmux.sidebar.curses.has_colors", return_value=True),
            patch("mtmux.sidebar.curses.start_color"),
            patch("mtmux.sidebar.curses.use_default_colors"),
            patch.object(curses, "COLORS", 256, create=True),
            patch("mtmux.sidebar.curses.init_pair") as init_pair,
            patch("mtmux.sidebar.curses.color_pair", side_effect=lambda pair: pair << 8),
        ):
            _init_colors()

        self.assertEqual(
            init_pair.call_args_list,
            [
                call(1, 79, 233),
                call(2, 233, 79),
                call(3, 36, -1),
                call(4, 30, -1),
                call(5, 79, -1),
                call(6, curses.COLOR_YELLOW, -1),
                call(7, curses.COLOR_RED, -1),
                call(8, 30, -1),
            ],
        )
        self.assertEqual(sidebar._COLOR["title"], (1 << 8) | curses.A_BOLD)
        self.assertEqual(sidebar._COLOR["hints"], (8 << 8) | curses.A_DIM)

    def test_8_color_terminal_uses_safe_palette(self):
        with (
            patch("mtmux.sidebar.curses.has_colors", return_value=True),
            patch("mtmux.sidebar.curses.start_color"),
            patch("mtmux.sidebar.curses.use_default_colors"),
            patch.object(curses, "COLORS", 8, create=True),
            patch("mtmux.sidebar.curses.init_pair") as init_pair,
            patch("mtmux.sidebar.curses.color_pair", side_effect=lambda pair: pair << 8),
        ):
            _init_colors()

        self.assertEqual(
            init_pair.call_args_list,
            [
                call(1, curses.COLOR_CYAN, curses.COLOR_BLACK),
                call(2, curses.COLOR_BLACK, curses.COLOR_CYAN),
                call(3, curses.COLOR_GREEN, -1),
                call(4, curses.COLOR_CYAN, -1),
                call(5, curses.COLOR_CYAN, -1),
                call(6, curses.COLOR_YELLOW, -1),
                call(7, curses.COLOR_RED, -1),
                call(8, curses.COLOR_CYAN, -1),
            ],
        )

    def test_no_color_terminal_leaves_palette_empty(self):
        sidebar._COLOR = {"title": 123}
        with patch("mtmux.sidebar.curses.has_colors", return_value=False):
            _init_colors()
        self.assertEqual(sidebar._COLOR, {})

    def test_curses_error_leaves_palette_empty(self):
        sidebar._COLOR = {"title": 123}
        with (
            patch("mtmux.sidebar.curses.has_colors", return_value=True),
            patch("mtmux.sidebar.curses.start_color", side_effect=curses.error),
        ):
            _init_colors()
        self.assertEqual(sidebar._COLOR, {})


class SidebarDrawTest(unittest.TestCase):
    def test_inactive_sidebar_dims_existing_colors(self):
        faded = _fade(curses.A_COLOR | curses.A_BOLD)

        self.assertEqual(faded & curses.A_COLOR, curses.A_COLOR)
        self.assertTrue(faded & curses.A_DIM)
        self.assertTrue(faded & curses.A_BOLD)

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

    def test_default_footer_has_two_complete_shortcut_rows(self):
        screen = FakeScreen(size=(7, 60))

        _draw(screen, [Entry("LOCAL", "header")], 0, "", "")

        footer = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr" and call[1] >= 5]
        self.assertEqual(footer, ["↵ switch  f star  n new  x kill", "/ filter  r refresh  ? help  q quit"])

    def test_footer_fills_terminal_width(self):
        screen = FakeScreen(size=(7, 60))

        _draw(screen, [], 0, "", "")

        footer_last_columns = [call for call in screen.calls if call[0] == "chgat" and call[1] >= 5]
        self.assertEqual(footer_last_columns, [("chgat", 5, 59, 1, curses.A_BOLD | curses.A_REVERSE), ("chgat", 6, 59, 1, curses.A_BOLD | curses.A_REVERSE)])

    def test_status_replaces_only_primary_footer_row(self):
        screen = FakeScreen(size=(7, 60))

        _draw(screen, [Entry("LOCAL", "header")], 0, "created b", "")

        footer = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr" and call[1] >= 5]
        self.assertEqual(footer, ["created b", "/ filter  r refresh  ? help  q quit"])

    def test_long_footer_wraps_and_reserves_bottom_rows_at_20_columns(self):
        screen = FakeScreen(size=(8, 20))
        entries = [Entry(str(i), "session", Target("local", str(i))) for i in range(8)]

        footer_height = _draw(screen, entries, 0, "created a status message much longer than width", "")

        footer_calls = [call for call in screen.calls if call[0] == "addnstr" and call[1] >= 3]
        self.assertEqual(footer_height, 5)
        self.assertIn("q quit", "".join(call[3] for call in footer_calls))
        self.assertFalse(any(call[0] == "addnstr" and call[1] >= 3 and call[3].lstrip().startswith(tuple(str(i) for i in range(8))) for call in screen.calls))

    def test_filtering_uses_two_instruction_rows_with_ascii_fallback(self):
        for ascii_mode, expected in (
            (False, ["type to filter  backspace edit", "esc clear  ↵ switch"]),
            (True, ["type to filter  backspace edit", "esc clear  Enter switch"]),
        ):
            screen = FakeScreen(size=(7, 60))
            with self.subTest(ascii=ascii_mode), patch("mtmux.sidebar._ascii", return_value=ascii_mode):
                _draw(screen, [], 0, "ignored", "", filtering=True)
            footer = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr" and call[1] >= 5]
            self.assertEqual(footer, expected)

    def test_footer_reuses_title_style_and_dims_inactive_pane(self):
        screen = FakeScreen(size=(7, 60))
        with patch.dict("mtmux.sidebar._COLOR", {"title": 123}, clear=True):
            _draw(screen, [], 0, "", "", dimmed=True)
        footer = [call for call in screen.calls if call[0] == "addnstr" and call[1] >= 5]
        self.assertTrue(all(call[5] == _fade(123) for call in footer))

    def test_footer_monochrome_fallback_is_bold_reverse_video(self):
        screen = FakeScreen(size=(7, 60))
        with patch.dict("mtmux.sidebar._COLOR", {}, clear=True):
            _draw(screen, [], 0, "", "")
        footer = [call for call in screen.calls if call[0] == "addnstr" and call[1] >= 5]
        self.assertTrue(all(call[5] & curses.A_BOLD and call[5] & curses.A_REVERSE for call in footer))

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
        self.assertEqual(screen.calls[-1], ("timeout", 50))

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
        self.assertEqual(screen.calls[-1], ("timeout", 50))

    def test_title_adds_terminal_icon_with_ascii_fallback(self):
        screen = FakeScreen(size=(5, 40))

        with patch("mtmux.sidebar._ascii", return_value=False):
            _draw(screen, [], 0, "ok", "")
        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].startswith("  mtmux"))

        screen = FakeScreen(size=(5, 40))
        with patch("mtmux.sidebar._ascii", return_value=True):
            _draw(screen, [], 0, "ok", "")
        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].startswith(" mtmux"))

    def test_draw_erases_without_forcing_full_repaint(self):
        screen = FakeScreen(size=(5, 40))

        _draw(screen, [], 0, "ok", "")

        self.assertEqual(screen.calls[0], ("erase",))
        self.assertNotIn(("clear",), screen.calls)

    def test_title_forces_terminal_line_redraw_after_count_changes(self):
        screen = FakeScreen(size=(5, 40))

        _draw(screen, [Entry("work", "session", Target("local", "work"))], 0, "", "", dimmed=True)

        title = next(i for i, call in enumerate(screen.calls) if call[0] == "addnstr" and call[1] == 0)
        redraw = screen.calls.index(("redrawln", 0, 1))
        self.assertLess(title, redraw)

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
        self.assertEqual(title[3], "  mtmux" + " " * 22 + "2 sessions")

    def test_title_count_uses_singular_labels(self):
        screen = FakeScreen(size=(5, 40))
        entries = [Entry("work", "session", Target("local", "work"))]

        _draw(screen, entries, 0, "ok", "")
        normal = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(normal[3].endswith("1 session"))

        screen = FakeScreen(size=(5, 40))
        _draw(screen, entries, 0, "filtering", "work", filtering=True)
        filtering = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(filtering[3].rstrip(), "  mtmux / work                  1 match")

    def test_filter_keeps_brand_query_count_and_cursor(self):
        screen = FakeScreen(size=(5, 40))
        entries = [Entry("work", "session", Target("local", "work"))]

        _draw(screen, entries, 0, "filtering", "work", filtering=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(title[3].rstrip(), "  mtmux / work                  1 match")
        self.assertIn(("move", 0, len("  mtmux / work")), screen.calls)

    def test_empty_filter_has_visible_input_position(self):
        screen = FakeScreen(size=(5, 20))

        _draw(screen, [], 0, "filtering", "", filtering=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].startswith("  mtmux / "))
        self.assertIn(("move", 0, len("  mtmux / ")), screen.calls)

    def test_narrow_filter_drops_count_before_clipping_query(self):
        screen = FakeScreen(size=(5, 16))

        _draw(screen, [Entry("work", "session", Target("local", "work"))], 0, "filtering", "abcdefghij", filtering=True)

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertEqual(title[3], "  mtmux / abcde")
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

    def test_bell_targets_combines_cockpit_local_and_remote_bells(self):
        discovered = snapshot(
            local=("notes",),
            local_bells=("notes",),
            remotes={"dev": source("ssh", ("chat",), ("chat",), "dev")},
        )
        self.assertEqual(
            _bell_targets(discovered, Target("local", "work")),
            {Target("local", "work"), Target("local", "notes"), Target("ssh", "chat", "dev")},
        )

    def test_draw_marks_matching_bell_target(self):
        screen = FakeScreen(size=(8, 40))
        target = Target("ssh", "work", "dev")

        _draw(screen, [Entry("work", "session", target)], 0, "", "", bell_targets={target})

        self.assertTrue(any(call[0] == "addnstr" and "work 🔔" in call[3] for call in screen.calls))

    def test_draw_does_not_mark_current_target_bell(self):
        screen = FakeScreen()
        target = Target("local", "work")

        _draw(screen, [Entry("work", "session", target)], 0, "", "", bell_targets={target}, current_target=target)

        self.assertFalse(any(call[0] == "addnstr" and "🔔" in call[3] for call in screen.calls))

    def test_transient_status_remains_before_deadline_and_clears_afterward(self):
        screen = FakeScreen([ord("r"), -1, -1, ord("q")], size=(7, 60))

        with (
            patch("mtmux.sidebar.time.monotonic", side_effect=[0, 0, 4.9, 5.0, 5.0]),
            patch("mtmux.sidebar.load_status_timeout", return_value=5),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        primary = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr" and call[1] == 5]
        self.assertEqual(primary, ["↵ switch  f star  n new  x kill", "refreshing", "↵ switch  f star  n new  x kill"])

    def test_later_status_resets_deadline(self):
        screen = FakeScreen([ord("r"), ord("?"), -1, -1, ord("q")], size=(7, 60))

        with (
            patch("mtmux.sidebar.time.monotonic", side_effect=[0, 0, 4, 4, 8, 9, 9]),
            patch("mtmux.sidebar.load_status_timeout", return_value=5),
            patch("mtmux.sidebar.cockpit.show_help"),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        primary = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr" and call[1] == 5]
        self.assertEqual(primary[-3:], ["refreshing", "help opened", "↵ switch  f star  n new  x kill"])

    def test_custom_status_timeout_controls_expiry(self):
        screen = FakeScreen([ord("r"), -1, -1, ord("q")], size=(7, 60))

        with (
            patch("mtmux.sidebar.time.monotonic", side_effect=[10, 10, 11.9, 12, 12]),
            patch("mtmux.sidebar.load_status_timeout", return_value=2) as load_timeout,
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        load_timeout.assert_called_once_with()
        primary = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr" and call[1] == 5]
        self.assertIn("refreshing", primary)
        self.assertEqual(primary[-1], "↵ switch  f star  n new  x kill")

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

        self.assertIn(("timeout", 50), screen.calls)
        self.assertEqual(calls, [""])

    def test_idle_ui_ticks_do_not_redraw_sidebar(self):
        screen = FakeScreen([-1, -1, ord("q")])

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", Target("local", "work"))]),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
            patch("mtmux.sidebar._draw", return_value=2) as draw,
        ):
            run(screen)

        draw.assert_called_once()

    def test_rapid_ui_ticks_do_not_accelerate_cockpit_bell_polling(self):
        screen = FakeScreen([-1, -1, -1, ord("q")])
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot()
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.time.monotonic", side_effect=[0, 0.1, 0.49, 0.5]),
            patch("mtmux.sidebar.cockpit.bell_target", return_value=None) as bell_target,
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        self.assertEqual(bell_target.call_count, 2)
        self.assertEqual(poller.tick.call_count, 4)

    def test_run_beeps_once_for_new_background_bell(self):
        screen = FakeScreen([-1, -1, ord("q")])
        target = Target("local", "work")

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.beep") as beep,
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=[Entry("work", "session", target)]),
            patch("mtmux.sidebar._bell_targets", return_value={target}),
            patch("mtmux.sidebar._current_target", return_value=Target("local", "shell")),
        ):
            run(screen)

        beep.assert_called_once_with()

    def test_run_propagates_new_local_snapshot_bell_to_sidebar(self):
        screen = FakeScreen([-1, ord("q")], size=(8, 40))
        target = Target("local", "work")
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot(local=("work",))

        def tick():
            ringing = snapshot(local=("work",), local_bells=("work",))
            changed = poller.snapshot != ringing
            poller.snapshot = ringing
            return changed

        poller.tick.side_effect = tick
        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.beep") as beep,
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar.cockpit.bell_target", return_value=None),
            patch("mtmux.sidebar._current_target", return_value=Target("local", "shell")),
        ):
            run(screen)

        beep.assert_called_once_with()
        self.assertTrue(any(call[0] == "addnstr" and "🔔" in call[3] for call in screen.calls))

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
            patch("mtmux.sidebar.cockpit.switch") as switch,
        ):
            run(screen)

        target = Target("local", "two")
        switch.assert_called_once_with(target, "env -u TMUX tmux -T clipboard new-session -A -s two")

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
            patch("mtmux.sidebar.cockpit.switch") as switch,
        ):
            run(screen)

        switch.assert_called_once_with(target, "env -u TMUX tmux -T clipboard new-session -A -s work")

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
            patch("mtmux.sidebar.cockpit.switch") as switch,
        ):
            run(screen)

        target = Target("local", "two")
        switch.assert_called_once_with(target, "env -u TMUX tmux -T clipboard new-session -A -s two")

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

    def test_switching_starred_entry_keeps_focus_in_starred_section(self):
        old = Target("local", "old")
        target = Target("local", "work")
        current = [old]
        entries = [
            Entry("STARRED", "header"),
            Entry("work", "session", target, starred=True, starred_section=True),
            Entry("LOCAL", "header"),
            Entry("work", "session", target, starred=True),
            Entry("old", "session", old),
        ]
        selected = []
        screen = FakeScreen([curses.KEY_UP, curses.KEY_UP, 10, ord("q")])

        with (
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", return_value=entries),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", side_effect=lambda: current[0]),
            patch("mtmux.sidebar._draw", side_effect=lambda _, __, index, *args: selected.append(index) or 2),
            patch("mtmux.sidebar.cockpit.switch", side_effect=lambda *_: current.__setitem__(0, target)),
        ):
            run(screen)

        self.assertEqual(selected, [4, 3, 1, 1])

    def test_external_switch_to_favorite_focuses_starred_entry(self):
        old = Target("local", "old")
        target = Target("local", "work")
        selected = []
        screen = FakeScreen([-1, ord("q")])
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot(local=("old", "work"))
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_stars", return_value={target}),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", side_effect=[old, old, target]),
            patch("mtmux.sidebar._draw", side_effect=lambda _, __, index, *args: selected.append(index) or 2),
        ):
            run(screen)

        self.assertEqual(selected, [3, 1])

    def test_external_switch_updates_selected_sidebar_row(self):
        old = Target("local", "old")
        new = Target("local", "new")
        screen = FakeScreen([-1, 10, ord("q")])
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot(local=("old", "new"))
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_stars", return_value=set()),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", side_effect=[old, old, new, new]),
            patch("mtmux.sidebar.cockpit.switch") as switch,
        ):
            run(screen)

        switch.assert_called_once_with(new, "env -u TMUX tmux -T clipboard new-session -A -s new")

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
            patch("mtmux.sidebar.cockpit.switch"),
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
        screen = FakeScreen()
        screen.getch = unittest.mock.Mock(side_effect=[ord("/"), ord("w"), KeyboardInterrupt, ord("q")])
        calls = []
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot()
        poller.tick.return_value = False

        def entries(filter_text="", *_):
            calls.append(filter_text)
            return [Entry("LOCAL", "header"), Entry("work", "session", Target("local", "work"))]

        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._entries", side_effect=entries),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        self.assertEqual(calls, ["", "w", ""])
        poller.close.assert_called_once_with()

    def test_starred_slots_follow_global_sort_and_survive_filtering(self):
        favorites = {
            Target("ssh", "zeta", "dev"),
            Target("local", "zeta"),
            Target("local", "alpha"),
        }

        starred = [entry for entry in _entries("zeta", snapshot(), favorites) if entry.starred_section]

        self.assertEqual(
            [(entry.target.format(), entry.shortcut_slot) for entry in starred],
            [("local:zeta", 2), ("ssh:dev:zeta", 3)],
        )

    def test_only_first_nine_starred_entries_get_slots(self):
        favorites = {Target("local", f"session-{slot}") for slot in range(10)}

        starred = [entry for entry in _entries("", snapshot(), favorites) if entry.starred_section]

        self.assertEqual([entry.shortcut_slot for entry in starred], [1, 2, 3, 4, 5, 6, 7, 8, 9, None])

    def test_starred_entries_are_first_sorted_duplicated_and_stale(self):
        discovered = snapshot(local=("work",), remotes={"dev": source("ssh", ("notes",), host="dev")})
        favorites = {Target("ssh", "gone", "off"), Target("local", "work"), Target("ssh", "notes", "dev")}

        entries = _entries("", discovered, favorites)

        self.assertEqual([entry.label for entry in entries[:4]], ["STARRED", "work", "notes", "gone"])
        self.assertTrue(all(entry.starred_section for entry in entries[1:4]))
        self.assertTrue(entries[3].unavailable_favorite)
        self.assertEqual(sum(entry.target == Target("local", "work") for entry in entries), 2)
        self.assertTrue(all(entry.starred for entry in entries if entry.target == Target("local", "work")))

    def test_local_discovery_error_is_visible(self):
        entries = _entries("", snapshot(local_available=False, local_error="permission denied"))

        self.assertTrue(any(entry.kind == "unavailable" and entry.label == "unavailable: permission denied" for entry in entries))

    def test_headers_identify_local_hostname_and_ssh_alias(self):
        with patch("mtmux.sidebar.socket.gethostname", return_value="laptop"), patch(
            "mtmux.sidebar._ascii", return_value=False
        ):
            entries = _entries("", snapshot(remotes={"dev": None}))

        self.assertEqual([entry.label for entry in entries if entry.kind == "header"], ["💻 laptop", "🌐 dev"])

    def test_ascii_headers_preserve_text_only_labels(self):
        with patch.dict("mtmux.sidebar.os.environ", {"MTMUX_ASCII": "1"}), patch(
            "mtmux.sidebar.socket.gethostname", return_value="laptop"
        ):
            entries = _entries("", snapshot(remotes={"dev": None}))

        self.assertEqual([entry.label for entry in entries if entry.kind == "header"], ["LOCAL laptop", "SSH dev"])

    def test_filter_hides_new_session_options(self):
        entries = _entries("work", snapshot(local=("work",), remotes={"dev": source("ssh", ("work",), host="dev")}))

        self.assertFalse(any(entry.kind == "create" for entry in entries))

    def test_starred_filter_matches_session_name_and_hides_empty_header(self):
        favorites = {Target("ssh", "work", "dev")}

        with patch("mtmux.sidebar.socket.gethostname", return_value="laptop"), patch(
            "mtmux.sidebar._ascii", return_value=False
        ):
            self.assertEqual(_entries("missing", snapshot(), favorites)[0].label, "💻 laptop")
            self.assertEqual(_entries("WORK", snapshot(), favorites)[0].label, "STARRED")

    def test_title_excludes_star_duplicates_and_stale_favorites(self):
        screen = FakeScreen(size=(5, 40))
        target = Target("local", "work")
        entries = [Entry("work", "session", target, starred=True, starred_section=True), Entry("work", "session", target, starred=True), Entry("gone", "session", Target("local", "gone"), starred=True, unavailable_favorite=True, starred_section=True)]

        _draw(screen, entries, 0, "ok", "")

        title = next(call for call in screen.calls if call[0] == "addnstr" and call[1] == 0)
        self.assertTrue(title[3].endswith("1 session"))

    def test_numbered_star_renders_slot_beside_star_in_unicode_and_ascii(self):
        entry = Entry(
            "work", "session", Target("local", "work"), host="laptop",
            starred=True, starred_section=True, shortcut_slot=3,
        )

        with patch("mtmux.sidebar._ascii", return_value=False):
            self.assertEqual(_entry_lines(entry, False, set(), None, 30)[0], "  ✱ 3 work")
        with patch("mtmux.sidebar._ascii", return_value=True):
            self.assertEqual(_entry_lines(entry, False, set(), None, 30)[0], "  * 3 work")

    def test_starred_entries_render_session_then_source_without_raw_targets(self):
        local = Entry("dashboard", "session", Target("local", "dashboard"), host="laptop", starred=True, starred_section=True)
        remote = Entry("auth", "session", Target("ssh", "auth", "dev"), host="dev", starred=True, starred_section=True)

        with patch("mtmux.sidebar._ascii", return_value=False):
            self.assertEqual(_entry_lines(local, True, set(), None, 30), ["› ✱ dashboard", "    💻 laptop"])
            self.assertEqual(_entry_lines(remote, False, set(), None, 30), ["  ✱ auth", "    🌐 dev"])

        self.assertNotIn("local:", "".join(_entry_lines(local, True, set(), None, 30)))
        self.assertNotIn("ssh:", "".join(_entry_lines(remote, False, set(), None, 30)))

    def test_starred_lines_truncate_session_and_metadata_and_keep_bell(self):
        entry = Entry("s" * 64, "session", Target("ssh", "s" * 64, "host"), host="h" * 64, starred=True, starred_section=True)

        with patch("mtmux.sidebar._ascii", return_value=False):
            lines = _entry_lines(entry, False, {entry.target}, None, 20)

        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("… 🔔"))
        self.assertTrue(lines[1].endswith("…"))
        self.assertTrue(all(len(line) <= 20 for line in lines))

    def test_ascii_starred_metadata_and_ellipsis_are_ascii_only(self):
        entry = Entry("session-name", "session", Target("ssh", "session-name", "long-host"), host="long-host", starred=True, starred_section=True, unavailable_favorite=True)

        with patch("mtmux.sidebar._ascii", return_value=True):
            lines = _entry_lines(entry, True, set(), None, 24)

        self.assertTrue(lines[0].isascii())
        self.assertTrue(lines[1].isascii())
        self.assertIn("SSH", lines[1])
        self.assertIn("unavailable", lines[1])
        self.assertIn("...", "".join(lines))

    def test_selected_starred_styles_both_rows_and_both_rows_map_to_entry(self):
        entry = Entry("work", "session", Target("local", "work"), host="laptop", starred=True, starred_section=True)
        screen = FakeScreen(size=(6, 30))

        with patch.dict("mtmux.sidebar._COLOR", {"selected": 123}, clear=True):
            _draw(screen, [entry], 0, "ok", "")

        rows = [call for call in screen.calls if call[0] == "addnstr" and call[1] in (1, 2)]
        self.assertEqual([call[5] for call in rows], [123, 123])
        self.assertEqual(_entry_at_row([entry], 0, 1, 6, 1), 0)
        self.assertEqual(_entry_at_row([entry], 0, 2, 6, 1), 0)

    def test_viewport_budgets_two_rows_for_selected_starred_entry(self):
        entries = [Entry("STARRED", "header"), Entry("work", "session", Target("local", "work"), starred_section=True), Entry("LOCAL", "header")]

        start, end = _viewport(entries, 1, 6)

        self.assertLessEqual(start, 1)
        self.assertGreater(end, 1)
        self.assertLessEqual(sum(2 if entry.starred_section else 1 for entry in entries[start:end]) + int(start > 0) + int(end < len(entries)), 4)

    def test_rendered_star_replaces_session_icon(self):
        target = Target("local", "work")
        entries = [Entry("work", "session", target, starred=True), Entry("notes", "session", Target("local", "notes"))]
        for ascii_mode, expected in ((False, ("› ✱ work", "  ● notes")), (True, ("> * work", "  * notes"))):
            screen = FakeScreen(size=(6, 30))
            with self.subTest(ascii=ascii_mode), patch("mtmux.sidebar._ascii", return_value=ascii_mode):
                _draw(screen, entries, 0, "ok", "")
            rendered = [call[3].rstrip() for call in screen.calls if call[0] == "addnstr"]
            self.assertTrue(all(text in rendered for text in expected))

    def test_f_stars_session_and_persists(self):
        screen = FakeScreen([ord("f"), ord("q")], size=(8, 30))
        target = Target("local", "work")

        with (
            patch("mtmux.sidebar.load_stars", return_value=set()),
            patch("mtmux.sidebar.save_stars") as save,
            patch("mtmux.discovery.local_snapshot", return_value=source("local", ("work",))),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=target),
        ):
            run(screen)

        save.assert_called_once_with({target})

    def test_failed_kill_shows_error_and_keeps_sidebar_open(self):
        screen = FakeScreen([ord("x"), ord("y"), ord("q")], size=(8, 60))
        target = Target("local", "work")

        with (
            patch("mtmux.discovery.local_snapshot", return_value=source("local", ("work",))),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=target),
            patch("mtmux.sidebar.sessions.kill", side_effect=SystemExit("kill local:work failed: denied")),
        ):
            run(screen)

        self.assertTrue(any(call[0] == "addnstr" and "kill local:work failed: denied" in call[3] for call in screen.calls))

    def test_refresh_reloads_local_sessions_and_preserves_selection(self):
        screen = FakeScreen([ord("r"), ord("q")], size=(8, 60))
        selected = Target("local", "work")
        draws = []

        with (
            patch("mtmux.discovery.local_snapshot", side_effect=[
                source("local", ("notes", "work")),
                source("local", ("work", "new")),
                source("local", ("work", "new")),
                source("local", ("work", "new")),
            ]),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=selected),
            patch("mtmux.sidebar._draw", side_effect=lambda _, entries, index, *args, **kwargs: draws.append((entries[index].target, [entry.target for entry in entries])) or 1),
        ):
            run(screen)

        self.assertEqual(draws[-1][0], selected)
        self.assertIn(Target("local", "new"), draws[-1][1])

    def test_stale_favorite_cannot_switch_or_kill(self):
        screen = FakeScreen([10, ord("x"), ord("q")], size=(8, 30))
        target = Target("local", "gone")

        with (
            patch("mtmux.sidebar.load_stars", return_value={target}),
            patch("mtmux.discovery.local_snapshot", return_value=source("local")),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", return_value=None),
            patch("mtmux.sidebar.cockpit.switch") as switch,
            patch("mtmux.sidebar.sessions.kill") as kill,
        ):
            run(screen)

        switch.assert_not_called()
        kill.assert_not_called()

    def test_rendered_rows_include_icons(self):
        screen = FakeScreen(size=(9, 30))

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

    def test_pending_remote_does_not_block_quit_and_poller_closes(self):
        screen = FakeScreen([ord("q")], size=(10, 30))
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot(remotes={"dev": None})
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=["dev"]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            run(screen)

        poller.close.assert_called_once_with()
        self.assertTrue(any(call[0] == "addnstr" and "connecting" in call[3] for call in screen.calls))

    def test_new_remote_session_keeps_selection_until_refresh_then_selects_it(self):
        screen = FakeScreen([curses.KEY_DOWN, 10, ord("n"), ord("e"), ord("w"), 10, -1, ord("q")], size=(10, 30))
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot(remotes={"dev": source("ssh", ("work",), host="dev")})
        current = [Target("ssh", "work", "dev")]
        selections = []
        refresh_ticks = [0]

        def tick():
            if current[0].session == "new":
                refresh_ticks[0] += 1
                if refresh_ticks[0] == 2:
                    poller.snapshot = snapshot(remotes={"dev": source("ssh", ("work", "new"), host="dev")})
                    return True
            return False

        def switch(target, command):
            current[0] = target

        poller.tick.side_effect = tick
        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_stars", return_value=set()),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar.curses.echo"),
            patch("mtmux.sidebar.curses.noecho"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._bell_targets", return_value=set()),
            patch("mtmux.sidebar._current_target", side_effect=lambda: current[0]),
            patch("mtmux.sidebar.sessions.create"),
            patch("mtmux.sidebar.cockpit.switch", side_effect=switch),
            patch("mtmux.sidebar._draw", side_effect=lambda _, entries, selected, *args, **kwargs: selections.append(entries[selected].target) or 1),
        ):
            run(screen)

        self.assertEqual(selections[-2:], [None, Target("ssh", "new", "dev")])

    def test_snapshot_completion_updates_remote_rows(self):
        screen = FakeScreen([-1, ord("q")], size=(10, 30))
        poller = unittest.mock.Mock()
        poller.snapshot = snapshot(remotes={"dev": None})

        def tick():
            if poller.snapshot.remotes["dev"] is None:
                poller.snapshot = snapshot(remotes={"dev": source("ssh", ("work",), host="dev")})
                return True
            return False

        poller.tick.side_effect = tick
        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=["dev"]),
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
        poller.snapshot = snapshot()
        poller.tick.return_value = False

        with (
            patch("mtmux.sidebar.DiscoveryPoller", return_value=poller),
            patch("mtmux.sidebar.load_hosts", return_value=[]),
            patch("mtmux.sidebar.curses.curs_set"),
            patch("mtmux.sidebar._init_colors"),
            patch("mtmux.sidebar._current_target", return_value=None),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run(screen)

        poller.close.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()
