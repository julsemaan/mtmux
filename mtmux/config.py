from __future__ import annotations

import os
from pathlib import Path
import tomllib

CONFIG_TEXT = "hosts = []\n"
WRAPPER_TEXT = """set -g prefix C-g
unbind C-b
bind C-g send-prefix
set -g status off
set -g mouse off
"""


def config_dir() -> Path:
    override = os.environ.get("MTMUX_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "mtmux"


def paths() -> tuple[Path, Path]:
    base = config_dir()
    return base / "config.toml", base / "wrapper.tmux.conf"


def ensure_config() -> tuple[Path, Path]:
    cfg, wrapper = paths()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    if not cfg.exists():
        cfg.write_text(CONFIG_TEXT)
    if not wrapper.exists():
        wrapper.write_text(WRAPPER_TEXT)
    return cfg, wrapper


def load_hosts() -> list[str]:
    cfg, _ = ensure_config()
    try:
        data = tomllib.loads(cfg.read_text())
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"Invalid config TOML {cfg}: {e}") from e
    hosts = data.get("hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        raise SystemExit(f"Invalid config {cfg}: hosts must be a list of strings")
    return hosts
