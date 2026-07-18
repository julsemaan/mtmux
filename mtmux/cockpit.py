from __future__ import annotations

import os
import shlex
import shutil
import sys

from .config import ensure_config, load_prefix
from . import tmux

def help_command(prefix: str) -> str:
    text = f"""mtmux cockpit

Navigation
  {prefix} s  focus/open sidebar
  ?      open help
  q      quit sidebar only

Session actions
  Enter  switch
  n      new session
  x      kill selected session
  /      filter sessions
  r      refresh

Recovery
  {prefix} d  detach cockpit
  {prefix} s  restart/focus sidebar
  Esc    cancel prompts/filter

Examples
  /work  filter sessions matching work
  n      create local or remote session from selected group
"""
    return f"printf %s {shlex.quote(text)}; exec sh"


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
    tmux.tmux("set-window-option", "-u", "-t", TARGET, "window-style")
    tmux.tmux("set-window-option", "-u", "-t", TARGET, "window-active-style")
    tmux.tmux("set-window-option", "-t", TARGET, "pane-border-style", "fg=terminal")
    tmux.tmux("set-window-option", "-t", TARGET, "pane-active-border-style", "fg=terminal")
    tmux.tmux("set-window-option", "-t", TARGET, "pane-border-lines", "single")
    tmux.tmux("select-pane", "-t", left)
    tmux.tmux("select-layout", "-t", TARGET, "main-vertical")


def _install_layout_hooks(left: str) -> None:
    command = f"set-window-option -t {TARGET} main-pane-width {SIDEBAR_WIDTH} ; select-pane -t {left} ; select-layout -t {TARGET} main-vertical"
    tmux.tmux("set-hook", "-t", tmux.SESSION, "client-attached", command)
    tmux.tmux("set-hook", "-t", tmux.SESSION, "client-resized", command)


def _install_bindings(prefix: str) -> None:
    tmux.tmux("bind-key", prefix, "send-prefix")
    tmux.tmux("bind-key", "s", "run-shell", FOCUS_SIDEBAR)


def _enable_mouse() -> None:
    tmux.tmux("set-option", "-t", tmux.SESSION, "mouse", "on")


def _install_bell_hook() -> None:
    tmux.tmux("set-window-option", "-t", TARGET, "monitor-bell", "on")
    tmux.tmux("set-option", "-t", tmux.SESSION, "bell-action", "any")
    tmux.tmux("set-hook", "-t", tmux.SESSION, "alert-bell", "set-option -F -t mtmux @mtmux_bell_target '#{@mtmux_current_target}'")


def _install_right_pane_reset(left: str, right: str, prefix: str) -> None:
    tmux.tmux("set-option", "-p", "-t", right, "remain-on-exit", "on")
    command = f"if-shell -F '#{{==:#{{hook_pane}},{right}}}' {{ set-option -u -t {tmux.SESSION} @mtmux_current_target ; set-option -u -t {tmux.SESSION} @mtmux_bell_target ; respawn-pane -k -t {right} {shlex.quote(help_command(prefix))} ; select-pane -t {left} }}"
    tmux.tmux("set-hook", "-t", tmux.SESSION, "pane-died", command)


def _build(prefix: str) -> None:
    _, wrapper = ensure_config()
    help_cmd = help_command(prefix)
    if _window_exists():
        tmux.tmux("kill-window", "-t", TARGET, check=False)
    if tmux.tmux("has-session", "-t", tmux.SESSION, check=False).returncode != 0:
        tmux.tmux("new-session", "-d", "-s", tmux.SESSION, "-n", tmux.WINDOW, help_cmd, config=wrapper)
    else:
        tmux.tmux("new-window", "-d", "-t", tmux.SESSION, "-n", tmux.WINDOW, help_cmd)
    right = tmux.out("display-message", "-p", "-t", TARGET, "#{pane_id}")
    left = tmux.out("split-window", "-h", "-b", "-l", SIDEBAR_WIDTH, "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
    _fix_layout(left)
    _set_markers(left, right)
    _install_layout_hooks(left)
    _install_bell_hook()
    _install_right_pane_reset(left, right, prefix)
    tmux.tmux("set-option", "-t", tmux.SESSION, "prefix", prefix)
    tmux.tmux("set-option", "-t", tmux.SESSION, "status", "off")
    _enable_mouse()
    _install_bindings(prefix)


def ensure_cockpit() -> None:
    prefix = load_prefix()
    if _valid():
        left = _option("@mtmux_sidebar_pane")
        right = _option("@mtmux_right_pane")
        _fix_layout(left)
        _install_layout_hooks(left)
        _install_bell_hook()
        _install_right_pane_reset(left, right, prefix)
        tmux.tmux("set-option", "-t", tmux.SESSION, "prefix", prefix)
        _enable_mouse()
        _install_bindings(prefix)
        return
    if _option("@mtmux_cockpit") == "1":
        right = _option("@mtmux_right_pane")
        if right and tmux.has_pane(right):
            left = tmux.out("split-window", "-h", "-b", "-l", SIDEBAR_WIDTH, "-P", "-F", "#{pane_id}", "-t", right, SIDEBAR)
            _fix_layout(left)
            _set_markers(left, right)
            _install_layout_hooks(left)
            _install_bell_hook()
            _install_right_pane_reset(left, right, prefix)
            tmux.tmux("set-option", "-t", tmux.SESSION, "prefix", prefix)
            _enable_mouse()
            _install_bindings(prefix)
            return
    _build(prefix)


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
