from __future__ import annotations

import os
import shlex
import subprocess

from .names import Target


def _default_server_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TMUX", None)
    return env


def attach_command(target: Target) -> str:
    session = shlex.quote(target.session)
    if target.kind == "local":
        return f"env -u TMUX tmux -T clipboard new-session -A -s {session}"
    return f"ssh -t {shlex.quote(target.host or '')} 'tmux -T clipboard new-session -A -s {session}'"


def _run(operation: str, target: Target, command: tuple[str, ...], **kwargs: object) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)
    except subprocess.CalledProcessError as error:
        reason = (error.stderr or "").strip() or f"exit status {error.returncode}"
        raise SystemExit(f"{operation} {target.format()} failed: {reason}") from None


def create(target: Target) -> None:
    if target.kind == "local":
        _run("create", target, ("tmux", "new-session", "-Ad", "-s", target.session), env=_default_server_env())
    else:
        _run("create", target, ("ssh", target.host or "", f"tmux new-session -Ad -s {shlex.quote(target.session)}"))


def kill(target: Target) -> None:
    if target.kind == "local":
        _run("kill", target, ("tmux", "kill-session", "-t", target.session), env=_default_server_env())
    else:
        _run("kill", target, ("ssh", target.host or "", f"tmux kill-session -t {shlex.quote(target.session)}"))
