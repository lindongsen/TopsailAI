---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: scheduler
programming_language: go
---

# Environment Variables

Every variable has a default, so the scheduler starts correctly with no
configuration at all. Values are read once at startup and converted into typed
configuration; a malformed value is a startup error rather than a silent
fallback, so a typo in a duration cannot be mistaken for the default.

All variables use the `SCHEDULER_` prefix.

## Paths and control

| Variable | Default | Meaning |
|---|---|---|
| `SCHEDULER_TASKS_ROOT` | `tasks` | Root of the task tree. Relative paths resolve against the working directory. The `run --tasks-root` flag takes precedence when both are set. |
| `SCHEDULER_CONTROL_SOCKET` | `scheduler.sock` | Unix socket the daemon listens on and the CLI connects to. Relative paths resolve against the working directory, so each project folder gets its own daemon. |

## Logging

| Variable | Default | Meaning |
|---|---|---|
| `SCHEDULER_LOG_LEVEL` | `info` | `debug`, `info`, `warn`, or `error`. An unknown level is rejected at startup. |
| `SCHEDULER_LOG_OUTPUT` | `stdout` | `stdout`, `stderr`, or a file path. |
| `SCHEDULER_LOG_MAX_SIZE_MB` | `100` | Size in MB at which the log rotates. |
| `SCHEDULER_LOG_MAX_BACKUPS` | `10` | Number of rotated files retained. |
| `SCHEDULER_LOG_MAX_AGE_DAYS` | `30` | Maximum age of a rotated file in days. |
| `SCHEDULER_LOG_COMPRESS` | `false` | Compress rotated files. |

Logs are JSON, one object per line, and every entry carries a `task` field when
it belongs to a task. Rotation is implemented in-process, so no external
`logrotate` is required.

## Execution

| Variable | Default | Meaning |
|---|---|---|
| `SCHEDULER_DEFAULT_PROVIDER_PATH` | none, required by `run` | Executable of the provider used by a task that names none. A relative path is resolved against the working directory. |
| `SCHEDULER_POLL_INTERVAL` | `5s` | How often a supervised run is polled for its lifecycle state. |
| `SCHEDULER_PROVIDER_CALL_TIMEOUT` | `30s` | How long one provider call may take before it is treated as failed. |
| `SCHEDULER_WORKSPACE` | working directory | Default workspace for a task that sets none. |
| `SCHEDULER_DEFAULT_TIMEOUT` | `30m` | Timeout for a task that sets none. |
| `SCHEDULER_MAX_CONCURRENT` | `4` | Maximum number of runs executing at once. |
| `SCHEDULER_MAX_OUTPUT_BYTES` | `65536` | Captured output retained per run; the rest is truncated and flagged. |
| `SCHEDULER_MIN_TASK_CONTENT_RUNES` | `30` | Shortest task content accepted, counted in characters after trimming whitespace. A shorter file makes the task `invalid`. |

The scheduler does not know how any provider starts a run. Everything specific
to an agent — its executable, its arguments, the variable that carries the task
content — belongs to the provider, not to the scheduler. See
`docs/Provider_Contract.md`.

## Lifecycle

| Variable | Default | Meaning |
|---|---|---|
| `SCHEDULER_RESCAN_INTERVAL` | `30s` | How often the task tree is rescanned for added, changed, and removed tasks. |
| `SCHEDULER_SHUTDOWN_GRACE` | `60s` | How long `SIGTERM` waits for running tasks before killing them. |

## Notes

- Durations accept Go duration syntax, for example `30s`, `5m`, `2h`.
- `SCHEDULER_MAX_CONCURRENT` bounds concurrency, not queueing. A task that is
  already running is skipped rather than queued.
- The `-m raw` requirement belongs to the scheduler-provider-topsailai provider, not to the
  scheduler. See `providers/scheduler-provider-topsailai/README.md`.
