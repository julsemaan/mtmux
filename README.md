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

- outer prefix: `C-s`
- focus/open sidebar: `C-s s`
- outer status: off
- left pane: `mtmux` sidebar, 40 cols by default
- right pane: selected local/remote tmux attach client

Inner local/remote tmux sessions keep their normal prefix.

## Config

Files live in `~/.config/mtmux/`:

```toml
hosts = ["prod", "dev"]
prefix = "C-s"
sidebar_width = 40
```

`prefix` accepts one non-empty, printable tmux key token without whitespace. `sidebar_width` sets left pane width in columns and must be a positive integer. Rerun `mtmux cockpit` after changing either value.

`C-s` normally sends XOFF when terminal `IXON` flow control is enabled. Attached tmux disables flow control on outer tty, so outer prefix works without global `stty` changes. Readline, Emacs, or Vim `C-s` commands require `C-s C-s` to forward literal `C-s`; inner tty may still treat it as XOFF, in which case `C-q` resumes output.

To restore old prefix, set `prefix = "C-g"` and rerun `mtmux cockpit`.

Hosts are SSH aliases only. Put users, ports, keys, proxies, IPv6, etc. in `~/.ssh/config`.

For fast background discovery, let OpenSSH reuse one authenticated transport per host:

```sshconfig
Host prod dev
    ControlMaster auto
    ControlPersist 10m
    ControlPath ~/.ssh/mtmux-%C
```

`ControlMaster` makes first SSH process own shared connection. `ControlPersist` keeps it alive after command exits. Later discovery polls, switches, creates, and kills open logical channels without repeating TCP setup, key exchange, or authentication. Keep control socket in directory writable only by your user.

Check multiplexing and compare first/subsequent connection times:

```sh
ssh prod true
ssh -O check prod
time ssh prod true
time ssh prod true
```

No mtmux multiplexing option exists; SSH aliases remain source of truth.

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
mtmux kill local:<session>
mtmux kill ssh:<host>:<session>
```

Switching uses outer tmux `respawn-pane` on right pane. Real tmux sessions stay alive.

## Sidebar keys

- `C-s s`: focus sidebar; recreates it if quit
- `Enter`: switch selected target
- `f`: star or unstar selected target
- `n`: create session for selected group/target
- `x`: kill selected session (asks first)
- `r`: refresh discovery
- `/`: filter
- `?`: open help in right pane
- `q`: quit sidebar only

Starred sessions appear first, sorted by full target (`local:work`, `ssh:dev:work`), and remain in their LOCAL/SSH sections. Each STARRED entry uses two rows: session name first, then local hostname or SSH host. Long text is truncated with an ellipsis. Filtering matches session names. Favorites persist in `~/.config/mtmux/stars`; unavailable favorites remain selectable so `f` can remove them, while switch and kill report them unavailable. Set `MTMUX_ASCII=1` for text-only stars, source labels, and ellipses.

## Mouse controls

- click sidebar row: select
- double-click sidebar row: switch or create
- wheel over sidebar: navigate
- right-pane mouse events: forwarded by outer tmux to mouse-aware applications

Tmux mouse capture may require holding `Shift` for terminal-native text selection.

## Clipboard

Native tmux copy mode forwards copied text through nested sessions using OSC 52. Physical terminal must support and enable OSC 52 clipboard access. mtmux declares inner clients as `clipboard` capable and sets outer server option `set-clipboard on`; inner tmux configuration remains unchanged, including explicit `set-clipboard off`.

**Security:** `set-clipboard on` permits processes in local and remote panes to set system clipboard through OSC 52. Only connect to trusted hosts and run trusted pane processes.

## Recovery

Press `C-s s` or rerun:

```sh
mtmux cockpit
```

It reuses valid cockpit, repairs broken window, and respawns missing sidebar.

Missing cockpit for switch/create prints:

```text
No valid mtmux cockpit. Run: mtmux cockpit
```
