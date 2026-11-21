---
maintainer: AI
author: DawsonLin
status: open
severity: high
created: 2026-11-21
---

# The provider launches the agent in the foreground, so `start` never returns

## Symptom

Every task run through the TopsailAI provider fails after 120 seconds with:

```text
start run: provider "..." start exited 1: topsailai-provider: topsailai did not answer within 120s
```

No run record is written, so `poll` has nothing to report and the scheduler
records `exit_code: -1`.

## Reproduction

Start the daemon against a temporary task tree and launch one task:

```bash
SCHEDULER_TASKS_ROOT=.tmp/live-topsailai/tasks \
SCHEDULER_PROVIDER_CALL_TIMEOUT=180s \
SCHEDULER_DEFAULT_PROVIDER_PATH=providers/scheduler-provider-topsailai/bin/scheduler-provider-topsailai \
.tmp/topsailai_scheduler run
```

then:

```bash
SCHEDULER_CONTROL_SOCKET=.tmp/live-topsailai/scheduler.sock \
.tmp/topsailai_scheduler launch probe/time --wait --json
```

The daemon log shows the failure after exactly 120 seconds.

The launch command can also be reproduced directly:

```bash
timeout 90 topsailai workspace agent -m raw --non-interactive --json <workspace> </dev/null
echo $?   # 124
```

## Root cause

`launch_arguments()` builds a foreground command:

```python
arguments = [binary(), "workspace", "agent", "-m", "raw", "--non-interactive", "--json"]
```

`run_command()` then waits on it with `subprocess.run(..., timeout=LAUNCH_TIMEOUT)`.

The agent finishes its work in about 15 seconds and prints:

```text
>>> Your Turn: (pid=3883467)  Press 'CTRL D' or Enter 'EOF' for end
```

and then waits for input indefinitely. `--non-interactive` stops the launcher
prompting, and `TOPSAILAI_INTERACTIVE_MODE=0` stops the agent prompting, but
neither makes the foreground process exit. Redirecting stdin from `/dev/null`
does not help either; the process still hangs.

The provider's docstring justifies `-m raw` as avoiding a wrapper's exit status,
but the command never adds `--background`, so the justification does not hold in
practice: there is no exit status to observe because the process never exits.

## Evidence

The agent's own log proves the work completed before the hang:

```text
[available_tools] [2] ['time_tool-get_local_date', 'time_tool-get_local_time']
[ToolStat] tool=time_tool-get_local_date count=1 sum_sec=0.0
topsailai.final_answer
The date returned by `get_local_date` is **2026-11-21** (full timestamp: `2026-11-21T20:49:25`).
elapsed_time        : 15
>>> Your Turn: (pid=3883467)  Press 'CTRL D' or Enter 'EOF' for end
```

Measured twice: `exit=124` under `timeout 100`, and again `exit=124` under
`timeout 90` with stdin redirected from `/dev/null`.

## Suggested fix

Launch in the background and treat the receipt as a submission:

```text
topsailai workspace agent -m raw --background --non-interactive --json <workspace>
```

That form returns immediately with a usable receipt:

```json
{"ok": true, "session_id": "wa-936606254f65", "pid": 3878451, "delivery_state": "submitted"}
```

`delivery_state` is `submitted`, not `started`, so `start` should record the
session id and let `poll` decide whether the agent is working. That is already
the intended contract: the README says a launch is a submission, not the work.

## Impact

The provider cannot run any task against a real agent. The stub-based unit tests
do not catch this because the stub exits immediately.
