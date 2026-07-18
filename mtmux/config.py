from __future__ import annotations

import os
from pathlib import Path
import tomllib

DEFAULT_PREFIX = "C-s"
CONFIG_TEXT = f'hosts = []\nprefix = "{DEFAULT_PREFIX}"\n'
WRAPPER_TEXT = """unbind C-b
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


def _load_config() -> tuple[Path, dict]:
    cfg, _ = ensure_config()
    try:
        return cfg, tomllib.loads(cfg.read_text())
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"Invalid config TOML {cfg}: {e}") from e


def load_prefix() -> str:
    cfg, data = _load_config()
    prefix = data.get("prefix", DEFAULT_PREFIX)
    if not isinstance(prefix, str) or not prefix or not prefix.isprintable() or any(char.isspace() for char in prefix):
        raise SystemExit(f"Invalid config {cfg}: prefix must be a non-empty, printable, whitespace-free string")
    return prefix


def load_hosts() -> list[str]:
    cfg, data = _load_config()
    hosts = data.get("hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        raise SystemExit(f"Invalid config {cfg}: hosts must be a list of strings")
    return hosts
