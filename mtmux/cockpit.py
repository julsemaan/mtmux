from __future__ import annotations

import os
import shlex
import shutil
import sys

from .config import ensure_config
from . import tmux

HELP = """printf 'mtmux cockpit\n\nNavigation\n  C-g s  focus/open sidebar\n  ?      open help\n  q      quit sidebar only\n\nSession actions\n  Enter  switch\n  n      new session\n  x      kill selected session\n  /      filter sessions\n  r      refresh\n\nRecovery\n  C-g d  detach cockpit\n  C-g s  restart/focus sidebar\n  Esc    cancel prompts/filter\n\nExamples\n  /work  filter sessions matching work\n  n      create local or remote session from selected group\n'; exec sh"""
SIDEBAR = f"{shlex.quote(sys.executable)} -m mtmux sidebar"
FOCUS_SIDEBAR = f"{shlex.quote(sys.executable)} -m mtmux focus-sidebar"
TARGET = f"{tmux.SESSION}:{tmux.WINDOW}"
SIDEBAR_WIDTH = "40"


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


def _install_bindings() -> None:
    tmux.tmux("bind-key", "C-g", "send-prefix")
    tmux.tmux("bind-key", "s", "run-shell", FOCUS_SIDEBAR)


def _install_bell_hook() -> None:
    tmux.tmux("set-window-option", "-t", TARGET, "monitor-bell", "on")
    tmux.tmux("set-option", "-t", tmux.SESSION, "bell-action", "any")
    tmux.tmux("set-hook", "-t", tmux.SESSION, "alert-bell", "set-option -F -t mtmux @mtmux_bell_target '#{@mtmux_current_target}'")


def _install_right_pane_reset(left: str, right: str) -> None:
    tmux.tmux("set-option", "-p", "-t", right, "remain-on-exit", "on")
    command = f"if-shell -F '#{{==:#{{hook_pane}},{right}}}' {{ set-option -u -t {tmux.SESSION} @mtmux_current_target ; set-option -u -t {tmux.SESSION} @mtmux_bell_target ; respawn-pane -k -t {right} {shlex.quote(HELP)} ; select-pane -t {left} }}"
    tmux.tmux("set-hook", "-t", tmux.SESSION, "pane-died", command)


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
    _install_bell_hook()
    _install_right_pane_reset(left, right)
    tmux.tmux("set-option", "-t", tmux.SESSION, "prefix", "C-g")
    tmux.tmux("set-option", "-t", tmux.SESSION, "status", "off")
    tmux.tmux("set-option", "-t", tmux.SESSION, "mouse", "off")
    _install_bindings()


def ensure_cockpit() -> None:
    if _valid():
        left = _option("@mtmux_sidebar_pane")
        right = _option("@mtmux_right_pane")
        _fix_layout(left)
        _install_layout_hooks(left)
        _install_bell_hook()
        _install_right_pane_reset(left, right)
        _install_bindings()
        return
    if _option("@mtmux_cockpit") == "1":
        right = _option("@mtmux_right_pane")
        if right and tmux.has_pane(right):
            left = tmux.out("split-window", "-h", "-b", "-l", SIDEBAR_WIDTH, "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
            _fix_layout(left)
            _set_markers(left, right)
            _install_layout_hooks(left)
            _install_bell_hook()
            _install_right_pane_reset(left, right)
            _install_bindings()
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
    if width < 90:
        print("Terminal too narrow for mtmux cockpit: need at least 90 columns.", file=sys.stderr)
        return 2
    ensure_cockpit()
    return _attach()


def focus_sidebar() -> int:
    ensure_config()
    ensure_cockpit()
    return 0


def right_pane() -> str | None:
    if not _valid():
        return None
    pane = _option("@mtmux_right_pane")
    return pane if pane and tmux.has_pane(pane) else None
