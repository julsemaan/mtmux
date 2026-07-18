from __future__ import annotations

import os
import shlex
import shutil
import sys

from .config import ensure_config
from . import tmux

HELP = """printf 'Select a session from mtmux sidebar.\nOpen help: ?\nDetach cockpit: C-g d\nQuit sidebar only: q\nRestart sidebar: mtmux cockpit\n'; exec sh"""
SIDEBAR = f"{shlex.quote(sys.executable)} -m mtmux sidebar"
TARGET = f"{tmux.SESSION}:{tmux.WINDOW}"
SIDEBAR_WIDTH = "30"


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


def _fix_layout(left: str) -> None:
    tmux.tmux("set-window-option", "-t", TARGET, "main-pane-width", SIDEBAR_WIDTH)
    tmux.tmux("select-pane", "-t", left)
    tmux.tmux("select-layout", "-t", TARGET, "main-vertical")


def _install_layout_hooks(left: str) -> None:
    command = f"set-window-option -t {TARGET} main-pane-width {SIDEBAR_WIDTH} ; select-pane -t {left} ; select-layout -t {TARGET} main-vertical"
    tmux.tmux("set-hook", "-t", tmux.SESSION, "client-attached", command)
    tmux.tmux("set-hook", "-t", tmux.SESSION, "client-resized", command)


def _build() -> None:
    _, wrapper = ensure_config()
    if _window_exists():
        tmux.tmux("kill-window", "-t", TARGET, check=False)
    if tmux.tmux("has-session", "-t", tmux.SESSION, check=False).returncode != 0:
        tmux.tmux("new-session", "-d", "-s", tmux.SESSION, "-n", tmux.WINDOW, HELP, config=wrapper)
    else:
        tmux.tmux("new-window", "-d", "-t", tmux.SESSION, "-n", tmux.WINDOW, HELP)
    right = tmux.out("display-message", "-p", "-t", TARGET, "#{pane_id}")
    left = tmux.out("split-window", "-h", "-b", "-l", SIDEBAR_WIDTH, "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
    _fix_layout(left)
    _set_markers(left, right)
    _install_layout_hooks(left)
    tmux.tmux("set-option", "-t", tmux.SESSION, "prefix", "C-g")
    tmux.tmux("set-option", "-t", tmux.SESSION, "status", "off")
    tmux.tmux("set-option", "-t", tmux.SESSION, "mouse", "off")
    tmux.tmux("bind-key", "C-g", "send-prefix")


def ensure_cockpit() -> None:
    if _valid():
        left = _option("@mtmux_sidebar_pane")
        _fix_layout(left)
        _install_layout_hooks(left)
        return
    if _option("@mtmux_cockpit") == "1":
        right = _option("@mtmux_right_pane")
        if right and tmux.has_pane(right):
            left = tmux.out("split-window", "-h", "-b", "-l", SIDEBAR_WIDTH, "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
            _fix_layout(left)
            _set_markers(left, right)
            _install_layout_hooks(left)
            return
    _build()


def _attach() -> int:
    attach_cmd = "tmux -L mtmux attach -t mtmux:cockpit"
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"Cockpit ready. Attach from a real terminal: {attach_cmd}")
        return 0
    try:
        tty = os.ttyname(0)
    except OSError:
        tty = ""
    if tty == "/dev/tty":
        print(f"Cockpit ready. Current fd is /dev/tty; tmux refuses it. Run: {attach_cmd}")
        return 0
    cmd = ["tmux", "-L", tmux.SOCKET, "attach-session", "-t", TARGET]
    if shutil.which("script"):
        shell_cmd = " ".join(shlex.quote(part) for part in cmd)
        os.execvp("script", ["script", "-q", "-c", shell_cmd, "/dev/null"])
    os.execvp("tmux", cmd)
    return 0


def cockpit() -> int:
    ensure_config()
    width = shutil.get_terminal_size((80, 24)).columns
    if width < 70:
        print("Terminal too narrow for mtmux cockpit: need at least 70 columns.", file=sys.stderr)
        return 2
    ensure_cockpit()
    return _attach()


def right_pane() -> str | None:
    if not _valid():
        return None
    pane = _option("@mtmux_right_pane")
    return pane if pane and tmux.has_pane(pane) else None
