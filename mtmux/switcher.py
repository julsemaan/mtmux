from __future__ import annotations

import os
import shlex
import subprocess

from .cockpit import HELP, right_pane
from .names import Target
from . import tmux

NO_COCKPIT = "No valid mtmux cockpit. Run: mtmux cockpit"


def _default_server_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TMUX", None)
    return env


def _pane() -> str:
    pane = right_pane()
    if not pane:
        raise SystemExit(NO_COCKPIT)
    return pane


def _command(target: Target) -> str:
    session = shlex.quote(target.session)
    if target.kind == "local":
        return f"env -u TMUX tmux new-session -A -s {session}"
    host = shlex.quote(target.host or "")
    return f"ssh -t {host} 'tmux new-session -A -s {session}'"


def switch(target: Target) -> None:
    pane = _pane()
    tmux.tmux("set-option", "-t", tmux.SESSION, "@mtmux_current_target", target.format())
    tmux.tmux("set-option", "-u", "-t", tmux.SESSION, "@mtmux_bell_target")
    tmux.tmux("respawn-pane", "-k", "-t", pane, _command(target))
    tmux.tmux("select-pane", "-t", pane)


def show_help() -> None:
    pane = _pane()
    tmux.tmux("respawn-pane", "-k", "-t", pane, HELP)
    tmux.tmux("select-pane", "-t", pane)


def kill(target: Target) -> None:
    if target.kind == "local":
        subprocess.run(("tmux", "kill-session", "-t", target.session), check=False, env=_default_server_env())
        return
    subprocess.run(("ssh", target.host or "", f"tmux kill-session -t {shlex.quote(target.session)}"), check=False)


def create_local(session: str) -> Target:
    from .names import Target
    subprocess.run(["tmux", "new-session", "-Ad", "-s", session], check=False, env=_default_server_env())
    target = Target("local", session)
    switch(target)
    return target


def create_remote(host: str, session: str) -> Target:
    from .names import Target
    subprocess.run(["ssh", host, f"tmux new-session -Ad -s {session}"], check=False)
    target = Target("ssh", session, host)
    switch(target)
    return target
