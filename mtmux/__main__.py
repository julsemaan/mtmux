from __future__ import annotations

import argparse
import sys

from .cockpit import cockpit, focus_sidebar
from .config import ensure_config
from .discovery import discover
from .names import parse_target, validate_name
from .switcher import create_local, create_remote, kill, switch


def placeholder(name: str) -> int:
    print(f"mtmux {name}: not implemented yet")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mtmux")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("cockpit", help="launch or attach cockpit")
    sub.add_parser("focus-sidebar", help="focus/open cockpit sidebar")
    sub.add_parser("init", help="create missing config files")
    sub.add_parser("list", help="list discovered targets")

    switch = sub.add_parser("switch", help="switch cockpit target")
    switch.add_argument("target")

    kill_parser = sub.add_parser("kill", help="kill target tmux session")
    kill_parser.add_argument("target")

    create = sub.add_parser("create", help="create target then switch")
    create_sub = create.add_subparsers(dest="create_kind", required=True)
    local = create_sub.add_parser("local", help="create local tmux session")
    local.add_argument("session")
    ssh = create_sub.add_parser("ssh", help="create remote tmux session")
    ssh.add_argument("host")
    ssh.add_argument("session")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["sidebar"]:
        from .sidebar import main as sidebar_main
        return sidebar_main()
    args = build_parser().parse_args(argv)
    if args.command == "init":
        cfg, wrapper = ensure_config()
        print(f"Config: {cfg}")
        print(f"Wrapper: {wrapper}")
        return 0
    if args.command == "cockpit":
        return cockpit()
    if args.command == "focus-sidebar":
        return focus_sidebar()
    if args.command == "list":
        for item in discover():
            print(item.line())
        return 0
    if args.command == "switch":
        switch(parse_target(args.target))
        return 0
    if args.command == "kill":
        kill(parse_target(args.target))
        return 0
    if args.command == "create":
        if args.create_kind == "local":
            create_local(validate_name(args.session, "session"))
        else:
            create_remote(validate_name(args.host, "host"), validate_name(args.session, "session"))
        return 0
    return placeholder(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
