# mtmux

Outer tmux cockpit for local and SSH tmux sessions.

## Install

```sh
pip install -e .
```

## Use

```sh
mtmux init
mtmux cockpit
```

`mtmux cockpit` creates/attaches outer tmux server:

```sh
tmux -L mtmux
```

Outer tmux owns layout only:

- outer prefix: `C-g`
- outer status: off
- left pane: `mtmux` sidebar, 30 cols
- right pane: selected local/remote tmux attach client

Inner local/remote tmux sessions keep their normal prefix.

## Config

Files live in `~/.config/mtmux/`:

```toml
hosts = ["prod", "dev"]
```

Hosts are SSH aliases only. Put users, ports, keys, proxies, IPv6, etc. in `~/.ssh/config`.

Names must match:

```text
[A-Za-z0-9_.-]{1,64}
```

## Commands

```sh
mtmux list
mtmux switch local:<session>
mtmux switch ssh:<host>:<session>
mtmux create local <session>
mtmux create ssh <host> <session>
```

Switching uses outer tmux `respawn-pane` on right pane. Real tmux sessions stay alive.

## Sidebar keys

- `Enter`: switch selected target
- `n`: create session for selected group/target
- `r`: refresh discovery
- `/`: filter
- `?`: open help in right pane
- `q`: quit sidebar only

## Recovery

Rerun:

```sh
mtmux cockpit
```

It reuses valid cockpit, repairs broken window, and respawns missing sidebar.

Missing cockpit for switch/create prints:

```text
No valid mtmux cockpit. Run: mtmux cockpit
```
