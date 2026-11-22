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

## Discovery

Tasks are found by walking the tasks root, so adding a task means adding files
and nothing else. No registration step and no code change are involved.

The scan rules:

- Only `*.yaml` files are tasks. The extension match is case-insensitive.
- The walk is recursive, so folders may nest arbitrarily.
- A subfolder whose name starts with `.` is skipped, which keeps `.git` and
  `.tmp` out of the scan. The tasks root itself is scanned even if its own name
  starts with `.`.
- A folder that cannot be read is reported and skipped; the rest of the tree
  still loads.
- A missing tasks root is not an error. An empty scheduler is a valid state, so
  an absent folder yields no tasks rather than a failure. A tasks root that
  exists but is not a directory is an error.
- Tasks are returned sorted by id, so the order is stable across scans.

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
| `schedule` is not a cron expression | The expression cannot be parsed, for example `every morning`. |
| `env` has an empty name | An `env` entry has a blank key. |
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

The cron expression is validated while the task is loaded, not when it is
registered. A task whose schedule cannot be parsed therefore never reaches the
schedule at all, and `status` reports it as `invalid` with the reason instead of
showing it as an idle task that silently never runs.

## Checking a task tree

`scheduler check` runs the same validation the daemon runs, without a daemon:

```bash
scheduler check                          # every task under the tasks folder
scheduler check data/work                # one task, by id
scheduler check tasks/data/work.yaml     # one task, by path
scheduler check --json data/work         # machine-readable result
```

It exits `0` when every checked task is valid and `1` when any is invalid, so it
can gate a deployment. A disabled task is reported as valid with a note that it
is disabled: being switched off is a decision, not a defect.

Because `check` calls the same loader as the daemon, the two cannot disagree
about whether a task is acceptable. A separate validator would drift.

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

The flag is configuration, not runtime state. It answers "should this task run
on its schedule", while a `.lock` answers "is this task running right now".

A disabled task stays visible: `status` reports it as `disabled`, so a task that
is deliberately paused is distinguishable from one that was deleted. A manual
`launch` of a disabled task is refused with the `task_disabled` error code
rather than run, because running it would contradict its own configuration.

Re-enabling the task needs no restart. The next rescan registers it again; see
[Hot reload](#hot-reload).

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

This is the only timeout a task can set. Two other timeouts exist around it and
are scheduler-wide, because they describe how the scheduler watches every run
rather than how long one task may work:

| Timeout | Default | Set by | Scope |
|---|---|---|---|
| `timeout` | `SCHEDULER_DEFAULT_TIMEOUT` (`30m`) | this field | one task |
| `SCHEDULER_POLL_INTERVAL` | `5s` | environment | every task |
| `SCHEDULER_PROVIDER_CALL_TIMEOUT` | `180s` | environment | every provider call |

The poll interval is how often a running task is asked whether it is still alive.
It is not a deadline: a task that runs for an hour is polled many times and none
of those polls ends it. The provider call timeout bounds a single conversation
with the provider, not the run itself, so it must stay above the provider's own
internal budget.

A task cannot set the poll interval. Writing `poll_interval` in a task file is
rejected as an unknown field rather than silently ignored, because a per-task
poll rate would make the scheduler's own timing impossible to reason about.

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

## Hot reload

The daemon rescans the tree every `SCHEDULER_RESCAN_INTERVAL`, which defaults to
`30s`. Each scan reloads every task file and compares the result with the
registered cron entries, so a change takes effect without a restart.

The comparison key is the task id plus a content fingerprint over both the
`.yaml` and the `.md`. Hashing both files means a change to the task content is
detected, not only a change to the configuration.

| Change on disk | Effect |
|---|---|
| `.yaml` added | Parsed and registered with the cron. |
| `.yaml` removed | Removed from the cron. |
| `.yaml` or `.md` content changed | The old cron entry is removed and the task is registered again from the new content. |
| `enabled` set to `false` | Removed from the cron; `status` reports `disabled`. |
| `enabled` set back to `true` | Registered with the cron again. |
| File becomes invalid | Reported as `invalid` and left unscheduled; the rest of the tree is unaffected. |
| File becomes valid again | Registered on the next scan, and the recovery is logged. |

Boundaries worth knowing:

- A change is picked up on the next scan, so it can take up to one rescan
  interval to apply. No command forces a scan.
- A run already in progress is not interrupted. It finishes with the settings it
  started with, and the new configuration applies from the next run.
- Only task files are reloaded. `SCHEDULER_*` variables are read once at startup,
  so changing one requires a restart.
- Missed runs are not replayed. A task whose time passed while the machine was
  off is skipped, matching native cron behaviour.
