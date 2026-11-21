---
maintainer: AI
author: DawsonLin
status: withdrawn
severity: high
created: 2026-11-21
withdrawn: 2026-11-22
---

# The launched agent ignores the workspace the task asked for

## Withdrawal

This issue is **wrong**. A later probe disproved it, and the record is kept only
so nobody re-opens the same false trail.

The original report claimed the agent ran in `/TopsailAI/src/topsailai` instead
of the folder passed on the command line. That was observed once, but the
observation was misread: the receipt field being inspected was not the field
that carries the resolved workspace, and the session being inspected belonged to
an earlier launch that had been started without a workspace argument.

## Evidence that disproves it

A live run through the scheduler, with the task setting
`workspace: .tmp/live-topsailai/agent-workspace`, produced a session meta that
records the requested folder in both fields:

```json
{
  "session_id": "wa-e1b0b91bd8f0",
  "pid": 2670011,
  "status": "completed",
  "project_workspace": "/TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace",
  "pwd": "/TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace"
}
```

A direct probe of the same command form agreed: `project_workspace` and `pwd`
both equalled the requested folder.

## Why the original theory was wrong

The original root cause pointed at two real facts:

- the `topsailai` wrapper does `cd "${CWD}/../"` before running;
- that folder's `.topsailai/settings.yaml` sets `workspace: /TopsailAI/src/topsailai`.

Both facts are true, but neither overrides the positional folder argument.
`_resolve_folder()` in `workspace_agent_cli.py` resolves the argument, and
`launch_configured_agent` records `workspace=folder`. An explicit argument beats
the configured default, which is the behaviour the original report asked for.

## What remains true

The scheduler did have a real workspace defect, but it was on the scheduler
side, not upstream: `provider/cli.go` never set `runner.Request.Dir`, so the
provider process inherited the scheduler's own working directory. That is fixed
and covered by `TestStartRunsProviderInWorkspace`.

## Impact of the false report

The live test's safety note was written as if workspace isolation were
unavailable, so it leaned on `TOPSAILAI_ENABLED_TOOLS=time_tool` alone. That
allow-list is still the primary guard, and it is still correct to keep it, but
the reason is now "defence in depth" rather than "the only guard".
