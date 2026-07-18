from __future__ import annotations

from dataclasses import dataclass
import re

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def validate_name(value: str, label: str = "name") -> str:
    if not NAME_RE.fullmatch(value):
        raise SystemExit(f"Invalid {label}: {value!r}. Must match [A-Za-z0-9_.-]{{1,64}}")
    return value


@dataclass(frozen=True)
class Target:
    kind: str
    session: str
    host: str | None = None

    def format(self) -> str:
        if self.kind == "local":
            return f"local:{self.session}"
        return f"ssh:{self.host}:{self.session}"


def parse_target(text: str) -> Target:
    parts = text.split(":")
    if len(parts) == 2 and parts[0] == "local":
        return Target("local", validate_name(parts[1], "session"))
    if len(parts) == 3 and parts[0] == "ssh":
        return Target("ssh", validate_name(parts[2], "session"), validate_name(parts[1], "host"))
    raise SystemExit("Invalid target. Use local:<session> or ssh:<host>:<session>")
