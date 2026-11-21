---
maintainer: AI
workspace: /TopsailAI/src/topsailai_scheduler/providers/mock
ProjectFolder: /TopsailAI/src/topsailai_scheduler/providers/mock
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler/providers/mock
ProjectCode: MOCK
programming_language: python
---

# Mock provider

A provider for the scheduler that runs the command a task names and reports
whether that process is still alive. It exists so the scheduler and its
integration tests can run real tasks without a real agent.

This is an independent project. It does not import scheduler code and the
scheduler does not import it. The only thing shared is the protocol.

## What it is for

- Running the scheduler's integration tests without an agent binary.
- Trying the scheduler out before a real provider exists.
- Being a worked example of the protocol for anyone writing a new provider.

## What it is not

- It is not a task runner with retries, queues or scheduling. The scheduler
  owns scheduling.
- It does not judge success. It reports whether the process is alive and, once
  it has ended, the exit status it produced. Whether that status means the work
  was good is the task's Markdown content's business.

## Layout

```text
mock/
├── bin/mock          the executable the scheduler runs
├── tests/test_mock.py
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
  "command": "/bin/sh",
  "args": ["-c", "make check"],
  "env": {"EXTRA": "value"},
  "timeout_ms": 1800000
}
```

Reply:

```json
{
  "protocol_version": 1,
  "run_id": "69972c64f0664d3487b00753643dd86d",
  "pid": 1044355,
  "detail": "started /bin/sh"
}
```

`run_id` is required. Without it a later `poll` cannot be answered.

When `command` is empty the provider decides. A mock has no agent to run, so it
simulates a run that completes immediately.

### poll

Request:

```json
{"protocol_version": 1, "run_id": "69972c64f0664d3487b00753643dd86d"}
```

Reply:

```json
{"state": "running", "exit_code": 0, "detail": "pid 1044355 alive"}
```

`state` is one of `running`, `finished` or `unknown`. There is deliberately no
`succeeded`: the provider reports whether the process is alive, not whether the
work was good.

`unknown` is an honest answer, not a failure. This provider returns it when it
has no record of the run, for example after its state folder was cleared.

### stop

Request:

```json
{"protocol_version": 1, "run_id": "69972c64f0664d3487b00753643dd86d"}
```

No output is required. Stopping a run the provider has lost succeeds, because
the desired state is already reached and failing would make a stop impossible to
complete.

## How a run is executed

`start` writes a small shell script and launches it with `start_new_session`, so
the run gets its own process group. That matters twice: the run survives this
provider exiting, and `stop` can signal the whole group so a task's own children
end with it.

The script records the exit status to a file. `poll` reads that file when it
exists, and otherwise checks whether the pid is alive.

## State folder

Run records live in `MOCK_PROVIDER_STATE_DIR`, defaulting to
`~/.cache/mock-provider`. Each run gets a `<run_id>.json` record, a
`<run_id>.sh` script and a `<run_id>.exit` status file.

The scheduler does not manage this folder. Clearing it is safe: runs already
started keep running, and `poll` then reports `unknown`.

## Running the tests

```bash
python3 tests/test_mock.py
```

The tests use a temporary state folder per test and clean up any process they
started.
