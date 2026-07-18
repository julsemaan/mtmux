from __future__ import annotations

import curses
import locale
import os
import re
from dataclasses import dataclass

from . import tmux
from .discovery import bell_targets as discovered_bell_targets, discover
from .cockpit import right_pane
from .names import Target, parse_target, validate_name
from .switcher import create_local, create_remote, kill, show_help, switch


@dataclass(frozen=True)
class Entry:
    label: str
    kind: str  # header | session | create | unavailable
    target: Target | None = None
    host: str | None = None


_COLOR: dict[str, int] = {}


def _ascii() -> bool:
    enc = locale.getpreferredencoding(False).lower()
    return os.environ.get("MTMUX_ASCII") == "1" or "utf" not in enc


def _icons() -> dict[str, str]:
    if _ascii():
        return {"local": "*", "remote": "*", "create": "+", "unavailable": "!", "selected": ">"}
    return {"local": "●", "remote": "◆", "create": "＋", "unavailable": "⚠", "selected": "›"}


def _init_colors() -> None:
    global _COLOR
    _COLOR = {}
    try:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        pairs = {
            "title": (1, curses.COLOR_CYAN, -1, curses.A_BOLD),
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


def _entries(filter_text: str = "") -> list[Entry]:
    needle = filter_text.lower()
    items = discover()
    out: list[Entry] = [Entry("LOCAL", "header")]
    for item in (i for i in items if i.kind == "local"):
        if item.session and needle in item.session.lower():
            out.append(Entry(item.session, "session", Target("local", item.session)))
    out.append(Entry("new local", "create", host=""))

    hosts: list[str] = []
    for item in items:
        if item.kind == "ssh" and item.host and item.host not in hosts:
            hosts.append(item.host)
    for host in hosts:
        out.append(Entry(f"SSH {host}", "header"))
        host_items = [i for i in items if i.kind == "ssh" and i.host == host]
        if any(not i.available for i in host_items):
            out.append(Entry("unavailable", "unavailable", host=host))
            continue
        for item in host_items:
            if item.session and needle in item.session.lower():
                out.append(Entry(item.session, "session", Target("ssh", item.session, host), host))
        out.append(Entry(f"new on {host}", "create", host=host))
    return out


def _selectable(entries: list[Entry]) -> list[int]:
    return [i for i, entry in enumerate(entries) if entry.kind in ("session", "create")]


def _selected_index(entries: list[Entry], target: Target | None) -> int:
    if target:
        for i, entry in enumerate(entries):
            if entry.target == target:
                return i
    selectable = _selectable(entries)
    return selectable[0] if selectable else 0


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


def _bell_targets() -> set[str]:
    target = tmux.out("show-options", "-v", "-t", tmux.SESSION, "@mtmux_bell_target", check=False)
    targets = discovered_bell_targets()
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


def _draw_title(stdscr: curses.window, w: int, filter_text: str) -> None:
    suffix = f"filter: {filter_text}" if filter_text else ""
    title = " mtmux"
    if suffix:
        title = f"{title:<30}{suffix}"
    stdscr.addnstr(0, 0, title.ljust(w - 1), w - 1, _color("title") or curses.A_BOLD)


def _entry_text(entry: Entry, selected: bool, bell_targets: set[str], current_target: Target | None) -> str:
    icon = _icons()
    pointer = icon["selected"] if selected else " "
    if entry.kind == "header":
        return entry.label
    if entry.kind == "session":
        kind = "remote" if entry.target and entry.target.kind == "ssh" else "local"
        text = f"{pointer} {icon[kind]} {entry.label}"
        if entry.target and entry.target.format() in bell_targets and entry.target != current_target:
            text += " 🔔"
        return text
    if entry.kind == "create":
        return f"{pointer} {icon['create']} {entry.label}"
    return f"  {icon['unavailable']} {entry.label}"


def _entry_attr(entry: Entry, selected: bool) -> int:
    if selected:
        return _color("selected") or curses.A_REVERSE
    if entry.kind == "header":
        return curses.A_BOLD
    if entry.kind == "session" and entry.target and entry.target.kind == "ssh":
        return _color("remote")
    if entry.kind == "session":
        return _color("local")
    if entry.kind == "create":
        return _color("create")
    if entry.kind == "unavailable":
        return _color("unavailable") or curses.A_DIM
    return 0


def _draw_entries(
    stdscr: curses.window,
    entries: list[Entry],
    selected: int,
    h: int,
    w: int,
    bell_targets: set[str],
    current_target: Target | None,
) -> None:
    start, end = _viewport(entries, selected, h)
    row = 1
    if start:
        stdscr.addnstr(row, 0, "↑ more", w - 1, _color("hints") or curses.A_DIM)
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
            _entry_attr(entry, idx == selected),
        )
        row += 1
    if end < len(entries) and row < h - 1:
        stdscr.addnstr(row, 0, "↓ more", w - 1, _color("hints") or curses.A_DIM)


def _draw_footer(stdscr: curses.window, h: int, w: int, status: str, filtering: bool = False) -> None:
    footer = "type to filter  esc clear  backspace edit  ↵ switch" if filtering and not _ascii() else status
    if filtering and _ascii():
        footer = "type to filter  esc clear  backspace edit  Enter switch"
    stdscr.addnstr(h - 1, 0, footer[: w - 1].ljust(w - 1), w - 1, _color("hints"))


def _draw(
    stdscr: curses.window,
    entries: list[Entry],
    selected: int,
    status: str,
    filter_text: str,
    filtering: bool = False,
    bell_targets: set[str] | None = None,
    current_target: Target | None = None,
) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    _draw_title(stdscr, w, filter_text)
    _draw_entries(stdscr, entries, selected, h, w, bell_targets or set(), current_target)
    _draw_footer(stdscr, h, w, status, filtering)
    stdscr.refresh()


def _session_prompt(stdscr: curses.window) -> str | None:
    value = _prompt(stdscr, "session: ")
    return validate_name(value, "session") if value else None


def run(stdscr: curses.window) -> None:
    _init_colors()
    curses.curs_set(0)
    selected = 0
    status = "↵ switch  n new  x kill  / filter  r refresh  ? help"
    if _ascii():
        status = "Enter switch  n new  x kill  / filter  r refresh  ? help"
    filter_text = ""
    filtering = False
    entries = _entries(filter_text)
    selected = _selected_index(entries, _current_target())
    rang_bells: set[str] = set()
    stdscr.timeout(500)
    while True:
        selectable = _selectable(entries)
        if selectable and selected not in selectable:
            selected = selectable[0]
        bell_targets = _bell_targets()
        current_target = _current_target()
        visible_bells = bell_targets - ({current_target.format()} if current_target else set())
        if visible_bells - rang_bells:
            curses.beep()
        rang_bells = visible_bells
        _draw(stdscr, entries, selected, status, filter_text, filtering, bell_targets, current_target)
        key = stdscr.getch()
        if key == -1:
            entries = _entries(filter_text)
            continue
        if filtering:
            if key in (27, 3):
                filter_text = ""
                filtering = False
                curses.curs_set(0)
                entries = _entries(filter_text)
                selected = _selected_index(entries, _current_target())
                status = "cancelled" if key == 3 else "filter cleared"
                continue
            new_filter = _filter_key(filter_text, key)
            if new_filter is not None:
                filter_text = new_filter
                entries = _entries(filter_text)
                selected = _selected_index(entries, _current_target())
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
            entries = _entries(filter_text)
            selected = _selected_index(entries, _current_target())
            status = "refreshed"
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
        elif key in (10, 13, curses.KEY_ENTER):
            entry = entries[selected]
            try:
                if entry.target:
                    switch(entry.target)
                    filter_text = ""
                    filtering = False
                    curses.curs_set(0)
                    entries = _entries(filter_text)
                    selected = _selected_index(entries, entry.target)
                    status = f"switched {entry.target.format()}"
                elif entry.kind == "create":
                    curses.curs_set(1)
                    name = _session_prompt(stdscr)
                    curses.curs_set(0)
                    if not name:
                        status = "cancelled"
                        continue
                    if entry.host == "":
                        create_local(name)
                    else:
                        create_remote(validate_name(entry.host or "", "host"), name)
                    entries = _entries(filter_text)
                    selected = _selected_index(entries, _current_target())
                    status = f"created {name}"
            except SystemExit as e:
                status = str(e)
        elif key == ord("x"):
            entry = entries[selected]
            if not entry.target:
                status = "select session to kill"
                continue
            answer = _read_key(stdscr, f"kill {entry.target.format()}? y/N")
            if answer != ord("y"):
                status = "cancelled"
                continue
            kill(entry.target)
            entries = _entries(filter_text)
            selected = _selected_before(entries, selected)
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
                if host == "":
                    create_local(name)
                else:
                    create_remote(validate_name(host or "", "host"), name)
                entries = _entries(filter_text)
                selected = _selected_index(entries, _current_target())
                status = f"created {name}"
            except SystemExit as e:
                status = str(e)


def main() -> int:
    curses.wrapper(run)
    return 0
