<p align="center">
  <img src="logo.png" alt="mtmux logo" width="280">
</p>

<h1 align="center">mtmux</h1>

<p align="center">
  One terminal. Every tmux session, local or remote.
</p>

`mtmux` gives tmux a cockpit: a persistent sidebar for finding, opening, and switching between sessions across your machine and SSH hosts. Your sessions stay ordinary tmux sessions; mtmux simply puts them within reach.

No more terminal-tab archaeology. Star the sessions that matter, jump between machines without leaving the keyboard, and notice bells from sessions that need you.

## Why mtmux?

- **One view across machines**: local and remote sessions live in the same sidebar.
- **Fast context switches**: view which sessions require your attention via tmux bells then quickly get to them.
- **Built for your existing flow**: mtmux works with your existing tmux configuration and workflows.

## Quick start

Requires Python 3.11+, tmux, and OpenSSH.

```sh
git clone https://github.com/julsemaan/mtmux.git
cd mtmux
pip install -e .
mtmux init
mtmux cockpit
```

That opens an outer tmux workspace with the mtmux sidebar on the left and your selected session on the right. Press `Enter` on a session to step into it; press `C-s s` whenever you want the cockpit back.

## How it works

`mtmux cockpit` creates or attaches to a dedicated outer tmux server (`tmux -L mtmux`). That outer layer owns only the layout:

- outer prefix: `C-s`
- focus/open sidebar: `C-s s`
- outer status: off
- left pane: `mtmux` sidebar, 40 columns by default
- right pane: selected local/remote tmux attach client

Inner local and remote sessions keep their normal tmux prefix and remain alive when you switch away.

## Configuration

Files live in `~/.config/mtmux/`:

```toml
hosts = ["prod", "dev"]
prefix = "C-s"
sidebar_width = 40
status_timeout = 5
```

`prefix` accepts one non-empty, printable tmux key token without whitespace. `sidebar_width` sets left pane width in columns. `status_timeout` controls how many seconds sidebar feedback remains visible. Both numeric settings must be positive integers. Restart sidebar by rerunning `mtmux cockpit` after changing these values.

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

## CLI commands

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
