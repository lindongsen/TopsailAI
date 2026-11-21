---
maintainer: AI
author: DawsonLin
status: resolved
severity: high
created: 2026-11-21
resolved: 2026-11-22
---

# The provider launches the agent in the foreground, so `start` never returns

## Symptom

Every task run through the TopsailAI provider failed after 120 seconds with:

```text
start run: provider "..." start exited 1: topsailai-provider: topsailai did not answer within 120s
```

No run record was written, so `poll` had nothing to report and the scheduler
recorded `exit_code: -1`.

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

The launch command could also be reproduced directly:

```bash
timeout 90 topsailai workspace agent -m raw --non-interactive --json <workspace> </dev/null
echo $?   # 124
```

## Root cause

The original diagnosis in this file was **wrong**. It blamed the missing
`--background` flag and claimed that `--non-interactive` plus
`TOPSAILAI_INTERACTIVE_MODE=0` "neither makes the foreground process exit".

The real cause is the **turn count of the selected agent driver**.

`times` is hard-coded inside each driver script and is not reachable from the
provider:

| Driver script | Actual call | Turns |
|---|---|---|
| `topsailai_agent_chat` | `run(times=1)` | exits after one turn |
| `topsailai_agent_chats` | `run()` | unlimited |
| `topsailai_agent_plan_task` | `run(times=1)` | exits after one turn |
| `topsailai_agent_plan_tasks` | `run()` | unlimited |

The provider did not pass `--driver`, so it fell back to the default
`topsailai_agent_chats`, which is the unlimited driver. `TOPSAILAI_INTERACTIVE_MODE=0`
only suppresses prompts and input waiting; the `times=0` loop structure remains,
so after finishing one turn the agent returns to the "wait for the next turn"
branch and the foreground process never exits.

The environment-variable route cannot fix this. Driver resolution priority is:

```text
1. interactive menu selection
2. --driver CLI argument
3. settings.yaml environment TOPSAILAI_AGENT_DRIVER
4. settings.yaml ai_agent_driver field
5. OS environment TOPSAILAI_AGENT_DRIVER   ← last
```

The OS environment variable ranks last, so any `settings.yaml` in the target
folder overrides it. `--driver` must therefore be a flag.

## Evidence

The agent's own log proved the work completed before the hang:

```text
[available_tools] [2] ['time_tool-get_local_date', 'time_tool-get_local_time']
[ToolStat] tool=time_tool-get_local_date count=1 sum_sec=0.0
The date returned by `get_local_date` is **2026-11-21** (full timestamp: `2026-11-21T20:49:25`).
elapsed_time        : 15
>>> Your Turn: (pid=3883467)  Press 'CTRL D' or Enter 'EOF' for end
```

Measured twice: `exit=124` under `timeout 100`, and again `exit=124` under
`timeout 90` with stdin redirected from `/dev/null`.

After the fix, the same command form returns naturally:

```text
EXIT=0
{"ok": true, "exit_code": 0, "action": "agent", "session_id": "wa-0200732d1abc",
 "pid": 2514074, "delivery_state": "launcher_exited",
 "response": {"driver": "topsailai_agent_chat", ...}}
```

## Fix

Two changes, both in the provider:

1. `launch_arguments()` now passes `--driver topsailai_agent_chat` (overridable
   through `TOPSAILAI_PROVIDER_DRIVER`), so the agent ends after one turn.
2. `launch_arguments()` also passes `--background`, because a foreground
   single-turn launch blocks for the whole run and would exceed the scheduler's
   call timeout. Measured: foreground blocks ~3.6 s for a 3 s task; background
   returns in ~1.3 s with a session id.

`--background` alone was never sufficient and was never the root cause. It is
required for a different reason: to keep `start` short.

## Related

The false-`finished` race that `--background` used to cause is gone, because the
provider no longer consults `session status`. Liveness now comes from the
control-channel heartbeat, then the session meta, then the process table. See
`providers/scheduler-provider-topsailai/README.md` section "Liveness".
