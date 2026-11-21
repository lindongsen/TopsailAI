---
maintainer: AI
workspace: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai
ProjectFolder: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai
ProjectRootFolder: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# Live test

`tests/test_topsailai.py` replaces `topsailai` with a stub, so it proves what
this provider sends but never how a real agent answers. This document describes
the complementary test: a real daemon, the real provider, and a real agent
against a real model.

The test is deliberately inert. The task's only enabled tool is `time_tool`, so
the agent can read the clock and do nothing else: no file writes, no shell, no
network. That is what makes it safe to run unattended.

## What the test proves

- The daemon discovers a task in a temporary task tree.
- The provider submits an agent launch and records a session id.
- The agent runs in the workspace the task names, not wherever the scheduler
  happened to be.
- `poll` reports `running` while the agent answers a heartbeat, and `finished`
  once the agent records a terminal status.
- The tool set offered to the agent is exactly `time_tool`.

## Isolation

The driver is tracked at `tests/live/run.sh`, so the test is reproducible from a
clean checkout. Everything the test owns lives under `.tmp/live-topsailai/`, and
the real `tasks/` tree is never touched, so a stray run cannot fire a production
task.

```text
.tmp/live-topsailai/
├── tasks/probe/time.yaml     the task under test, written by the driver
├── tasks/probe/time.md       its content, written by the driver
├── agent-workspace/          the folder the agent runs in
├── provider-state/           the provider's run records
├── daemon.log                daemon stdout and stderr
├── daemon.exit               the daemon's exit code
├── launch.json               the launch result
└── status.json               the status snapshot
```

The agent's own session artifacts are the one thing outside that folder. They are
written under `TOPSAILAI_HOME` because the agent needs the real configuration
there to reach a model. The test reads them and never creates them.

## The task pair

`tasks/probe/time.yaml`:

```yaml
schedule: "0 3 * * *"
launcher: agent
provider: /TopsailAI/src/topsailai_scheduler/providers/scheduler-provider-topsailai/bin/scheduler-provider-topsailai
workspace: /TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace
timeout: 5m
env:
  TOPSAILAI_ENABLED_TOOLS: "time_tool"
```

`tasks/probe/time.md`:

```text
Call get_local_date exactly once and report the date it returns.

Then stop. Do not call any other tool, do not write files, do not run shell commands.
```

The schedule is `0 3 * * *` so the cron trigger never fires during the test; the
run is started explicitly with `launch`. That keeps the test deterministic.

## Why the tool set is safe

`TOPSAILAI_ENABLED_TOOLS=time_tool` is an allow-list, not an addition. Two
details make it work:

- `time_tool` declares `FLAG_TOOL_ENABLED = False` upstream, so it is off unless
  named explicitly. Naming it is what turns it on.
- The value must be the bare name. Adding `+` or `*` as a list element
  re-enables every tool, which would defeat the purpose.

The task's `env` is applied before the provider's own requirements, so the
provider cannot drop this variable. It only overrides
`TOPSAILAI_INTERACTIVE_MODE` and `TOPSAILAI_TASK`.

The driver adds a few mandatory tools on top (`file_readonly_tool`,
`inject_input`, `exit_process`) and disables `file_tool`. Those are read-only or
session-control tools; none of them can modify the workspace.

## Daemon environment

The driver starts the daemon inside tmux with these variables:

| Variable | Value | Why |
|---|---|---|
| `SCHEDULER_TASKS_ROOT` | `.tmp/live-topsailai/tasks` | Point at the temporary tree. |
| `SCHEDULER_CONTROL_SOCKET` | `.tmp/live-topsailai/scheduler.sock` | Keep the CLI off the default socket. |
| `SCHEDULER_LOG_OUTPUT` | `.tmp/live-topsailai/daemon.log` | Capture evidence to disk. |
| `SCHEDULER_LOG_LEVEL` | `debug` | Keep the provider exchange visible. |
| `SCHEDULER_RESCAN_INTERVAL` | `1s` | Do not wait 30s for discovery. |
| `SCHEDULER_SHUTDOWN_GRACE` | `5s` | Keep teardown short. |
| `SCHEDULER_DEFAULT_TIMEOUT` | `5m` | Match the task's own timeout. |
| `SCHEDULER_DEFAULT_PROVIDER_PATH` | the provider executable | Avoid repeating the path. |
| `SCHEDULER_POLL_INTERVAL` | `1s` | Observe completion promptly. |
| `SCHEDULER_PROVIDER_CALL_TIMEOUT` | `180s` | Must exceed the provider's own 120s launch budget. |
| `TOPSAILAI_PROVIDER_STATE_DIR` | `.tmp/live-topsailai/provider-state` | Keep run records inside the test folder. |

`SCHEDULER_PROVIDER_CALL_TIMEOUT` is set explicitly even though the scheduler
default is now `180s`, which already exceeds the provider's `LAUNCH_TIMEOUT` of
`120s`. Stating it here keeps the relationship visible: if either budget changes,
the mismatch is obvious in this file rather than hidden in a default.

## Running it

```bash
bash providers/scheduler-provider-topsailai/tests/live/run.sh
```

The driver follows the project's tmux conventions: a deterministic session name,
output written to disk, readiness polled from observable output, the exit code
recorded in a separate file, and cleanup by exact session name. It never uses
`killall` or `pkill`.

Readiness is polled in two steps: the log must contain `scheduler starting`, then
`status` must answer on the control socket. Only then does the test assert
anything.

The driver recreates `.tmp/live-topsailai/` on every run, so a previous failure
cannot leave a task pair behind that makes the next run pass for the wrong
reason.

## Reading the result

A passing run prints one `ok:` line per assertion and ends with
`N checks, 0 failures`.

On failure the workspace is kept so the evidence can be inspected. The useful
files are `daemon.log` for the provider exchange, `launch.json` for the launch
result, and `provider-state/*.json` for the recorded session id.

The agent's own output is not in `daemon.log`: the agent writes it to its session
artifacts under `TOPSAILAI_HOME`. To confirm the tool set independently, read the
session stdout:

```bash
grep -F "effective_tools" "${TOPSAILAI_HOME:-$HOME/.topsailai}"/workspace/task/<session_id>.*.session.stdout
```

A correct run shows exactly two entries, `time_tool-get_local_date` and
`time_tool-get_local_time`.

The session metadata in the same folder is the other useful file. It records the
agent's own pid, its terminal status, and the workspace it actually ran in:

```bash
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["status"], d["pid"], d["project_workspace"])' \
  "${TOPSAILAI_HOME:-$HOME/.topsailai}"/workspace/task/<session_id>.*.session.meta
```

## Observed run

The test passes. A full run reports:

```text
[live] ok: the daemon reported startup
[live] ok: the control socket answered
[live] ok: status succeeds
[live] ok: the task is discovered
[live] ok: the task is scheduled and idle
[live] ok: the task runs to completion
[live] ok: the provider wrote a state record
[live] ok: the record carries a session id
[live] ok: the provider recorded session wa-ab19a138228e
[live] ok: the record names the single-turn driver
[live] ok: the agent recorded a terminal status
[live] ok: the agent ran in the requested workspace
[live] ok: the agent's working directory is the workspace
[live] ok: poll ended on the agent's recorded status
[live] ok: time_tool was available to the agent
[live] ok: file_tool was not available to the agent
[live] 16 checks, 0 failures
```

The daemon's own record of the run shows the supervision ladder ending on the
metadata rather than on `session status`:

```text
run finished | state=finished exit_code=0 polls=6 duration=7464850592
             detail="session wa-ab19a138228e recorded status completed"
```

The provider's record shows the launcher pid and the driver it selected:

```json
{"run_id": "b6fe6cbe50c94c44856abc44e2a83f2c", "session_id": "wa-ab19a138228e",
 "launcher_pid": 2704943, "launcher_exit": 0, "task_id": "probe/time",
 "driver": "topsailai_agent_chat"}
```

The session metadata shows the workspace was honoured, which is the assertion
that used to fail:

```text
status = completed
pid = 2704998
project_workspace = /TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace
pwd = /TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace
```

And the agent's stdout shows the tool allow-list held:

```text
[available_tools] [2] ['time_tool-get_local_time', 'time_tool-get_local_date']
[effective_tools] [2] ['time_tool-get_local_time', 'time_tool-get_local_date']
[ToolStat] tool=time_tool-get_local_date count=1
```

## Two defects this test found

Both were invisible to the stubbed unit tests, because a stub answers whatever it
is told to answer.

**The launch never returned.** The default driver runs unlimited turns, so the
agent finished its work and then waited for a next turn that never came. The turn
count lives inside the driver script and is not reachable from the provider, so
the provider now selects the single-turn driver with `--driver`. The operating
system environment variable would not have worked: it ranks last in driver
resolution, so any `settings.yaml` naming `ai_agent_driver` overrides it.

**The launch blocked for the whole run.** A foreground launch does not return
until the agent exits, so a task longer than the scheduler's call timeout would be
reported as a provider failure while the agent was working correctly. The provider
now submits with `--background` and supervises through `poll`.

A third defect was in the scheduler rather than here: it never set the provider's
working directory, so the agent ran wherever the scheduler happened to be. The
scheduler now runs the provider in the task's workspace, which is why the metadata
above reports the requested folder.

## Why the test is still safe

The `time_tool` allow-list is the primary guarantee, and workspace isolation is
the second layer. The agent can read the clock and nothing else: no file writes,
no shell, no network. Even if a future change broke the workspace handling again,
the agent would still have no tool that could modify anything.

Keeping both layers matters because they fail independently. The allow-list is
enforced by the agent's tool loader; the workspace is enforced by the scheduler
setting the provider's working directory. A regression in either one alone does
not make the run dangerous.
