---
maintainer: AI
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: SCHEDULER
programming_language: go
---

# Deployment

The scheduler runs as the systemd unit `topsailai_scheduler`. The unit file is
kept in `deploy/topsailai_scheduler.service` so the deployed configuration is
reviewable in the repository rather than existing only on the host.

## Install

```bash
sudo cp deploy/topsailai_scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now topsailai_scheduler
```

## Update

```bash
make restart
```

`make restart` rebuilds the binary and restarts the unit. The restart is not
optional: a running process keeps the inode of the binary it was started from,
so `make build` alone leaves the service executing the previous build. The
process would only pick up the new binary after it happened to exit.

## Operate

```bash
make service                          # unit state
journalctl -u topsailai_scheduler -f  # logs
systemctl stop topsailai_scheduler    # drain runs, then stop
```

## Why the unit sets what it sets

| Setting | Reason |
|---|---|
| `WorkingDirectory` | The scheduler resolves relative defaults against the current directory, most importantly the control socket. Pinning it makes the socket path stable. |
| `SCHEDULER_CONTROL_SOCKET` | Absolute, so the single-instance guard cannot be defeated by starting the daemon from another directory. |
| `SCHEDULER_TASKS_ROOT` | Tasks live outside the code tree; the default relative `tasks` would point at the wrong folder. |
| `SCHEDULER_DEFAULT_PROVIDER_PATH` | Has no default; `run` exits without it. |
| `PATH` | The provider invokes the `topsailai` CLI by name, and the systemd default `PATH` does not contain it. |
| `SCHEDULER_LOG_OUTPUT=stdout` | Lets journald own capture and rotation instead of running a second rotation scheme. |
| `TimeoutStopSec=90` | Exceeds `SCHEDULER_SHUTDOWN_GRACE` (60s) so systemd does not SIGKILL during a legitimate drain. |
| `ReadWritePaths` | `ProtectSystem=strict` makes the filesystem read-only; the daemon must still write the socket, the task lock files, and the run workspace. |

## Single instance

The scheduler has no daemon-wide lock. What it has is a per-task kernel advisory
lock (`flock` on each task's `.lock` file), which prevents the same task running
twice, and a control-socket guard that refuses to start when another scheduler
already answers on the same socket path.

The socket guard is only effective when both instances resolve the same socket
path. The default is `$HOME/.topsailai/scheduler.sock`, an absolute path that
does not depend on the working directory, so two daemons started from different
directories collide on the same socket and the second one is refused. This is a
code-level guarantee, not a unit-file convention: the unit no longer sets
`SCHEDULER_CONTROL_SOCKET` at all.

Starting a second instance manually against the running service is refused:

```text
control socket stopped: control socket
"/root/.topsailai/scheduler.sock" is already in use by a running scheduler
```

## Known limitation

`make clean` deletes `bin/topsailai_scheduler`, which is the unit's `ExecStart`
target. Running it while the service is enabled leaves the unit unable to start
until the next build. Run `make build` afterwards, or avoid `make clean` on a
host where the service is enabled.
