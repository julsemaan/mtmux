from __future__ import annotations

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


def switch(target: Target) -> None:
    pane = _pane()
    if target.kind == "local":
        cmd = f"tmux new-session -A -s {target.session}"
    else:
        cmd = f"ssh -t {target.host} 'tmux new-session -A -s {target.session}'"
    tmux.tmux("respawn-pane", "-k", "-t", pane, cmd)


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
