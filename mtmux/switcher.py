from __future__ import annotations

import shlex
import subprocess

from .cockpit import right_pane
from .names import Target
from . import tmux

NO_COCKPIT = "No valid mtmux cockpit. Run: mtmux cockpit"


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
    tmux.tmux("respawn-pane", "-k", "-t", _pane(), _command(target))


def create_local(session: str) -> Target:
    from .names import Target
    subprocess.run(["tmux", "new-session", "-Ad", "-s", session], check=False)
    target = Target("local", session)
    switch(target)
    return target


def create_remote(host: str, session: str) -> Target:
    from .names import Target
    subprocess.run(["ssh", host, f"tmux new-session -Ad -s {session}"], check=False)
    target = Target("ssh", session, host)
    switch(target)
    return target
