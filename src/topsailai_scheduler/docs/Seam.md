---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_scheduler
ProjectFolder: /TopsailAI/src/topsailai_scheduler
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler
ProjectCode: scheduler
programming_language: go
---

# Seam: the standard contracts

This document describes the three seams that make the scheduler reusable:

- the **control contract** — how any client drives the scheduler;
- the **launcher seam** — how a task becomes a provider request;
- the **provider seam** — how a request becomes a supervised run, which is where
  an agent such as TopsailAI is started.

All three are stable interfaces. A new transport, a new way to describe work, or
a new runtime is added by implementing one interface or one executable, never by
editing the scheduling loop.

The boundary that shapes every seam: the scheduler is a **process supervisor**.
It confirms that a run started and observes when it stops. It does not judge
whether the task succeeded — that is defined by the task's `.md`. Keeping this
boundary narrow is what lets the scheduler stay small and lets a task define its
own success.

## The control contract

`runtime.Controller` is the whole contract. Three operations, no more:

| Operation | Request | Result | Purpose |
|---|---|---|---|
| `Launch` | `LaunchRequest{TaskID, Wait}` | `LaunchResult` | Start one run of a task now |
| `Status` | none | `Snapshot` | Report every task and run |
| `Stop` | `StopRequest{TaskID, Force}` | `StopResult` | Actively stop a running task |

The daemon is the only implementation. A transport decodes a request, calls one
of these methods, and encodes the reply. Because the logic lives in one place,
every transport behaves identically.

### Sentinel errors and stable wire codes

Errors are sentinel values, so a client branches on identity rather than on
message text. Each maps to one stable string code on the wire:

| Sentinel error | Wire code | Meaning |
|---|---|---|
| `ErrTaskNotFound` | `task_not_found` | No task with that id is known |
| `ErrTaskNotRunning` | `task_not_running` | The task has no in-flight run to stop |
| `ErrTaskDisabled` | `task_disabled` | The task exists but is disabled in its YAML |
| `ErrShuttingDown` | `shutting_down` | The scheduler is stopping, no new run accepted |
| — (decode failure) | `invalid_request` | The request could not be decoded |
| any other error | `internal` | The daemon failed for another reason |

The mapping lives in `control.CodeForError`, next to the codes, so no transport
can invent a different code for the same condition.

### Task states

`Status` reports one of four states per task:

| State | Meaning |
|---|---|
| `idle` | Scheduled, no in-flight run |
| `running` | Has an in-flight run |
| `disabled` | Present but `enabled: false` in its YAML |
| `invalid` | Files exist but cannot be loaded; `error` explains why |

An `invalid` task is reported rather than hidden, so a broken file is visible
through `Status` and not only in the log. Its id is derived by the same
`task.IDFor` helper a valid task uses, so a broken file keeps the identity it
will have once fixed.

## The socket transport

The built-in transport is a Unix socket. The wire format is **one JSON object
per line in each direction**:

- one connection carries exactly one request and one reply, then closes;
- the server reads one line, dispatches it, writes one reply line, and closes;
- a request line is bounded by `maxRequestBytes`, so a malformed client cannot
  exhaust memory;
- the server sets a 30 second deadline per connection, so a stalled client
  cannot hold a handler forever.

Request:

```json
{"op": "launch", "task_id": "data/work", "wait": true}
```

Reply:

```json
{"ok": true, "data": {"task_id": "data/work", "pid": 4242, "trace_id": "data-work-1-4242", "skipped": false, "record": null}}
```

Failure:

```json
{"ok": false, "code": "task_not_found", "error": "task not found: data/nope"}
```

`data` is omitted on failure, so a client decodes it only after checking `ok`.
A line is used rather than a length prefix because it is readable with ordinary
tools and needs no framing code on either side.

The socket path comes from `SCHEDULER_CONTROL_SOCKET`, defaulting to
`scheduler.sock` in the working directory. A relative path is resolved against
the working directory, so each project folder gets its own daemon instead of
sharing one global socket.

## The launcher seam

`launcher.Launcher` turns a task into a provider request:

```go
type Launcher interface {
    Name() string
    Build(item task.Task, defaults Defaults) (provider.Request, error)
}
```

The daemon never knows how a task is executed. It asks the registry for the
launcher named by the task and receives a `provider.Request`, which it hands to
the provider. Adding a new way to describe work means registering one
implementation:

```go
registry := launcher.DefaultRegistry()
if err := registry.Register("my-launcher", func() launcher.Launcher { return MyLauncher{} }); err != nil {
    // handle
}
```

Registering a name twice is an error, not a silent replacement: two
implementations of one name would make the effective behaviour depend on
initialisation order.

`Defaults` is a plain struct, not the config type, so this package does not
depend on configuration loading and a test can supply its own values. It holds
only `Workspace` and `Timeout` — the two defaults the scheduler itself owns.
Everything specific to an agent belongs to the provider.

### The two built-in launchers

| Launcher | Builds | Used when |
|---|---|---|
| `agent` | Task identity, content path, workspace, timeout, task `env`; leaves `Command` empty | The task names no launcher, or names `agent` |
| `command` | The same, plus `Command` and expanded `Args` | The task names `command` and supplies `command:` |

`agent` is the default. It deliberately does not know the agent's command line:
that belongs to the provider, which is an independent project. A task that wants
a specific executable without changing provider uses `command`.

### Placeholders

The `command` launcher expands these placeholders in each argument:

| Placeholder | Replaced by |
|---|---|
| `{task}` | Absolute path of the task Markdown file |
| `{task_id}` | Task id, for example `data/work` |
| `{task_dir}` | Absolute folder holding the task files |
| `{stem}` | Shared filename stem, for example `work` |
| `{workspace}` | Resolved workspace |

Expansion is a plain string replacement, not a shell evaluation. Each argument
is passed to the child as one argv entry, so a path containing spaces stays a
single argument and needs no quoting.

## The provider seam

A provider is an independent program that starts, observes and stops one run of
a task. It is not linked into the scheduler and not loaded as a plugin: the
scheduler runs it as a child process and talks to it over stdin and stdout.

That separation is what lets a provider be written in any language, released on
its own schedule, and replaced without rebuilding the scheduler. The scheduler
knows nothing about sessions, containers or agent runtimes; it knows only three
operations.

`docs/Provider_Contract.md` is the standard a provider author implements. This
section describes only how the scheduler uses it.

### Provider discovery

A provider is found by the executable path the task gives, or by the default
path the scheduler was started with:

```text
provider: /srv/providers/mock/bin/mock     # in the task
SCHEDULER_DEFAULT_PROVIDER_PATH=...        # at startup, required by "run"
```

There is no folder layout to follow. A provider may live anywhere on disk, which
matters because a provider is a foreign project: the scheduler must not require
it to be a Go binary, to sit under a particular directory, or to be registered
anywhere. A compiled binary, a shell script and a Python script are equally
valid, and the scheduler never needs to know which it is.

A relative path is resolved against the scheduler working directory, the same
rule as `SCHEDULER_TASKS_ROOT` and the control socket. The resolved absolute path
is the provider's identity: it is what the startup log reports, what the lock
file records and what restart reconciliation compares. A provider that moved is
therefore reported as a mismatch instead of being silently replaced by whatever
now sits at the old path.

The default path is required, not defaulted. A scheduler with no provider cannot
run anything, and guessing a location would turn a missing configuration into a
confusing failure at the first due task instead of a clear refusal to start. The
check runs in `scheduler run` only: `status`, `launch` and `stop` are clients
talking to a daemon that already validated its own configuration, so they never
need a provider path.

### The three operations

The scheduler invokes the provider executable with the operation name as the
last argument:

```text
<provider-command> [provider-args...] start
<provider-command> [provider-args...] poll
<provider-command> [provider-args...] stop
```

Each call is a short exchange: one JSON document on stdin, at most one JSON
document on stdout, diagnostics on stderr. A call is bounded by
`SCHEDULER_PROVIDER_CALL_TIMEOUT`, defaulting to 30 seconds; a provider that does
not answer within it is treated as broken rather than slow.

`start` returns a handle whose `run_id` is the only required field. The scheduler
stores that handle and hands it back unchanged to `poll` and `stop`, so a
provider may key on a session id, a job id, a container name or a pid without the
scheduler knowing which.

### Run states

`poll` reports exactly one of three states:

| State | Meaning for the scheduler |
|---|---|
| `running` | Keep supervising |
| `finished` | Supervision ends |
| `unknown` | Keep supervising and log it; never read as finished |

There is deliberately no `succeeded` state. A provider reports whether the
process is alive, not whether the work was good.

`unknown` is an honest answer, not a failure. A provider that lost its record, or
whose own status call failed, must say `unknown` rather than guess. The scheduler
keeps supervising and lets the round's timeout bound it, because ending
supervision on `unknown` would abandon a run that may still be working.

An unrecognised state string is an error. Treating an unknown word as `finished`
would end supervision of a live run, and treating it as `running` would supervise
forever; refusing to guess is the only safe reading.

### The boundary: supervisor, not judge

The scheduler's responsibility ends at two questions:

1. Did the run start?
2. Is the run still alive?

It does **not** decide whether the task succeeded. Success criteria belong to the
task's `.md`, which tells the provider's agent what counts as done and what
signal or marker proves it. A scheduler that also judged success would hold a
second, conflicting authority over the same question.

This is why a run record has no `succeeded` field, and why an exit code is
recorded as a lifecycle fact rather than a verdict. A non-zero code may mean the
work failed, or that a provider's wrapper exited; the scheduler does not decide
which.

### The lock spans the whole supervision

`{stem}.lock` is acquired before `start` and released only when supervision ends,
not when `start` returns.

This is the point where a background run changes the design. A provider returns a
handle promptly and does the work in the background, so a lock bound to the
`start` call would be free while the run was still working, and the next tick
would start a second copy of the same task. Holding the lock until the run
reports `finished` makes the lock mean "this task has a round under supervision",
which is the only meaning that prevents overlap.

The consequences are deliberate:

- A run is in flight from lock acquisition until `poll` reports `finished`.
- The lock is a kernel lock on an open descriptor, so a crashed scheduler
  releases it automatically.
- A scheduler restart must reconcile recorded runs before scheduling, or it would
  forget a run it still holds and start a duplicate.

The lock is a separate file, never the `.md`. A lock is bound to an open file
descriptor, not to a path: locking the `.md` would let an edit or replacement of
that file move the lock, and two runs of one task could proceed at once.

### The lock record: a breadcrumb, not the mutex

The flock answers "is a scheduler supervising this task right now". It cannot
answer "which run was in flight when the last scheduler died", because a run is a
separate process that outlives the scheduler. After a restart the lock is free
while the run may still be working.

So the lock file also carries a record, written by the supervisor while it
supervises:

```json
{
  "run_id": "session-abc",
  "provider": "scheduler-provider-topsailai",
  "pid": 12345,
  "started_at": "2026-11-20T21:44:16Z",
  "scheduler_pid": 12000
}
```

`run_id` and `provider` are what a later check needs: the provider name selects
who to ask, and the run id is what to ask about. `pid` is observability only — a
pid can be reused, so it must never be the sole key. `scheduler_pid` identifies
the supervisor that died, which is what makes a stale record recognisable.

The record is **advisory**. The flock remains the authority for "a scheduler owns
this task". A missing, empty or unreadable record means *unknown*, never "nothing
was running": a supervisor that died before writing it leaves no trace.

Two implementation constraints follow from the flock:

- The record is written through its own descriptor, because the flock handle is
  opened read-only.
- The record is rewritten **in place**, never through a temporary file and a
  rename. A rename gives the path a new inode while the flock stays bound to the
  old one, so the next process would lock the new file successfully and mutual
  exclusion would be silently gone.

### Restart reconciliation

Before a round starts anything, it reads the record and asks the provider about
the run it names. Three outcomes:

| Record | Provider answer | Outcome |
|---|---|---|
| none | — | nothing to reconcile, the round proceeds |
| names a run | `finished` | the record is stale, it is cleared, the round proceeds |
| names a run | `running` or `unknown` | the round is skipped, the record is kept |

`unknown` is treated as busy on purpose. A provider that cannot answer is not
evidence that the run ended. Waiting one more tick costs a delayed run; guessing
wrong costs duplicated work.

A failed `poll` is also treated as busy, and the record is left for the next
attempt. A record naming a provider this task no longer uses is an **error**, not
a skip: asking a different provider about the run would be meaningless.

The record is cleared only when the run is confirmed `finished`. A timeout or a
`Stop` does not clear it, because those ask the run to end without proving that it
did.

### Stopping a run from a previous supervisor

After a restart the run table is empty, so `Stop` cannot find the run there. It
falls back to the lock record: it takes the lock, reads the record, asks the
provider, and forwards a `stop`.

This path is **best effort**, and the contract says so. The scheduler holds no
context to cancel and no supervision loop to observe the outcome, so it can only
forward the request. `StopResult.best_effort` is `true` for such a stop, and a
caller must not read it as "the run is stopped".

The lock is the safety check: the fallback only runs when the lock is **free**,
which proves no live supervisor owns the task. Taking the lock also keeps a new
round from starting while the stop is being forwarded. If the lock is held, the
run table was merely stale in this process, and the owning supervisor's own stop
path is authoritative.

The provider is asked before the stop is sent, so a run that ended on its own
after the supervisor died is reported as not running instead of receiving a
pointless stop. A failed `poll` does not abort the stop: the record is the only
evidence of the run, and refusing to act would leave it unmanageable.

### Run lifecycle

1. Acquire `{stem}.lock` non-blocking. If it is held, the round is skipped and
   logged — not queued, because the next tick will try again.
2. Reconcile the lock record. If it names a run that is still `running` or
   `unknown`, the round is skipped and the lock is released.
3. Take a concurrency slot, bounded by `SCHEDULER_MAX_CONCURRENT`.
4. Call `start` and read the handle, then write the record naming that run.
5. Poll every `SCHEDULER_POLL_INTERVAL`, defaulting to 5 seconds, until the state
   is `finished`, the round's timeout expires, or `Stop` is called.
6. On timeout or `Stop`, call `stop` so the provider can end the run and its
   children rather than leaving them behind.
7. Clear the record only when the run is confirmed `finished`, then release the
   lock and record the supervision outcome.

Step 7 is ordered that way on purpose. Clearing before the run is confirmed would
erase the only evidence of a run that may still be working, and releasing the lock
before clearing would let the next tick read a record for a run that just ended.

### Environment variables from the task

A task's YAML may set `env`, a map of variables injected into the run's
environment for that round only:

```yaml
env:
  TOPSAILAI_INTERACTIVE_MODE: "0"
  PROJECT_STAGE: staging
```

The launcher copies that map into the provider request, and the provider applies
it to the run. The scheduler adds no variable of its own, so there is no reserved
name a task could collide with.

This is the supported way to give a task its own environment. It needs no
scheduler-wide setting and no code change.

### Adding a different provider

To run tasks through another runtime, add a provider project and point at it:

1. Create an executable implementing the three operations in
   `docs/Provider_Contract.md`. It may live anywhere on disk.
2. Set `provider: <path>` in a task's YAML, or start the scheduler with
   `SCHEDULER_DEFAULT_PROVIDER_PATH=<path>` to make it the default.

No scheduler code change and no rebuild. The `launcher` seam is needed only when
the *request* must be built differently, not when the runtime changes.

## What a client must not do

- Do not import the daemon to call the contract in-process. The CLI talks to the
  running daemon through the socket, so one contract serves every client.
- Do not match on error message text. Use the sentinel error or the wire code.
- Do not assume a launch started a run. Check `skipped` and `record`: a task
  already running is skipped, and a run that failed to start reports a record
  instead of a pid.
- Do not treat `Stop` as a guarantee of termination. It asks the provider to end
  the run; the run is confirmed finished when `Status` reports `idle`.
- Do not read `best_effort: true` as "the run is stopped". It means the stop was
  forwarded for a run this scheduler is not supervising, so nothing here can
  confirm the outcome. Check `Status` or the provider.
- Do not read an exit code as a task result. It is a lifecycle fact. Whether the
  work succeeded is answered by the task's `.md`.
- Do not treat a confirmed start as a finished run. `start` proves the run began;
  the run is over when `poll` reports `finished`.
- Do not treat the lock record as the mutex. The flock decides whether a scheduler
  owns the task; the record only names the run to go and check.

## Verification status

The control contract, the socket transport and the `command` launcher are covered
by unit tests and by the integration suite, which drives the real binary over the
real socket.

The `provider` package and its CLI adapter are unit tested against fake providers
written as shell scripts, so the tests exercise the process boundary rather than
an in-process stub. The `supervisor` package is unit tested, including the
guarantee that the lock is still held while a run is in flight.

The daemon is wired to the supervisor and selects a provider per task. The
integration suite runs real tasks through `providers/mock`, so the whole path
from task file to supervised run is exercised end to end.

Restart reconciliation is covered at two levels. The `supervisor` package is unit
tested for the three record outcomes, and the live suite kills a real daemon with
`SIGKILL` while a run is in flight, restarts it, and asserts the next tick is
skipped and no second `start` reaches the provider. `SIGKILL` is required: a
graceful shutdown clears the record, which is exactly the state reconciliation
exists to handle.

The best-effort stop is unit tested for the six cases that matter: a live record,
a record for a finished run, an empty record, a lock held by a live supervisor, a
record naming an unresolvable provider, and a failed `poll`. Each test asserts
whether a `stop` reached the provider, not only the returned error, because the
error alone cannot show that a request was or was not sent.

The `scheduler-provider-topsailai` provider is tested against a stub executable that records the
arguments and environment it receives. That proves what is sent, not how a real
agent responds: **no agent has been launched** while writing this document. The
upstream command lines and receipt fields were read from the TopsailAI CLI
source, not observed from a live run. Before relying on that provider, run one
task manually and watch it through `topsailai session status`.

### Known gaps between this contract and the current code

| Gap | Current behaviour | Required behaviour |
|---|---|---|
| Real agent path | The `scheduler-provider-topsailai` provider is asserted against a stub | One manual run against a real agent |

This is a verification gap in a provider that is maintained as its own project. It
does not affect the scheduler's own behaviour.

### Limits of restart reconciliation

Reconciliation is a best-effort recovery, not a guarantee, and the limits are
worth stating plainly:

- A supervisor that dies **before** writing the record leaves nothing to
  reconcile. The run may still be working and the next tick will start a second
  copy. The window is small — the record is written immediately after `start`
  returns — but it exists.
- A provider that answers `unknown` forever keeps the task blocked. That is the
  intended trade: a blocked task is visible, a duplicated run is not.
- The record is advisory, so a corrupted or truncated record reads as *no record*
  and the round proceeds. A torn write is as uninformative as a missing one.
- A run left behind by a dead supervisor can only be stopped through the
  best-effort path, and only if the provider still recognises the run id. If the
  provider has forgotten it, the run must be ended by the provider itself.
