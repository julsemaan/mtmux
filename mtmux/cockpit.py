from __future__ import annotations

import os
import shutil
import sys

from .config import ensure_config
from . import tmux

HELP = """printf 'Select a session from mtmux sidebar.\nDetach cockpit: C-g d\nQuit sidebar only: q\nRestart sidebar: mtmux cockpit\n'; exec sh"""
SIDEBAR = "python -m mtmux sidebar"
TARGET = f"{tmux.SESSION}:{tmux.WINDOW}"


def _option(name: str) -> str:
    return tmux.out("show-options", "-v", "-t", tmux.SESSION, name, check=False)


def _window_exists() -> bool:
    return tmux.tmux("has-session", "-t", TARGET, check=False).returncode == 0


def _valid() -> bool:
    if _option("@mtmux_cockpit") != "1":
        return False
    left = _option("@mtmux_sidebar_pane")
    right = _option("@mtmux_right_pane")
    return bool(left and right and tmux.has_pane(left) and tmux.has_pane(right))


def _set_markers(left: str, right: str) -> None:
    tmux.tmux("set-option", "-t", tmux.SESSION, "@mtmux_cockpit", "1")
    tmux.tmux("set-option", "-t", tmux.SESSION, "@mtmux_sidebar_pane", left)
    tmux.tmux("set-option", "-t", tmux.SESSION, "@mtmux_right_pane", right)


def _build() -> None:
    _, wrapper = ensure_config()
    if _window_exists():
        tmux.tmux("kill-window", "-t", TARGET, check=False)
    if tmux.tmux("has-session", "-t", tmux.SESSION, check=False).returncode != 0:
        tmux.tmux("new-session", "-d", "-s", tmux.SESSION, "-n", tmux.WINDOW, HELP, config=wrapper)
    else:
        tmux.tmux("new-window", "-d", "-t", tmux.SESSION, "-n", tmux.WINDOW, HELP)
    right = tmux.out("display-message", "-p", "-t", TARGET, "#{pane_id}")
    left = tmux.out("split-window", "-h", "-b", "-l", "30", "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
    tmux.tmux("select-pane", "-t", left)
    _set_markers(left, right)
    tmux.tmux("set-option", "-t", tmux.SESSION, "prefix", "C-g")
    tmux.tmux("set-option", "-t", tmux.SESSION, "status", "off")
    tmux.tmux("set-option", "-t", tmux.SESSION, "mouse", "off")
    tmux.tmux("bind-key", "C-g", "send-prefix")


def ensure_cockpit() -> None:
    if _valid():
        return
    if _option("@mtmux_cockpit") == "1":
        right = _option("@mtmux_right_pane")
        if right and tmux.has_pane(right):
            left = tmux.out("split-window", "-h", "-b", "-l", "30", "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
            _set_markers(left, right)
            return
    _build()


def cockpit() -> int:
    ensure_config()
    width = shutil.get_terminal_size((80, 24)).columns
    if width < 70:
        print("Terminal too narrow for mtmux cockpit: need at least 70 columns.", file=sys.stderr)
        return 2
    ensure_cockpit()
    if not sys.stdin.isatty():
        print("Cockpit ready. Attach: tmux -L mtmux attach -t mtmux:cockpit")
        return 0
    os.execvp("tmux", ["tmux", "-L", tmux.SOCKET, "attach", "-t", TARGET])
    return 0


def right_pane() -> str | None:
    if not _valid():
        return None
    pane = _option("@mtmux_right_pane")
    return pane if pane and tmux.has_pane(pane) else None
