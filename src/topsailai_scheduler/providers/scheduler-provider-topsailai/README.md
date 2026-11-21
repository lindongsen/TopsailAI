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

- `start` launches an agent in the task's workspace and returns its session id.
- `poll` asks whether that session is still processing.
- `stop` interrupts that session.

It does **not** decide whether the work succeeded. The task's Markdown content
says what counts as success and what signal marks it; the provider only reports
whether the agent is still working.

## Layout

```text
scheduler-provider-topsailai/
├── bin/scheduler-provider-topsailai  the executable the scheduler runs
├── docs/Live_Test.md                 how to exercise it against a real agent
├── tests/test_topsailai.py
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
{"state": "running", "exit_code": 0, "detail": "session 20261120120000 processing"}
```

`state` is one of `running`, `finished` or `unknown`. There is deliberately no
`succeeded`.

### stop

Request:

```json
{"protocol_version": 1, "run_id": "69972c64f0664d3487b00753643dd86d"}
```

No output is required.

## The upstream command lines

### Launch

```text
topsailai workspace agent -m raw --non-interactive --json <workspace>
```

Three parts of this are load-bearing:

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

### Task content

The task content path is passed through `TOPSAILAI_TASK`, not through `--task`.

Upstream `--task` writes the content to a temporary file and sets
`TOPSAILAI_TASK` to that path, which would collide with the path this provider
supplies. Passing the path directly also avoids creating and cleaning up a
temporary file, and a path with spaces needs no quoting because it travels
through the environment.

### Status

```text
topsailai session status <session_id> --json
```

The reported `state` is derived from the session's file lock: `processing` while
the lock is held, `idle` once it is released. That lock is the authority, and it
is released when the agent process ends, including when it crashes.

### Interrupt

```text
topsailai runtime control hard_interrupt -s <session_id> -p <pid> --json
```

A session that has already ended cannot be interrupted. That is not a failure:
the desired state is reached.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `TOPSAILAI_PROVIDER_BINARY` | `topsailai` | Executable to drive. |
| `TOPSAILAI_PROVIDER_STATE_DIR` | `~/.cache/topsailai-provider` | Where run records are kept. |

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

## Known limitation

The provider has now been exercised against a real agent, and the launch does not
work. `start` builds a foreground command, so it blocks until `LAUNCH_TIMEOUT`
expires and then reports `topsailai did not answer within 120s`. The agent itself
finishes in about 15 seconds and then waits for input that never arrives.

Adding `--background` makes the same launch return a usable receipt immediately.
See `docs/Live_Test.md` for the full procedure and the observed output, and
`issues/issue-provider-launch-blocks-in-foreground.md` in the scheduler project
for the defect record.

A second limitation affects any live test: the launched agent ignores the
workspace the task asks for, because the `topsailai` wrapper changes directory
and the configured `workspace` wins over the argument. Until that is fixed, a
live test must rely on a tool allow-list such as
`TOPSAILAI_ENABLED_TOOLS=time_tool` rather than on workspace isolation.
