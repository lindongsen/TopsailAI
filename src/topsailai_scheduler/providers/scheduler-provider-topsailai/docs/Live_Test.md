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
- The provider launches an agent and records a session id.
- The agent session reaches `idle`, so `poll` reports `finished`.
- The tool set offered to the agent is exactly `time_tool`.

## Isolation

Everything lives under `.tmp/live-topsailai/`. The real `tasks/` tree is never
touched, so a stray run cannot fire a production task.

```text
.tmp/live-topsailai/
├── tasks/probe/time.yaml     the task under test
├── tasks/probe/time.md       its content
├── agent-workspace/          the folder the agent runs in
├── provider-state/           the provider's run records
├── daemon.log                daemon stdout and stderr
├── daemon.exit               the daemon's exit code
├── run.log                   the test's own output
└── run.sh                    the driver
```

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

`SCHEDULER_PROVIDER_CALL_TIMEOUT` is not optional. Its default is `30s`, which is
shorter than the provider's `LAUNCH_TIMEOUT` of `120s`, so the scheduler would
abandon the call before the provider gives up and the real error would be hidden.

## Running it

```bash
bash .tmp/live-topsailai/run.sh
```

The driver follows the project's tmux conventions: a deterministic session name,
output written to disk, readiness polled from observable output, the exit code
recorded in a separate file, and cleanup by exact session name. It never uses
`killall` or `pkill`.

Readiness is polled in two steps: the log must contain `scheduler starting`, then
`status` must answer on the control socket. Only then does the test assert
anything.

## Reading the result

A passing run prints one `ok:` line per assertion and ends with
`N checks, 0 failures`.

On failure the workspace is kept so the evidence can be inspected. The useful
files are `run.log` for the assertion that failed, `daemon.log` for the provider
exchange, and `provider-state/*.json` for the recorded session id.

To confirm the tool set independently, read the agent's own log:

```bash
grep -F "effective_tools" .tmp/live-topsailai/daemon.log
```

A correct run shows exactly two entries, `time_tool-get_local_date` and
`time_tool-get_local_time`.

## Known failure: the launch never returns

As of this writing the test does **not** pass, and the cause is in the provider,
not in the test.

`launch_arguments()` builds:

```text
topsailai workspace agent -m raw --non-interactive --json <workspace>
```

That command runs in the foreground and blocks. The agent itself finishes in
about 15 seconds and prints `>>> Your Turn: (pid=...) Press 'CTRL D' or Enter
'EOF' for end`, then waits for input that never arrives. Redirecting stdin from
`/dev/null` does not help; the process still does not exit.

The provider waits `LAUNCH_TIMEOUT` (120s), then reports:

```text
topsailai-provider: topsailai did not answer within 120s
```

and the daemon logs:

```text
start run: provider "..." start exited 1: topsailai-provider: topsailai did not answer within 120s
```

Adding `--background` makes the same launch return immediately with a valid
receipt:

```json
{"ok": true, "session_id": "wa-936606254f65", "pid": 3878451, "delivery_state": "submitted"}
```

So the fix is to launch in the background and treat the receipt as a submission,
which is what the provider's own comment already says a launch is.

## Known failure: the requested workspace is ignored

The receipt reports `"workspace": "/TopsailAI/src/topsailai"` even though the
task asked for `.tmp/live-topsailai/agent-workspace`.

The cause is outside this provider. The `topsailai` wrapper does
`cd "${CWD}/../"`, which lands in `/TopsailAI/src/topsailai`, and that folder's
`.topsailai/settings.yaml` sets `workspace: /TopsailAI/src/topsailai`, which then
wins over the path passed on the command line.

Until that is resolved, a live test cannot confine the agent to a scratch
folder. The `time_tool` allow-list is what keeps the run harmless in the
meantime, which is why this test depends on it rather than on workspace
isolation.
