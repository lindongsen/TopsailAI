---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: scheduler
programming_language: go
---

# Scheduler

A Go scheduler that discovers scheduled tasks from the `tasks/` folder tree and
runs them on their cron schedule.

Each task is plain files on disk. Adding a task means adding files; removing a
task means deleting files. No code change and no restart are needed.

## Task layout

Every task is three files that share one stem:

```text
tasks/
├── data/
│   ├── work.yaml     # configuration: when and how to run
│   ├── work.md       # task content handed to the agent
│   └── work.lock     # runtime lock, prevents parallel runs
└── daily/nightly/
    ├── report.yaml
    ├── report.md
    └── report.lock
```

The task id is the `.yaml` path relative to the tasks root, without the
extension: `tasks/data/work.yaml` is task `data/work`. Folders are free-form
grouping and may nest arbitrarily; they do not affect scheduling.

## Quick start

```bash
make build          # build bin/topsailai_scheduler
make check          # gofmt, vet, and the full test suite
./bin/topsailai_scheduler run
```

In another shell, in the same folder:

```bash
./bin/topsailai_scheduler status
./bin/topsailai_scheduler launch data/work --wait
./bin/topsailai_scheduler stop data/work
./bin/topsailai_scheduler check
./bin/topsailai_scheduler check data/work
```

`check` validates the task tree without a daemon, so it can run in CI or before a
restart. It reports every task with its reason and exits non-zero when any task is
invalid. Given one task id or path it validates only that task.

The CLI finds the daemon through `SCHEDULER_CONTROL_SOCKET`, which defaults to
`$HOME/.topsailai/scheduler.sock`. The path is absolute and independent of the
working directory, so one machine has one scheduler socket and a second daemon
started from any folder is refused instead of quietly running alongside the
first.

## Choosing the tasks folder

The tasks folder defaults to `tasks` in the working directory. Two ways change
it, and the command line wins:

```bash
# environment variable, applies to every command
SCHEDULER_TASKS_ROOT=/srv/jobs ./bin/topsailai_scheduler run

# command-line flag, applies to this daemon only
./bin/topsailai_scheduler run --tasks-root /srv/jobs
```

When both are set, `--tasks-root` takes precedence. That ordering lets one
machine keep a default in the environment while a single daemon points at a
different tree. A relative value is resolved against the working directory, so
`--tasks-root ./jobs` and `--tasks-root /abs/path/jobs` both work.

The daemon logs the resolved absolute path at startup, and `status --json`
reports it as `tasks_root`, so the effective value is always observable.

## A minimal task

A task is a YAML file beside a Markdown file of the same name:

```yaml
schedule: "0 8 * * *"
launcher: command
provider: providers/mock/bin/mock
command: /bin/sh
args: ["-c", "echo hello"]
```

```markdown
# Hello

Print a greeting.
```

The task runs every day at 08:00. `launch hello --wait` runs it immediately and
reports the outcome.

`provider: providers/mock/bin/mock` is what makes the `command` meaningful. The
default provider is whatever `SCHEDULER_DEFAULT_PROVIDER_PATH` names, and the
shipped `scheduler-provider-topsailai` launches an agent and ignores `command`; a
task that wants to run a specific executable points at a provider that runs one,
such as `mock`.

## Documentation

| Document | Contents |
|---|---|
| `docs/Task_Format.md` | The three files, the YAML schema, placeholders, locking. |
| `docs/Environment_Variables.md` | Every `SCHEDULER_` variable and its default. |
| `docs/Design.md` | Architecture, decisions, the control contract, the CLI. |
| `docs/Seam.md` | The control contract, the launcher seam, and the provider seam. |
| `docs/Provider_Contract.md` | The standard a provider implements, written for a provider author. |
| `docs/Deployment.md` | The systemd unit, how to install and update it, and the single-instance guard. |

## What the scheduler is responsible for

The scheduler is a **process supervisor**, not a judge of results. It answers two
questions: did the run start, and is it still running.

Whether a task succeeded is decided by the task's `.md`, which tells the agent
what counts as done and what signal proves it. The scheduler does not interpret
that signal and records no `succeeded` field.

A round is supervised like this:

1. Take `{stem}.lock`, so a second run of the same task cannot start.
2. Ask the task's provider to `start` the run, and read the handle it returns.
3. Poll the provider every `SCHEDULER_POLL_INTERVAL` until it reports `finished`.
4. Release the lock and record the supervision outcome.

The lock is held for the whole supervision, not just for the `start` call.
Otherwise a background run would keep working after its lock was released, and
the next tick would start a duplicate.

See `docs/Seam.md` for the full contract.

## Providers

The scheduler does not know how a task is run. It asks a **provider**, which is
an independent program speaking a small JSON protocol over stdin and stdout:

```text
/srv/providers/mock/bin/mock start|poll|stop
```

A provider is addressed by its executable path, so it can be a compiled binary, a
shell script or a Python script, and it may live anywhere on disk. It is
maintained as its own project and can be replaced without rebuilding the
scheduler.

Two providers ship with this repository, each an independent workspace:

| Provider | Purpose |
|---|---|
| `providers/mock` | Runs the command a task names. Used by the integration tests, and a worked example of the protocol. |
| `providers/scheduler-provider-topsailai` | Launches a TopsailAI agent and reports whether it is still working. |

A task selects one with `provider:` in its YAML, giving the executable path. A
task that names none uses `SCHEDULER_DEFAULT_PROVIDER_PATH`, which the scheduler
requires at startup.

To add a provider, create an executable implementing `docs/Provider_Contract.md`
and point a task or the scheduler at it. No scheduler code change is needed.

## Choosing the provider executable

The default provider is required, because a scheduler with no provider cannot run
anything:

```bash
SCHEDULER_DEFAULT_PROVIDER_PATH=/srv/providers/mock/bin/mock ./bin/topsailai_scheduler run
```

A relative path is resolved against the working directory, the same rule as
`SCHEDULER_TASKS_ROOT` and the control socket. The resolved absolute path is what
the scheduler reports, records in the lock file and compares during restart
reconciliation, so a provider that moves is reported as a mismatch rather than
silently replaced.

Only `run` requires the variable. `status`, `launch` and `stop` are clients
talking to a daemon that already validated its own configuration.

## Layout

| Path | Role |
|---|---|
| `src/` | Go module `topsailai_scheduler` |
| Task tree | `/work/scheduler/tasks`, outside this repository; set `SCHEDULER_TASKS_ROOT` |
| `providers/` | Provider projects, each an independent workspace |
| `tests/integration/` | End-to-end tests driving the real binary |
| `tests/live/` | Field-level assertions on the request the provider receives |
| `tests/bdd/` | Operator-visible behaviour, one feature per module |
| `docs/` | Task format, environment variables, design, seams, BDD map |
| `.task/` | Plan, review and check artifacts maintained by AI |
| `deploy/` | The systemd unit, kept in the repository so the deployed configuration is reviewable |

## Testing

```bash
make test                                   # unit tests with the race detector
make cover                                  # per-package coverage
bash tests/integration/startup.sh           # start the daemon in tmux
bash tests/integration/run.sh               # drive and assert the behaviour
bash tests/live/run.sh                      # assert every field the provider receives
python3 -m pytest tests/bdd -q --color=no   # operator-visible behaviour
```

The integration suite runs the real binary against a temporary task tree and
asserts discovery, strict parsing, locking, timeout kill, hot reload, the JSON
contract, and shutdown without orphans. Tasks run through `providers/mock`, so
the whole path from task file to supervised run is exercised without an agent.

The live suite asserts the request the provider actually receives: the protocol
version, the task identity, every placeholder, the environment, the workspace and
the timeout. The mock provider records the request verbatim, so a field the
scheduler forgot is a failure rather than a silently ignored value.

The BDD suite states the behaviour in the operator's language and covers
discovery, execution, configuration, locking, restart reconciliation, the CLI
contract, cron scheduling, concurrency and shutdown, and launcher selection. See
`docs/BDD_Tests.md` for the module map and the harness design.

Each provider is tested in its own workspace:

```bash
python3 providers/mock/tests/test_mock.py
python3 providers/scheduler-provider-topsailai/tests/test_topsailai.py
```

## Behaviour worth knowing

- A missing `.md` or an unknown YAML key makes the task `invalid`; it is
  reported and never runs.
- `enabled: false` pauses a task without deleting it: it stays in `status` as
  `disabled`, is never scheduled, and a manual `launch` is refused.
- Adding, removing or editing task files takes effect without a restart, on the
  next rescan, so a change can take up to `SCHEDULER_RESCAN_INTERVAL` to apply.
- A task already running is skipped, not queued.
- A run exceeding its timeout is stopped through its provider, which ends the
  run's process group so children do not survive as orphans.
- Missed runs are not replayed, matching native cron.
- Logs are JSON, rotated by size, and bounded by backup count and age.
- A run's exit code is recorded as a lifecycle fact, never as a verdict.
