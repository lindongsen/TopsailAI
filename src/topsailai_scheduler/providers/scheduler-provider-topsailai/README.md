---
maintainer: AI
workspace: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai
ProjectFolder: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# TopsailAI provider

A provider for the scheduler that launches a TopsailAI agent for a task and
reports whether that agent is still working.

This is an independent project. It does not import scheduler code and the
scheduler does not import it. The only thing shared is the protocol.

## What it does

- `start` submits an agent launch in the task's workspace and returns its session
  id.
- `poll` asks whether that agent is still working.
- `stop` interrupts that agent.

It does **not** decide whether the work succeeded. The task's Markdown content
says what counts as success and what signal marks it; the provider only reports
whether the agent is still working.

## Layout

```text
scheduler-provider-topsailai/
├── bin/scheduler-provider-topsailai  the executable the scheduler runs
├── docs/Live_Test.md                 how to exercise it against a real agent
├── tests/test_topsailai.py           unit tests, with topsailai stubbed
├── tests/live/run.sh                 the live test driver
└── README.md
```

The scheduler addresses a provider by its executable path, so this file can be
named and placed however you like; the path is what a task or
`SCHEDULER_DEFAULT_PROVIDER_PATH` must give.

## Protocol

Three operations, each a short exchange. One JSON document on stdin, one JSON
document on stdout, diagnostics on stderr.

### start

Request:

```json
{
  "protocol_version": 1,
  "task_id": "data/work",
  "task_path": "/tasks/data/work.md",
  "task_dir": "/tasks/data",
  "workspace": "/srv/project",
  "command": "",
  "args": [],
  "env": {"EXTRA": "value"},
  "timeout_ms": 1800000
}
```

Reply:

```json
{
  "protocol_version": 1,
  "run_id": "69972c64f0664d3487b00753643dd86d",
  "pid": 4242,
  "detail": "session 20261120120000"
}
```

`run_id` is required. The session id is kept in the provider's own state folder
and is not exposed to the scheduler, which treats the handle as opaque.

### poll

Request:

```json
{"protocol_version": 1, "run_id": "69972c64f0664d3487b00753643dd86d"}
```

Reply:

```json
{"state": "running", "exit_code": 0, "detail": "session 20261120120000 answered a heartbeat"}
```

`state` is one of `running`, `finished` or `unknown`. There is deliberately no
`succeeded`.

`unknown` is a real answer, not a failure: it means no heartbeat answered, no
terminal status was recorded, and no live process could be found. That is the
normal state during the short window between submission and the agent writing
its first artifact, so reporting `finished` there would end supervision of a run
that is still starting. The scheduler already treats `unknown` as busy.

### stop

Request:

```json
{"protocol_version": 1, "run_id": "69972c64f0664d3487b00753643dd86d"}
```

No output is required.

## The upstream command lines

### Launch

```text
topsailai workspace agent -m raw --non-interactive --background --driver topsailai_agent_chat --json <workspace>
```

Every part of this is load-bearing:

- **`-m raw` is required.** The `dtach` and `tmux` modes wrap the launch in a
  detaching wrapper, so the exit status observed would be the wrapper's rather
  than the agent's.
- **`--json` is required.** It makes the launcher print one receipt on stdout
  and send everything else to stderr, which is what makes the receipt parseable.
- **`--non-interactive` is not enough on its own.** It only stops the launcher
  prompting. The agent's own interactive mode is controlled by
  `TOPSAILAI_INTERACTIVE_MODE`, which defaults to interactive, so this provider
  sets it to `0` explicitly. Without that, a run can wait for input that never
  comes and end by being killed at the timeout rather than by finishing.
- **`--driver` is required.** The turn count is fixed inside each driver script
  and is not reachable from here: `topsailai_agent_chat` calls `run(times=1)` and
  exits after one turn, while the default `topsailai_agent_chats` calls `run()`
  and waits for a next turn forever. It is passed as a flag rather than through
  `TOPSAILAI_AGENT_DRIVER` because the operating-system environment ranks last in
  driver resolution, so any `settings.yaml` naming `ai_agent_driver` would
  override it.
- **`--background` is required.** A foreground launch does not return until the
  agent exits, so a task longer than the scheduler's call timeout would be
  reported as a provider failure while the agent was working correctly. The cost
  is that the receipt reports a submission rather than a confirmed start, which
  is why `poll` never treats a missing signal as proof that the run ended.

### Task content

The task content path is passed through `TOPSAILAI_TASK`, not through `--task`.

Upstream `--task` writes the content to a temporary file and sets
`TOPSAILAI_TASK` to that path, which would collide with the path this provider
supplies. Passing the path directly also avoids creating and cleaning up a
temporary file, and a path with spaces needs no quoting because it travels
through the environment.

### Liveness

`poll` consults three signals in order of strength, and never calls
`session status`:

1. **The control-channel heartbeat.** The agent binds
   `{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.sock` and answers
   a `heartbeat` action. A reply is produced by the process that owns the
   channel, so it proves the agent is alive right now.
2. **The session metadata.** `{session_id}.{pid}.session.meta` records
   `running`, `completed`, `error` or `interrupted`. A terminal status is written
   by the agent itself on exit, so it survives the socket being removed.
3. **The process table.** The last resort, and it only proves that some process
   with that pid exists.

`session status` is deliberately not used. It reports `idle` for a session that
never existed, and it reports `idle` for a background launch that has been
submitted but has not yet taken its lock, so it cannot tell "not started yet"
from "finished".

The socket is **absent**, not refused, at both ends of a run: it is created after
the process starts and removed before it exits. Absence therefore proves nothing
and must be resolved by the metadata or the process table. Only a refused
connection proves the listener is gone.

### Interrupt

```text
topsailai runtime control hard_interrupt -s <session_id> -p <pid> --json
```

The pid must be the **agent's**, not the launcher's. The launch receipt reports
the launcher's pid, and the launcher exits as soon as the run is submitted, so
that pid addresses a socket that never existed. The agent writes its own pid into
the session metadata and into the socket filename; either is authoritative.

A session that has already ended cannot be interrupted. That is not a failure:
the desired state is reached.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `TOPSAILAI_PROVIDER_BINARY` | `topsailai` | Executable to drive. |
| `TOPSAILAI_PROVIDER_STATE_DIR` | `{TOPSAILAI_HOME}/scheduler-provider` | Where run records are kept. |
| `TOPSAILAI_PROVIDER_DRIVER` | `topsailai_agent_chat` | Agent driver to launch. |
| `TOPSAILAI_HOME` | `~/.topsailai` | Where session artifacts are looked for. |

`TOPSAILAI_PROVIDER_DRIVER` exists for a provider that needs a different turn
model. The default is the single-turn driver, and changing it to an unlimited
driver would make `poll` supervise an agent that never ends on its own.

`TOPSAILAI_HOME` is read with the same resolution the CLI uses: the environment
variable first, then `~/.topsailai`, then `/topsailai`. It must agree with the
value the agent saw, or `poll` will look for session artifacts in the wrong
folder and answer `unknown` forever.

`TOPSAILAI_PROVIDER_STATE_DIR` defaults to a folder named after the project under
`TOPSAILAI_HOME`, so run records sit beside the other runtime state the agent
keeps there instead of in a separate cache tree. The project name is the prefix,
which lets several providers share one home without colliding. The default is
resolved on every call, not at import time, so a `TOPSAILAI_HOME` set after the
provider starts is still honoured.

The scheduler does not manage the state folder. Clearing it is safe: agents
already launched keep running, and `poll` then reports `unknown`.

## Precedence of environment variables

The task's own `env` is applied first, then this provider's requirements. A task
therefore cannot switch the agent back to interactive mode or redirect the task
content, because either would break supervision.

## Running the tests

```bash
python3 tests/test_topsailai.py
```

The tests use a stub executable in place of `topsailai`, so **no agent is
launched**. The stub records the arguments and environment it receives, which is
what lets the tests assert the exact command line without starting anything.

The live test is separate and does launch a real agent:

```bash
bash tests/live/run.sh
```

It needs a built scheduler binary (`make build`), a working model configuration
under `TOPSAILAI_HOME`, and tmux. It refuses to run against a stale binary.

## Verified against a real agent

`docs/Live_Test.md` describes the live test: a real daemon, this provider, and a
real agent against a real model. It passes, and the run is inert because the
task's only enabled tool is `time_tool`.

Two defects were found and fixed by that test, and both are worth knowing
because they were invisible to the stubbed unit tests:

- **The launch never returned.** The default driver runs unlimited turns, so the
  agent finished its work and then waited for a next turn that never came. The
  turn count lives inside the driver script and cannot be reached from here, so
  the provider now selects the single-turn driver with `--driver`.
- **The launch blocked for the whole run.** A foreground launch does not return
  until the agent exits, so a task longer than the scheduler's call timeout would
  be reported as a provider failure while the agent was working correctly. The
  provider now submits with `--background` and supervises through `poll`.

A third defect was in the scheduler, not here: it never set the provider's
working directory, so the agent ran wherever the scheduler happened to be. The
scheduler now runs the provider in the task's workspace, and the live test
confirms the agent's `project_workspace` and `pwd` both equal the requested
folder.
