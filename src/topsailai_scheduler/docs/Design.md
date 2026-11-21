---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: scheduler
programming_language: go
---

# Design

## Shape

One long-lived daemon holds the schedule in-process. The CLI talks to it over a
Unix socket. Tasks are plain files on disk.

```text
tasks/  ──scan──▶  daemon (cron in-process)  ──launch──▶  runner (process group)
                        ▲                                      │
                        └──────── control socket ◀── CLI ───────┘
```

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Long-lived daemon with an in-process cron, not a per-minute crontab scan | The daemon owns the schedule: one process, no crontab entry per task, no overlapping scans, and second-level precision is available later. |
| D2 | Task identity is the `.yaml` path relative to the tasks root, without extension | Nesting works for free and the identity is stable and human-readable. |
| D3 | The `.yaml` is the anchor; `.md` is required, `.lock` is created on demand | Discovery walks for `*.yaml`. A missing `.md` is a configuration error, not a silent skip. The lock is a handle, so it need not pre-exist. |
| D4 | Locking uses `flock` on `{stem}.lock`, non-blocking | Kernel-level lock tied to an open file descriptor, released automatically when the process dies. A crashed run cannot leave a task permanently locked. Non-blocking means a still-running task is skipped rather than queued. |
| D5 | The lock lives in its own file, never on the `.md` | A lock is bound to a file, not a path. Editing or replacing the `.md` would move the lock and let the same task run twice. |
| D6 | YAML parsing is strict | A typo such as `schedul:` would otherwise be silently ignored and the task would never run. |
| D7 | Hot reload by periodic rescan, diffed by id and content fingerprint | "Adding a task means adding files" must hold without a restart. A rescan is cheap at this scale and avoids a filesystem watcher dependency. |
| D8 | Each run executes in its own process group; timeout kills the group | A task that spawns children must not leave orphans behind when it is killed. |
| D9 | One structured JSON log for all tasks, with a `task` field | Per-task log files multiply rotation configuration. A single rotated stream with a `task` field is queryable and bounded. |
| D10 | Missed runs are not replayed | Matches native cron. Replaying after downtime would cause a burst of tasks at boot. |
| D11 | The lock file also carries a record naming the in-flight run | The flock says whether a scheduler owns the task; it cannot say which run was in flight when the last scheduler died. A run outlives the scheduler, so after a restart the lock is free while the run may still be working. The record is advisory; the flock stays the authority. |
| D12 | The record is rewritten in place, never through a rename | A rename gives the path a new inode while the flock stays bound to the old one, so the next process would lock the new file successfully and mutual exclusion would be silently gone. |
| D13 | A stop for an unsupervised run is best effort and says so | After a restart the run table is empty, so the record is the only way to reach the run. The scheduler holds no context to cancel and no loop to observe the outcome, so it forwards a request and reports `best_effort`. Claiming more would be a lie the caller cannot detect. |

## Packages

| Package | Responsibility |
|---|---|
| `config` | Reads the environment once, validates it, exposes typed configuration. |
| `logging` | JSON logger with rotation and a `task` field. |
| `task` | Discovers `*.yaml`, parses strictly, computes the content fingerprint. |
| `lock` | Non-blocking `flock` on the task's `.lock`, plus the advisory record naming the in-flight run. |
| `runner` | Starts a process group, enforces the timeout, captures bounded output. |
| `launcher` | Registry of launch strategies: `agent` and `command`. |
| `runtime` | The control contract: request and result types, sentinel errors. |
| `daemon` | Cron registration, rescan and reconcile, concurrency bound, shutdown. |
| `control` | Unix socket transport: protocol, server, client. |
| `main` | Entry point, CLI subcommands, flag parsing. |

## Control contract

Launch, status, and stop are one standardized contract, so behaviour cannot
diverge between transports.

```go
type Controller interface {
	Launch(LaunchRequest) (LaunchResult, error)
	Status() (Snapshot, error)
	Stop(StopRequest) (StopResult, error)
}
```

The daemon is the only implementation. A transport decodes its own request
format and calls these methods. The Unix socket transport is the first one; a
second transport would reuse the same contract unchanged.

Errors are sentinel values, so a caller classifies a failure without parsing
text: `ErrTaskNotFound`, `ErrTaskNotRunning`, `ErrTaskDisabled`,
`ErrShuttingDown`.

### Machine-readable output

`status --json`, `launch --json`, and `stop --json` emit the contract structs
directly. Field names are snake_case and identical to the wire format, so one
consumer can read both surfaces without a translation layer.

## Concurrency

`SCHEDULER_MAX_CONCURRENT` bounds how many runs execute at once. A task already
running is skipped, not queued: queueing would only delay a run that the next
trigger attempts again anyway.

## Shutdown

`SIGTERM` stops accepting new runs, waits up to `SCHEDULER_SHUTDOWN_GRACE` for
running tasks, then kills the remaining process groups. No orphan survives.

## CLI

| Command | Meaning |
|---|---|
| `run` | Start the daemon. |
| `status [--json]` | Report every task's state, schedule, next run, and last exit. |
| `launch <task-id> [--wait] [--json]` | Start one run now. `--wait` reports the outcome. |
| `stop <task-id> [--force] [--json]` | Stop a running task. `--force` sends `SIGKILL`. |

Exit codes: `0` success, `1` failure, `2` usage error.
