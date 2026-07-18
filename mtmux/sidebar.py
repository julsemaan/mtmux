from __future__ import annotations

import curses
import locale
import os
import re
import socket
import textwrap
from dataclasses import dataclass

from . import tmux
from .discovery import RemotePoller, RemoteSnapshot, local_bell_sessions, local_sessions
from .config import load_hosts, load_stars, save_stars
from .cockpit import right_pane
from .names import Target, parse_target, validate_name
from .switcher import create_local, create_remote, kill, show_help, switch


@dataclass(frozen=True)
class Entry:
    label: str
    kind: str  # header | session | create | unavailable
    target: Target | None = None
    host: str | None = None
    starred: bool = False
    unavailable_favorite: bool = False


_COLOR: dict[str, int] = {}


def _ascii() -> bool:
    enc = locale.getpreferredencoding(False).lower()
    return os.environ.get("MTMUX_ASCII") == "1" or "utf" not in enc


def _icons() -> dict[str, str]:
    if _ascii():
        return {"local": "*", "remote": "*", "local_header": "LOCAL", "remote_header": "SSH", "create": "+", "unavailable": "!", "selected": ">", "starred": "*"}
    return {"local": "●", "remote": "◆", "local_header": "💻", "remote_header": "🔐", "create": "＋", "unavailable": "⚠", "selected": "›", "starred": "⭐"}


def _init_colors() -> None:
    global _COLOR
    _COLOR = {}
    try:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        pairs = {
            "title": (1, curses.COLOR_BLACK, curses.COLOR_CYAN, curses.A_BOLD),
            "selected": (2, curses.COLOR_BLACK, curses.COLOR_CYAN, 0),
            "local": (3, curses.COLOR_GREEN, -1, 0),
            "remote": (4, curses.COLOR_BLUE, -1, 0),
            "create": (5, curses.COLOR_CYAN, -1, 0),
            "unavailable": (6, curses.COLOR_YELLOW, -1, curses.A_DIM),
            "danger": (7, curses.COLOR_RED, -1, 0),
            "hints": (8, -1, -1, curses.A_DIM),
        }
        for name, (pair, fg, bg, attr) in pairs.items():
            curses.init_pair(pair, fg, bg)
            _COLOR[name] = curses.color_pair(pair) | attr
    except curses.error:
        _COLOR = {}


def _color(name: str) -> int:
    return _COLOR.get(name, 0)


def _fade(attr: int) -> int:
    return attr | curses.A_DIM


def _pane_active() -> bool:
    pane = os.environ.get("TMUX_PANE")
    return not pane or tmux.out("display-message", "-p", "-t", pane, "#{pane_active}", check=False) == "1"


def _entries(
    filter_text: str,
    local: list[str],
    remote: dict[str, RemoteSnapshot | None],
    favorites: set[Target] | None = None,
) -> list[Entry]:
    needle = filter_text.lower()
    favorites = favorites or set()
    available = {Target("local", session) for session in local}
    for host, snapshot in remote.items():
        if snapshot and snapshot.available:
            available.update(Target("ssh", session, host) for session in snapshot.sessions)

    starred = [target for target in sorted(favorites, key=lambda target: target.format()) if needle in target.session.lower()]
    out = [Entry("STARRED", "header")] if starred else []
    out.extend(Entry(target.format(), "session", target, target.host, True, target not in available) for target in starred)
    icons = _icons()
    out.append(Entry(f"{icons['local_header']} {socket.gethostname()}", "header"))
    for session in local:
        if needle in session.lower():
            target = Target("local", session)
            out.append(Entry(session, "session", target, starred=target in favorites))
    out.append(Entry("new local", "create", host=""))

    for host, snapshot in remote.items():
        out.append(Entry(f"{icons['remote_header']} {host}", "header"))
        if snapshot is None:
            out.append(Entry("connecting…", "unavailable", host=host))
            continue
        if not snapshot.available:
            out.append(Entry("unavailable", "unavailable", host=host))
            continue
        for session in snapshot.sessions:
            if needle in session.lower():
                target = Target("ssh", session, host)
                out.append(Entry(session, "session", target, host, target in favorites))
        out.append(Entry(f"new on {host}", "create", host=host))
    return out


def _selectable(entries: list[Entry]) -> list[int]:
    return [i for i, entry in enumerate(entries) if entry.kind in ("session", "create")]


def _selected_index(entries: list[Entry], target: Target | None) -> int:
    if target:
        for i, entry in enumerate(entries):
            if entry.target == target:
                return i
    for kind in ("session", "create"):
        for i, entry in enumerate(entries):
            if entry.kind == kind:
                return i
    return 0


def _selected_before(entries: list[Entry], index: int) -> int:
    selectable = _selectable(entries)
    previous = [i for i in selectable if i < index]
    return previous[-1] if previous else (selectable[0] if selectable else 0)


def _current_target() -> Target | None:
    try:
        text = tmux.out("show-options", "-v", "-t", tmux.SESSION, "@mtmux_current_target", check=False)
        if text:
            return parse_target(text)
    except SystemExit:
        pass
    try:
        pane = right_pane()
        cmd = tmux.out("display-message", "-p", "-t", pane or "", "#{pane_start_command}", check=False)
        if match := re.search(r"ssh -t ([A-Za-z0-9_.-]+) .* -s ([A-Za-z0-9_.-]+)", cmd):
            return Target("ssh", validate_name(match.group(2), "session"), validate_name(match.group(1), "host"))
        if match := re.search(r"(?:^| )tmux new-session .* -s ([A-Za-z0-9_.-]+)", cmd):
            return Target("local", validate_name(match.group(1), "session"))
    except SystemExit:
        pass
    return None


def _prompt(stdscr: curses.window, prompt: str) -> str | None:
    h, w = stdscr.getmaxyx()
    stdscr.timeout(-1)
    curses.echo()
    try:
        stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
        stdscr.addstr(h - 1, 0, prompt)
        chars: list[str] = []
        while True:
            key = stdscr.getch()
            if key in (27, 3):
                return None
            if key in (10, 13, curses.KEY_ENTER):
                return "".join(chars).strip()
            if key in (curses.KEY_BACKSPACE, 8, 127):
                if chars:
                    chars.pop()
            elif 32 <= key <= 126 and len(chars) < max(0, w - len(prompt) - 1):
                chars.append(chr(key))
    finally:
        curses.noecho()
        stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
        stdscr.refresh()
        stdscr.timeout(500)


def _read_key(stdscr: curses.window, prompt: str) -> int:
    h, w = stdscr.getmaxyx()
    stdscr.timeout(-1)
    try:
        stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
        stdscr.addnstr(h - 1, 0, prompt, w - 1)
        stdscr.refresh()
        return stdscr.getch()
    finally:
        stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
        stdscr.refresh()
        stdscr.timeout(500)


def _filter_key(filter_text: str, key: int) -> str | None:
    if key in (curses.KEY_BACKSPACE, 8, 127):
        return filter_text[:-1]
    if 32 <= key <= 126:
        return filter_text + chr(key)
    return None


def _bell_targets(remote: dict[str, RemoteSnapshot | None]) -> set[str]:
    target = tmux.out("show-options", "-v", "-t", tmux.SESSION, "@mtmux_bell_target", check=False)
    targets = {f"local:{session}" for session in local_bell_sessions()}
    for host, snapshot in remote.items():
        if snapshot and snapshot.available:
            targets.update(f"ssh:{host}:{session}" for session in snapshot.bells)
    if target:
        targets.add(target)
    return targets


def _viewport(entries: list[Entry], selected: int, height: int) -> tuple[int, int]:
    body = max(0, height - 2)
    if len(entries) <= body:
        return 0, len(entries)
    if body <= 1:
        return selected, min(len(entries), selected + 1)

    slots = max(1, body - int(selected > 0) - int(selected < len(entries) - 1))
    start = selected
    end = selected + 1
    while end - start < slots and (start > 0 or end < len(entries)):
        if start > 0:
            start -= 1
        if end - start < slots and end < len(entries):
            end += 1
    return start, end


def _entry_at_row(entries: list[Entry], selected: int, row: int, height: int, footer_height: int) -> int | None:
    content_height = height - footer_height + 1
    start, end = _viewport(entries, selected, content_height)
    entry_row = row - 1 - int(start > 0)
    index = start + entry_row
    if entry_row < 0 or row >= height - footer_height or index >= end:
        return None
    return index if entries[index].kind in ("session", "create") else None


def _mouse_mask() -> None:
    events = (
        getattr(curses, "BUTTON1_PRESSED", 0),
        getattr(curses, "BUTTON1_CLICKED", 0),
        getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0),
        getattr(curses, "BUTTON4_PRESSED", 0),
        getattr(curses, "BUTTON5_PRESSED", 0),
    )
    try:
        curses.mousemask(sum(event for event in events if isinstance(event, int)))
    except curses.error:
        pass


def _draw_title(
    stdscr: curses.window,
    w: int,
    entries: list[Entry],
    filter_text: str,
    filtering: bool = False,
    dimmed: bool = False,
) -> int:
    width = max(1, w)
    count = len({entry.target for entry in entries if entry.kind == "session" and not entry.unavailable_favorite})
    brand = " MTMUX" if _ascii() else " 🖥️ MTMUX"
    left = f"{brand} / {filter_text}" if filtering else brand
    noun = ("match" if count == 1 else "matches") if filtering else ("session" if count == 1 else "sessions")
    right = f"{count} {noun}"
    title = f"{left}{right.rjust(width - len(left))}" if len(left) + len(right) < width else left
    attr = _color("title") or (curses.A_BOLD | curses.A_REVERSE)
    stdscr.addnstr(0, 0, title[:width].ljust(width), width, _fade(attr) if dimmed else attr)
    return min(width - 1, len(left))


def _entry_text(entry: Entry, selected: bool, bell_targets: set[str], current_target: Target | None) -> str:
    icon = _icons()
    pointer = icon["selected"] if selected else " "
    if entry.kind == "header":
        return entry.label
    if entry.kind == "session":
        kind = "unavailable" if entry.unavailable_favorite else ("remote" if entry.target and entry.target.kind == "ssh" else "local")
        marker = f" {icon['starred']}" if entry.starred else ""
        text = f"{pointer} {icon[kind]}{marker} {entry.label}"
        if entry.target and entry.target.format() in bell_targets and entry.target != current_target:
            text += " 🔔"
        return text
    if entry.kind == "create":
        return f"{pointer} {icon['create']} {entry.label}"
    return f"  {icon['unavailable']} {entry.label}"


def _entry_attr(entry: Entry, selected: bool, dimmed: bool = False) -> int:
    if selected:
        attr = _color("selected") or curses.A_REVERSE
    elif entry.kind == "header":
        attr = curses.A_BOLD
    elif entry.unavailable_favorite:
        attr = _color("unavailable") or curses.A_DIM
    elif entry.kind == "session" and entry.target and entry.target.kind == "ssh":
        attr = _color("remote")
    elif entry.kind == "session":
        attr = _color("local")
    elif entry.kind == "create":
        attr = _color("create")
    elif entry.kind == "unavailable":
        attr = _color("unavailable") or curses.A_DIM
    else:
        attr = 0
    return _fade(attr) if dimmed else attr


def _draw_entries(
    stdscr: curses.window,
    entries: list[Entry],
    selected: int,
    h: int,
    w: int,
    bell_targets: set[str],
    current_target: Target | None,
    dimmed: bool = False,
) -> None:
    start, end = _viewport(entries, selected, h)
    row = 1
    if start:
        attr = _color("hints") or curses.A_DIM
        stdscr.addnstr(row, 0, "↑ more", w - 1, _fade(attr) if dimmed else attr)
        row += 1
    for idx in range(start, end):
        if row >= h - 1:
            break
        entry = entries[idx]
        stdscr.addnstr(
            row,
            0,
            _entry_text(entry, idx == selected, bell_targets, current_target),
            w - 1,
            _entry_attr(entry, idx == selected, dimmed),
        )
        row += 1
    if end < len(entries) and row < h - 1:
        attr = _color("hints") or curses.A_DIM
        stdscr.addnstr(row, 0, "↓ more", w - 1, _fade(attr) if dimmed else attr)


def _draw_footer(
    stdscr: curses.window,
    h: int,
    w: int,
    status: str,
    filtering: bool = False,
    dimmed: bool = False,
) -> int:
    footer = "type to filter  esc clear  backspace edit  ↵ switch" if filtering and not _ascii() else status
    if filtering and _ascii():
        footer = "type to filter  esc clear  backspace edit  Enter switch"
    width = max(1, w - 1)
    lines = textwrap.wrap(footer, width=width) or [""]
    attr = _color("hints")
    for row, line in enumerate(lines, h - len(lines)):
        stdscr.addnstr(row, 0, line.ljust(w - 1), w - 1, _fade(attr) if dimmed else attr)
    return len(lines)


def _draw(
    stdscr: curses.window,
    entries: list[Entry],
    selected: int,
    status: str,
    filter_text: str,
    filtering: bool = False,
    bell_targets: set[str] | None = None,
    current_target: Target | None = None,
    dimmed: bool = False,
) -> int:
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    cursor = _draw_title(stdscr, w, entries, filter_text, filtering, dimmed)
    footer_height = _draw_footer(stdscr, h, w, status, filtering, dimmed)
    _draw_entries(
        stdscr,
        entries,
        selected,
        h - footer_height + 1,
        w,
        bell_targets or set(),
        current_target,
        dimmed,
    )
    if filtering:
        stdscr.move(0, cursor)
    stdscr.refresh()
    return footer_height


def _session_prompt(stdscr: curses.window) -> str | None:
    value = _prompt(stdscr, "session: ")
    return validate_name(value, "session") if value else None


def run(stdscr: curses.window) -> None:
    _init_colors()
    curses.curs_set(0)
    _mouse_mask()
    status = "↵ go f star n new x kill / ?" if not _ascii() else "Enter f star n new x kill / ?"
    filter_text = ""
    filtering = False
    local = local_sessions()
    favorites = load_stars()
    poller = RemotePoller(load_hosts())
    entries = _entries(filter_text, local, poller.snapshots, favorites)
    selected = _selected_index(entries, _current_target())
    rang_bells: set[str] = set()
    stdscr.timeout(500)

    def rebuild(preferred: Target | None = None, old_index: int | None = None, starred: bool | None = None) -> None:
        nonlocal entries, selected
        entries = _entries(filter_text, local, poller.snapshots, favorites)
        if preferred and any(entry.target == preferred for entry in entries):
            selected = next((i for i, entry in enumerate(entries) if entry.target == preferred and (starred is None or entry.starred == starred)), _selected_index(entries, preferred))
        elif old_index is not None:
            choices = _selectable(entries)
            selected = min(choices, key=lambda index: abs(index - old_index)) if choices else 0
        else:
            selected = _selected_index(entries, _current_target())

    try:
        while True:
            current_entry = entries[selected] if entries and selected < len(entries) else None
            current_selection = current_entry.target if current_entry else None
            if poller.tick():
                rebuild(old_index=selected)
            selectable = _selectable(entries)
            if selectable and selected not in selectable:
                selected = selectable[0]
            bell_targets = _bell_targets(poller.snapshots)
            current_target = _current_target()
            visible_bells = bell_targets - ({current_target.format()} if current_target else set())
            if visible_bells - rang_bells:
                curses.beep()
            rang_bells = visible_bells
            footer_height = _draw(stdscr, entries, selected, status, filter_text, filtering, bell_targets, current_target, not _pane_active())
            key = stdscr.getch()
            if key == -1:
                continue
            if key == curses.KEY_MOUSE:
                try:
                    _, _, row, _, state = curses.getmouse()
                except (curses.error, TypeError, ValueError):
                    continue
                if not isinstance(row, int) or not isinstance(state, int):
                    continue
                if state & (getattr(curses, "BUTTON4_PRESSED", 0) or 0):
                    key = curses.KEY_UP
                elif state & (getattr(curses, "BUTTON5_PRESSED", 0) or 0):
                    key = curses.KEY_DOWN
                else:
                    index = _entry_at_row(entries, selected, row, stdscr.getmaxyx()[0], footer_height)
                    if index is None:
                        continue
                    selected = index
                    if state & (getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0) or 0):
                        key = curses.KEY_ENTER
                    elif state & ((getattr(curses, "BUTTON1_CLICKED", 0) or 0) | (getattr(curses, "BUTTON1_PRESSED", 0) or 0)):
                        continue
                    else:
                        continue
            if filtering:
                if key in (27, 3):
                    filter_text = ""
                    filtering = False
                    curses.curs_set(0)
                    rebuild()
                    status = "cancelled" if key == 3 else "filter cleared"
                    continue
                new_filter = _filter_key(filter_text, key)
                if new_filter is not None:
                    filter_text = new_filter
                    rebuild(current_selection, selected)
                    status = "filtering" if filter_text else "filter cleared"
                    continue
            selectable = _selectable(entries)
            if key == ord("q"):
                return
            if key in (curses.KEY_DOWN, ord("j")) and selectable:
                selected = selectable[(selectable.index(selected) + 1) % len(selectable)]
            elif key in (curses.KEY_UP, ord("k")) and selectable:
                selected = selectable[(selectable.index(selected) - 1) % len(selectable)]
            elif key == ord("r"):
                poller.refresh()
                status = "refreshing"
            elif key == ord("/"):
                filtering = True
                curses.curs_set(1)
                status = "filtering"
            elif key == ord("?"):
                try:
                    show_help()
                    status = "help opened"
                except SystemExit as e:
                    status = str(e)
            elif key == ord("f"):
                entry = entries[selected]
                if not entry.target:
                    status = "select session to star"
                    continue
                target = entry.target
                was_starred_copy = entry.starred and entry.label == target.format()
                if target in favorites:
                    favorites.remove(target)
                    save_stars(favorites)
                    rebuild(target if not entry.unavailable_favorite else None, selected, False if was_starred_copy else None)
                    status = f"unstarred {target.format()}"
                else:
                    favorites.add(target)
                    save_stars(favorites)
                    rebuild(target, starred=True)
                    status = f"starred {target.format()}"
            elif key in (10, 13, curses.KEY_ENTER):
                entry = entries[selected]
                try:
                    if entry.unavailable_favorite:
                        status = f"unavailable {entry.target.format()}"
                    elif entry.target:
                        switch(entry.target)
                        filter_text = ""
                        filtering = False
                        curses.curs_set(0)
                        rebuild(entry.target)
                        status = f"switched {entry.target.format()}"
                    elif entry.kind == "create":
                        curses.curs_set(1)
                        name = _session_prompt(stdscr)
                        curses.curs_set(0)
                        if not name:
                            status = "cancelled"
                            continue
                        create_local(name) if entry.host == "" else create_remote(validate_name(entry.host or "", "host"), name)
                        local[:] = local_sessions()
                        poller.refresh()
                        rebuild()
                        status = f"created {name}"
                except SystemExit as e:
                    status = str(e)
            elif key == ord("x"):
                entry = entries[selected]
                if not entry.target:
                    status = "select session to kill"
                    continue
                if entry.unavailable_favorite:
                    status = f"unavailable {entry.target.format()}"
                    continue
                answer = _read_key(stdscr, f"kill {entry.target.format()}? y/N")
                if answer != ord("y"):
                    status = "cancelled"
                    continue
                kill(entry.target)
                local[:] = local_sessions()
                poller.refresh()
                rebuild(old_index=selected)
                status = f"killed {entry.target.format()}"
            elif key == ord("n"):
                entry = entries[selected]
                host = entry.host if entry.kind == "create" else (entry.target.host if entry.target and entry.target.kind == "ssh" else "")
                try:
                    curses.curs_set(1)
                    name = _session_prompt(stdscr)
                    curses.curs_set(0)
                    if not name:
                        status = "cancelled"
                        continue
                    create_local(name) if host == "" else create_remote(validate_name(host or "", "host"), name)
                    local[:] = local_sessions()
                    poller.refresh()
                    rebuild()
                    status = f"created {name}"
                except SystemExit as e:
                    status = str(e)
    finally:
        poller.close()


def main() -> int:
    while True:
        try:
            curses.wrapper(run)
            return 0
        except KeyboardInterrupt:
            pass
