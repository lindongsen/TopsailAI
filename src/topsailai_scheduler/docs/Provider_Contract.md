---
maintainer: AI
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: SCHEDULER
programming_language: go
---

# Provider Contract

This document is the standard a provider implements. It is written for the author
of a provider, who works in a separate project and never reads the scheduler's
source code.

## What a provider is

A provider is an independent program that starts, observes and stops one run of a
task. It is not linked into the scheduler and it is not a plugin loaded into the
scheduler's process. The scheduler runs it as a child process and talks to it over
stdin and stdout.

That separation is deliberate. A provider can be written in any language, released
on its own schedule, and replaced without rebuilding the scheduler. The scheduler
knows nothing about sessions, containers, job queues or agent runtimes; it knows
only the three operations below.

The scheduler is a **process supervisor**. It starts a run, observes whether the
run is still alive, and stops it on request. It never decides whether the work
succeeded. Success criteria belong to the task's Markdown content, which the
provider reads.

## The three operations

The scheduler invokes the provider executable with the operation name as the last
argument:

```text
<provider-command> [provider-args...] start
<provider-command> [provider-args...] poll
<provider-command> [provider-args...] stop
```

Every operation reads one JSON document from stdin and, where a reply is defined,
writes exactly one JSON document to stdout.

Each call must exit promptly. A call is a short exchange, not the work itself. A
provider that needs to run work in the background detaches it itself and returns a
handle; the scheduler supervises through `poll` rather than by waiting for `start`
to finish.

The default call timeout is 30 seconds. A provider that does not answer within it
is treated as broken rather than slow.

## start

Reads a request document from stdin:

```json
{
  "protocol_version": 1,
  "task_id": "data/work",
  "task_path": "/srv/tasks/data/work.md",
  "task_dir": "/srv/tasks/data",
  "workspace": "/srv/project",
  "command": "/bin/sh",
  "args": ["--flag"],
  "env": {"MY_VAR": "value"},
  "timeout_ms": 1800000
}
```

| Field | Meaning |
|---|---|
| `protocol_version` | Protocol revision the scheduler speaks |
| `task_id` | Task identity, the YAML path relative to the tasks root without extension |
| `task_path` | Absolute path of the task Markdown content |
| `task_dir` | Absolute folder holding the task files |
| `workspace` | Working directory the run should use |
| `command` | Executable the task asks to run; empty means the provider decides |
| `args` | Extra arguments the task supplies to the provider |
| `env` | Extra environment variables for this run only |
| `timeout_ms` | Run bound in milliseconds, `0` means no timeout |

`command` is empty for the `agent` launcher, which leaves the invocation to the
provider. A provider that wraps one fixed tool ignores it; a provider that runs
whatever it is told, such as `providers/mock`, uses it.

Writes a receipt document to stdout:

```json
{
  "protocol_version": 1,
  "run_id": "sess-abc123",
  "pid": 4242,
  "detail": "started in background"
}
```

| Field | Required | Meaning |
|---|---|---|
| `protocol_version` | no | Revision the provider implements; `0` or `1` is accepted |
| `run_id` | **yes** | Provider-defined run identity, opaque to the scheduler |
| `pid` | no | Process id, for observability only |
| `detail` | no | Free-form text for logs |

`run_id` is the only required field. Without it a later `poll` cannot be answered,
so a receipt with an empty `run_id` is rejected.

A non-zero exit status, a timeout, or a reply that is not exactly one JSON
document is a failed start. The scheduler records the failure and does not
supervise the run.

## poll

Reads a handle document from stdin:

```json
{
  "protocol_version": 1,
  "run_id": "sess-abc123",
  "pid": 4242
}
```

Writes an observation document to stdout:

```json
{
  "state": "running",
  "exit_code": 0,
  "detail": "agent is working"
}
```

`state` is one of exactly three values:

| State | Meaning |
|---|---|
| `running` | The run is still in progress |
| `finished` | The run has ended |
| `unknown` | The provider cannot determine the state |

There is deliberately no `succeeded` state. A provider reports whether the process
is alive, not whether the work was good.

`unknown` is an honest answer, not a failure. A provider that lost its record, or
whose own status call failed, must say `unknown` rather than guess. The scheduler
treats `unknown` as "keep supervising" and logs it; it never reads `unknown` as
finished.

An unrecognised `state` string is an error. Treating an unknown word as `finished`
would end supervision of a run that may still be working, and treating it as
`running` would supervise forever. Refusing to guess is the only safe reading.

`exit_code` is a lifecycle fact, not a verdict. A non-zero code may mean the work
failed, or that the provider's wrapper exited; the scheduler does not decide which.

## stop

Reads the same handle document as `poll`. No output is required.

A provider that has already lost the run may exit `0`: the desired state is
reached, and failing here would make a stop impossible to complete.

## Rules a provider must follow

1. **Write exactly one JSON document to stdout.** A log line printed before the
   JSON makes the reply unreadable. Send diagnostics to stderr.
2. **Exit promptly.** Detach long work yourself and return a handle.
3. **Never report a guess.** Use `unknown` when the state cannot be determined.
4. **Key on `run_id`, not on `pid`.** A pid can be reused by an unrelated process,
   so a pid alone is not a safe identity.
5. **Be idempotent on `stop`.** A second stop of an already-finished run is not an
   error.
6. **Do not decide success.** Report lifecycle only. The task Markdown defines what
   success means and how it is signalled.

## Environment

The scheduler passes the task's `env` map to the provider process, so a provider
reads configuration the same way any CLI does. The scheduler adds no variable of
its own, so there is no reserved name a task could collide with.

The task Markdown path is not passed through the environment. It arrives in the
`start` request as `task_path`, which is the only place a provider should read it
from: a request field cannot be shadowed by an inherited variable.

## Registering a provider

A provider is selected per task through the task YAML:

```yaml
schedule: "0 8 * * *"
provider: /srv/providers/my-provider/bin/my-provider
```

`provider` is the executable path, not a name. It may point anywhere on disk, so
a provider does not have to live under a particular folder. When `provider` is
omitted the task uses `SCHEDULER_DEFAULT_PROVIDER_PATH`, which the scheduler
requires at startup.

A relative path is resolved against the scheduler working directory. The
resolved absolute path is the provider's identity: the scheduler reports it,
records it in the lock file and compares it during restart reconciliation.

The scheduler checks the provider executable when it scans the task tree, not
when the task first fires. A task naming a missing provider is reported as
`invalid` with the reason and is not scheduled, so a misconfiguration is visible
immediately instead of failing silently on every trigger. The task stays in the
status output, so a manual launch still reports the real reason rather than
claiming the task does not exist. A task that is disabled is not checked,
because it is never scheduled.

`command` is not how a provider is selected. It belongs to the `command`
launcher, which asks the provider to run that specific executable; a provider
that wraps one fixed tool ignores it.

## Implementation status

| Part | Status |
|---|---|
| Protocol definition | Defined here |
| `provider` package and CLI adapter | Implemented, tested |
| `provider` key in task YAML | Parsed and validated as an executable path |
| Provider resolution from an executable path | Implemented, tested |
| Supervisor holding the lock across a run | Implemented, tested |
| Daemon selecting a provider from the task | Wired |
| Poll interval configuration | Implemented |
| Restart reconciliation of in-flight runs | Implemented, tested |

The daemon selects a provider per task and supervises through `poll`, holding the
task lock for the whole round. The integration suite exercises that path through
`providers/mock`.

A scheduler restart does not forget runs that were in flight. The lock file
carries a run record, and a new round reads it before starting anything: a run
still in progress is left alone, a run confirmed finished is cleared, and an
unreadable state is treated as running rather than guessed. A stop for a run left
by a previous scheduler is forwarded to the provider on a best-effort basis,
because that run is not supervised and the stop cannot be confirmed.

## Reference implementation

`scheduler-provider-topsailai` is one provider, not the framework. It is registered like any other and
carries no privilege. Its own project owns its implementation; this document
defines only what any provider must satisfy.
