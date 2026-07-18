from __future__ import annotations

import curses

from .discovery import discover, DiscoveryResult
from .names import Target, validate_name
from .switcher import create_local, create_remote, show_help, switch

Entry = tuple[str, str | None, Target | None]  # label, new-host marker, target


def _entries(filter_text: str = "") -> list[Entry]:
    items = discover()
    out: list[Entry] = [("LOCAL", None, None)]
    locals_ = [i for i in items if i.kind == "local"]
    for item in locals_:
        if item.session and filter_text.lower() in item.session.lower():
            out.append((f"  {item.session}", None, Target("local", item.session)))
    out.append(("  + new local", "", None))

    hosts: list[str] = []
    for item in items:
        if item.kind == "ssh" and item.host and item.host not in hosts:
            hosts.append(item.host)
    for host in hosts:
        out.append((f"REMOTE {host}", None, None))
        host_items = [i for i in items if i.kind == "ssh" and i.host == host]
        if any(not i.available for i in host_items):
            out.append(("  unavailable", None, None))
            continue
        for item in host_items:
            if item.session and filter_text.lower() in item.session.lower():
                out.append((f"  {item.session}", None, Target("ssh", item.session, host)))
        out.append((f"  + new on {host}", host, None))
    return out


def _selectable(entries: list[Entry]) -> list[int]:
    return [i for i, (_, new_host, target) in enumerate(entries) if new_host is not None or target is not None]


def _prompt(stdscr: curses.window, prompt: str) -> str:
    curses.echo()
    h, w = stdscr.getmaxyx()
    stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
    stdscr.addstr(h - 1, 0, prompt)
    value = stdscr.getstr(h - 1, len(prompt), max(0, w - len(prompt) - 1)).decode().strip()
    curses.noecho()
    stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
    stdscr.refresh()
    return value


def _draw(stdscr: curses.window, entries: list[Entry], selected: int, status: str, filter_text: str) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    title = "mtmux"
    if filter_text:
        title += f" /{filter_text}"
    stdscr.addnstr(0, 0, title, w - 1, curses.A_BOLD)
    for row, (label, new_host, target) in enumerate(entries[: h - 2], 1):
        attr = curses.A_REVERSE if row - 1 == selected else 0
        if target is None and new_host is None and not label.startswith("  +"):
            attr |= curses.A_BOLD
        stdscr.addnstr(row, 0, label, w - 1, attr)
    stdscr.addnstr(h - 1, 0, status[: w - 1].ljust(w - 1), w - 1)
    stdscr.refresh()


def run(stdscr: curses.window) -> None:
    curses.curs_set(0)
    selected = 0
    status = "Enter switch  n new  r refresh  / filter  ? help  q quit"
    filter_text = ""
    entries = _entries(filter_text)
    while True:
        selectable = _selectable(entries)
        if selectable and selected not in selectable:
            selected = selectable[0]
        _draw(stdscr, entries, selected, status, filter_text)
        key = stdscr.getch()
        selectable = _selectable(entries)
        if key == ord("q"):
            return
        if key in (curses.KEY_DOWN, ord("j")) and selectable:
            selected = selectable[(selectable.index(selected) + 1) % len(selectable)]
        elif key in (curses.KEY_UP, ord("k")) and selectable:
            selected = selectable[(selectable.index(selected) - 1) % len(selectable)]
        elif key == ord("r"):
            entries = _entries(filter_text)
            status = "refreshed"
        elif key == ord("/"):
            curses.curs_set(1)
            filter_text = _prompt(stdscr, "/")
            curses.curs_set(0)
            entries = _entries(filter_text)
            selected = 0
            status = "filtered" if filter_text else "filter cleared"
        elif key == ord("?"):
            try:
                show_help()
                status = "help opened"
            except SystemExit as e:
                status = str(e)
        elif key in (10, 13, curses.KEY_ENTER):
            _, new_host, target = entries[selected]
            try:
                if target:
                    switch(target)
                    status = f"switched {target.format()}"
                elif new_host is not None:
                    curses.curs_set(1)
                    name = validate_name(_prompt(stdscr, "session: "), "session")
                    curses.curs_set(0)
                    if new_host == "":
                        create_local(name)
                    else:
                        create_remote(validate_name(new_host, "host"), name)
                    entries = _entries(filter_text)
                    status = f"created {name}"
            except SystemExit as e:
                status = str(e)
        elif key == ord("n"):
            _, new_host, target = entries[selected]
            host = new_host if new_host is not None else (target.host if target and target.kind == "ssh" else "")
            try:
                curses.curs_set(1)
                name = validate_name(_prompt(stdscr, "session: "), "session")
                curses.curs_set(0)
                if host == "":
                    create_local(name)
                else:
                    create_remote(validate_name(host, "host"), name)
                entries = _entries(filter_text)
                status = f"created {name}"
            except SystemExit as e:
                status = str(e)


def main() -> int:
    curses.wrapper(run)
    return 0
