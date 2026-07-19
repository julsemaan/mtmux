from __future__ import annotations

import os
import shlex
import subprocess

from .cockpit import help_command, right_pane
from .config import load_prefix
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
        return f"env -u TMUX tmux -T clipboard new-session -A -s {session}"
    host = shlex.quote(target.host or "")
    return f"ssh -t {host} 'tmux -T clipboard new-session -A -s {session}'"


def switch(target: Target) -> None:
    pane = _pane()
    tmux.tmux("set-option", "-t", tmux.SESSION, "@mtmux_current_target", target.format())
    tmux.tmux("set-option", "-u", "-t", tmux.SESSION, "@mtmux_bell_target")
    tmux.tmux("respawn-pane", "-k", "-t", pane, _command(target))
    tmux.tmux("select-pane", "-t", pane)


def show_help() -> None:
    pane = _pane()
    tmux.tmux("respawn-pane", "-k", "-t", pane, help_command(load_prefix()))


def _run(operation: str, target: Target, command: list[str] | tuple[str, ...], **kwargs: object) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)
    except subprocess.CalledProcessError as error:
        reason = (error.stderr or "").strip() or f"exit status {error.returncode}"
        raise SystemExit(f"{operation} {target.format()} failed: {reason}") from None


def kill(target: Target) -> None:
    if target.kind == "local":
        _run("kill", target, ("tmux", "kill-session", "-t", target.session), env=_default_server_env())
        return
    _run("kill", target, ("ssh", target.host or "", f"tmux kill-session -t {shlex.quote(target.session)}"))


def create_local(session: str) -> Target:
    target = Target("local", session)
    _run("create", target, ["tmux", "new-session", "-Ad", "-s", session], env=_default_server_env())
    switch(target)
    return target


def create_remote(host: str, session: str) -> Target:
    target = Target("ssh", session, host)
    _run("create", target, ["ssh", host, f"tmux new-session -Ad -s {session}"])
    switch(target)
    return target
