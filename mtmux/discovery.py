from __future__ import annotations

from dataclasses import dataclass
import subprocess

from .config import load_hosts
from .names import validate_name


@dataclass(frozen=True)
class DiscoveryResult:
    kind: str
    available: bool
    session: str | None = None
    host: str | None = None

    def line(self) -> str:
        if self.kind == "local":
            return f"local:{self.session}"
        if not self.available:
            return f"ssh:{self.host} unavailable"
        return f"ssh:{self.host}:{self.session}"


def _valid_sessions(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        name = line.strip()
        if not name or name.startswith("mtmux:"):
            continue
        try:
            out.append(validate_name(name, "session"))
        except SystemExit:
            continue
    return out


def local_sessions() -> list[str]:
    proc = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], text=True, capture_output=True)
    if proc.returncode != 0:
        return []
    return _valid_sessions(proc.stdout)


def _bell_sessions(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        name, _, flag = line.partition(":")
        if name.startswith("mtmux") or (flag not in ("1", "!") and "!" not in flag):
            continue
        try:
            out.add(validate_name(name, "session"))
        except SystemExit:
            continue
    return out


def local_bell_sessions() -> set[str]:
    subprocess.run(["tmux", "set-window-option", "-g", "monitor-bell", "on"], text=True, capture_output=True, check=False)
    subprocess.run(["tmux", "set-option", "-g", "bell-action", "any"], text=True, capture_output=True, check=False)
    proc = subprocess.run(["tmux", "list-windows", "-a", "-F", "#{session_name}:#{window_bell_flag}:#{window_flags}"], text=True, capture_output=True)
    if proc.returncode != 0:
        return set()
    return _bell_sessions(proc.stdout)


def remote_sessions(host: str) -> list[str] | None:
    validate_name(host, "host")
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=1",
        "-o", "ServerAliveInterval=1",
        "-o", "ServerAliveCountMax=1",
        host,
        'tmux list-sessions -F "#{session_name}" 2>/dev/null || true',
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=3)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    return _valid_sessions(proc.stdout)


def remote_bell_sessions(host: str) -> set[str]:
    validate_name(host, "host")
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=1",
        "-o", "ServerAliveInterval=1",
        "-o", "ServerAliveCountMax=1",
        host,
        'tmux set-window-option -g monitor-bell on 2>/dev/null; tmux set-option -g bell-action any 2>/dev/null; tmux list-windows -a -F "#{session_name}:#{window_bell_flag}:#{window_flags}" 2>/dev/null || true',
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=3)
    except subprocess.TimeoutExpired:
        return set()
    if proc.returncode != 0:
        return set()
    return _bell_sessions(proc.stdout)


def discover() -> list[DiscoveryResult]:
    results = [DiscoveryResult("local", True, session=s) for s in local_sessions()]
    for host in load_hosts():
        validate_name(host, "host")
        sessions = remote_sessions(host)
        if sessions is None:
            results.append(DiscoveryResult("ssh", False, host=host))
        else:
            results.extend(DiscoveryResult("ssh", True, session=s, host=host) for s in sessions)
    return results


def bell_targets() -> set[str]:
    out = {f"local:{session}" for session in local_bell_sessions()}
    for host in load_hosts():
        validate_name(host, "host")
        out.update(f"ssh:{host}:{session}" for session in remote_bell_sessions(host))
    return out
