---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: scheduler
programming_language: go
---

# Task Format

A task is three files that share one stem. The `.yaml` file is the anchor: the
scheduler discovers tasks by walking the tasks root for `*.yaml`.

```text
tasks/
├── data/
│   ├── work.yaml
│   ├── work.md
│   └── work.lock
└── daily/nightly/
    ├── report.yaml
    ├── report.md
    └── report.lock
```

## File roles

| File | Role | Required | Versioned |
|---|---|---|---|
| `{stem}.yaml` | Configuration: when and how to run. | Yes | Yes |
| `{stem}.md` | Task content handed to the agent. | Yes | Yes |
| `{stem}.lock` | Runtime lock, prevents parallel runs of this task. | No, created on demand | No |

A missing `.md` is a configuration error, not a silent skip. The task is
reported as `invalid` and never runs.

## Content requirements

Both files must carry real content. A task that fails any check below is
reported as `invalid`, is never registered with the schedule, and never runs.
The other tasks in the tree are unaffected: a rejected task is skipped, not
fatal.

| Check | Rejected when |
|---|---|
| `.yaml` is empty | The file holds only whitespace. |
| `.yaml` is unparseable | The YAML is malformed or contains an unknown key. |
| `.yaml` lacks `schedule` | The `schedule` key is absent or empty. |
| `.md` is empty | The file holds only whitespace. |
| `.md` is too short | Fewer characters remain after trimming whitespace than the configured floor. |

The length is counted in characters, not bytes, so a short Chinese phrase is
measured the same way as a short English one. The floor defaults to 30
characters and is configurable through `SCHEDULER_MIN_TASK_CONTENT_RUNES`, so a
deployment can raise or lower it without a rebuild. A content file that only
says `TODO` is rejected because the agent would have nothing to act on.

The rejection reason names the file and the actual count, for example
`task content work.md has 4 characters, at least 30 are required`. The daemon
logs it once per unchanged failure and logs a recovery when the file becomes
valid again.

## Task identity

The task id is the `.yaml` path relative to the tasks root, without the
extension. `tasks/data/work.yaml` is task `data/work`.

Folders are free-form grouping and may nest arbitrarily. Folders do not affect
scheduling. A task id only needs to be unique within the tree, which the path
guarantees.

## YAML schema

```yaml
schedule: "0 8 * * *"     # required, 5-field cron or @daily style
enabled: true             # optional, default true
launcher: agent           # optional, agent or command, default agent
provider: /srv/providers/mock/bin/mock  # optional, default SCHEDULER_DEFAULT_PROVIDER_PATH
command: /bin/true        # optional, only for the command launcher
args: []                  # optional, extra arguments
workspace: /work/foo      # optional, default SCHEDULER_WORKSPACE
timeout: 30m              # optional, default SCHEDULER_DEFAULT_TIMEOUT
env:                      # optional, extra environment for this task
  KEY: value
```

Parsing is strict. An unknown key is a hard error naming the file, so a typo
such as `schedul:` cannot silently leave a task unscheduled.

### schedule

Standard cron syntax: lists (`1,3,5`), ranges (`1-5`), steps (`*/10`), month and
weekday names, and `@daily` style shortcuts.

When both day-of-month and day-of-week are restricted, cron combines them with
OR, not AND. `0 8 1 * 1` means the first of the month **or** every Monday.

### enabled

Defaults to `true`. A disabled task is discovered and reported but never
scheduled.

### launcher

Selects how the task's request is built. Two launchers are built in.

| Launcher | Behaviour |
|---|---|
| `agent` | Leaves the invocation to the provider. This is the default. |
| `command` | Asks the provider to run `command` with `args`. |

The launcher does not decide how a task is run; the provider does. `agent` is the
default because a provider such as `scheduler-provider-topsailai` already knows how to launch its
agent, so the scheduler does not need to describe the command line.

`command` is only meaningful with a provider that runs whatever it is told, such
as `mock`. A provider that wraps one fixed tool ignores it.

### provider

Path to the program that runs the task. It may point anywhere on disk, so a
provider does not have to live under a particular folder. Omitted means
`SCHEDULER_DEFAULT_PROVIDER_PATH`, which the scheduler requires at startup.

A relative path is resolved against the scheduler working directory, the same
rule as `SCHEDULER_TASKS_ROOT` and the control socket. The resolved absolute
path is what the scheduler reports, records in the lock file and compares during
restart reconciliation, so a provider that moves is reported as a mismatch
rather than silently replaced.

The provider executable is checked when the task tree is scanned, not when the
task first fires. A task naming a missing provider is reported as `invalid` with
the reason and is not scheduled, so a typo is visible immediately instead of
failing on every trigger. The task still appears in `status`, so a manual launch
reports the real reason rather than claiming the task does not exist.

A provider is an independent program speaking the protocol in
`docs/Provider_Contract.md`. It can be a compiled binary, a shell script or a
Python script; the scheduler does not care which.

### Placeholders

`command`, `args`, and `workspace` support these placeholders, substituted
before the run starts.

| Placeholder | Value |
|---|---|
| `{task}` | Absolute path of the `.md` file. |
| `{task_id}` | Task id, for example `data/work`. |
| `{task_dir}` | Absolute path of the folder holding the task. |
| `{stem}` | Filename stem, for example `work`. |
| `{workspace}` | The run's workspace. |

### timeout

A duration such as `30m` or `2s`. A run exceeding it is stopped through its
provider, which ends the run and its process group so a task that spawns children
leaves no orphan.

### env

Extra environment variables injected into the run for this round only:

```yaml
env:
  PROJECT_STAGE: staging
  EXTRA_FLAG: "1"
```

They are merged over the scheduler's own environment, so a task's value wins over
an inherited one. This is the supported way to give one task its own environment;
it needs no scheduler-wide setting and no code change.

The scheduler adds no variable of its own, so there is no reserved name a task
could collide with. A provider may still override a key it needs: the scheduler-provider-topsailai
provider sets `TOPSAILAI_INTERACTIVE_MODE=0` and `TOPSAILAI_TASK` after applying
the task's `env`, because a task that switched the agent back to interactive mode
or redirected the task content would break supervision. That precedence is
documented in `providers/scheduler-provider-topsailai/README.md`.

## Reserved for later extension

Task dependencies are planned but not implemented. The YAML struct is a plain
struct, so a new key is a one-line addition.

## Locking

The lock is `flock` on `{stem}.lock`, taken in non-blocking mode.

- The lock is a kernel lock tied to an open file descriptor, so it is released
  automatically when the process dies. A crashed run cannot leave a task
  permanently locked.
- The lock lives in its own file, never on the `.md`. A lock is bound to a file,
  not a path, so editing or replacing the `.md` would move the lock to a new
  file and let the same task run twice.
- If the lock is already held, the run is skipped and logged. Waiting would only
  queue runs that the next trigger will attempt again anyway.
- The lock is held for the whole supervision, not just for the provider's `start`
  call. A provider returns a handle promptly and works in the background, so a
  lock released at `start` would be free while the run was still working and the
  next tick would start a duplicate.
- The `.lock` file persists on disk. It is a handle, not a state marker; its
  presence does not mean the task is running.

## Adding and removing tasks

Adding a task means adding the `.yaml` and `.md` pair. Removing a task means
deleting them. The daemon rescans the tree every `SCHEDULER_RESCAN_INTERVAL`
and diffs by task id and content fingerprint, so no restart is needed.

Missed runs are not replayed. A task whose time passed while the machine was
off is skipped, matching native cron behaviour.
