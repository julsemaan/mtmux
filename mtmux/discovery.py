from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import time
from collections.abc import Callable, Iterable

from .config import load_hosts
from .names import validate_name


REMOTE_COMMAND = 'tmux list-windows -a -F "#{session_name}:#{window_bell_flag}:#{window_flags}" 2>/dev/null || true'


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


@dataclass(frozen=True)
class RemoteSnapshot:
    available: bool
    sessions: tuple[str, ...]
    bells: frozenset[str]


UNAVAILABLE = RemoteSnapshot(False, (), frozenset())


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


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("TMUX", None)
    return env


def local_sessions() -> list[str]:
    proc = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], text=True, capture_output=True, env=_clean_env())
    return _valid_sessions(proc.stdout) if proc.returncode == 0 else []


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
    proc = subprocess.run(
        ["tmux", "list-windows", "-a", "-F", "#{session_name}:#{window_bell_flag}:#{window_flags}"],
        text=True, capture_output=True, env=_clean_env(),
    )
    return _bell_sessions(proc.stdout) if proc.returncode == 0 else set()


def _parse_remote_snapshot(text: str) -> RemoteSnapshot:
    sessions: list[str] = []
    bells: set[str] = set()
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        name, bell_flag, window_flags = parts
        if name == "mtmux":
            continue
        try:
            name = validate_name(name, "session")
        except SystemExit:
            continue
        if name not in sessions:
            sessions.append(name)
        if bell_flag in ("1", "!") or "!" in window_flags:
            bells.add(name)
    return RemoteSnapshot(True, tuple(sessions), frozenset(bells))


def _ssh_command(host: str) -> list[str]:
    return [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "ServerAliveInterval=1", "-o", "ServerAliveCountMax=1",
        validate_name(host, "host"), REMOTE_COMMAND,
    ]


def remote_snapshot(host: str) -> RemoteSnapshot:
    try:
        proc = subprocess.run(_ssh_command(host), text=True, capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return UNAVAILABLE
    return _parse_remote_snapshot(proc.stdout) if proc.returncode == 0 else UNAVAILABLE


def remote_sessions(host: str) -> list[str] | None:
    snapshot = remote_snapshot(host)
    return list(snapshot.sessions) if snapshot.available else None


def remote_bell_sessions(host: str) -> set[str]:
    return set(remote_snapshot(host).bells)


@dataclass
class _Request:
    process: object
    started: float
    timed_out: bool = False


class RemotePoller:
    def __init__(
        self,
        hosts: Iterable[str],
        *,
        popen: Callable[..., object] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hosts = tuple(validate_name(host, "host") for host in hosts)
        self.snapshots: dict[str, RemoteSnapshot | None] = dict.fromkeys(self.hosts)
        self._popen = popen
        self._clock = clock
        self._active: dict[str, _Request] = {}
        self._next = dict.fromkeys(self.hosts, 0.0)

    def tick(self) -> bool:
        now = self._clock()
        for host in self.hosts:
            if host not in self._active and now >= self._next[host]:
                process = self._popen(_ssh_command(host), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self._active[host] = _Request(process, now)

        changed = False
        for host, request in list(self._active.items()):
            returncode = request.process.poll()
            if returncode is None:
                if not request.timed_out and now - request.started >= 10:
                    request.process.terminate()
                    request.timed_out = True
                    changed |= self.snapshots[host] != UNAVAILABLE
                    self.snapshots[host] = UNAVAILABLE
                    self._next[host] = now + 2
                continue
            stdout, _ = request.process.communicate()
            snapshot = UNAVAILABLE if request.timed_out or returncode != 0 else _parse_remote_snapshot(stdout)
            changed |= snapshot != self.snapshots[host]
            self.snapshots[host] = snapshot
            del self._active[host]
            self._next[host] = now + (1 if snapshot.available else 2)
        return changed

    def refresh(self) -> None:
        now = self._clock()
        for host in self.hosts:
            if host not in self._active:
                self._next[host] = now

    def close(self) -> None:
        for request in self._active.values():
            if request.process.poll() is None:
                request.process.terminate()
            request.process.communicate()
        self._active.clear()


def discover() -> list[DiscoveryResult]:
    results = [DiscoveryResult("local", True, session=s) for s in local_sessions()]
    for host in load_hosts():
        snapshot = remote_snapshot(host)
        if not snapshot.available:
            results.append(DiscoveryResult("ssh", False, host=host))
        else:
            results.extend(DiscoveryResult("ssh", True, session=s, host=host) for s in snapshot.sessions)
    return results


def bell_targets() -> set[str]:
    out = {f"local:{session}" for session in local_bell_sessions()}
    for host in load_hosts():
        out.update(f"ssh:{host}:{session}" for session in remote_snapshot(host).bells)
    return out
