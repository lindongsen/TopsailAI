---
maintainer: AI
author: DawsonLin
status: open
severity: high
created: 2026-11-21
---

# The launched agent ignores the workspace the task asked for

## Symptom

A task sets `workspace: /TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace`,
but the agent runs in `/TopsailAI/src/topsailai` instead.

The launch receipt reports the wrong folder:

```json
{"response": {"workspace": "/TopsailAI/src/topsailai", "mode": "raw", "background": true}}
```

The agent's session log agrees:

```text
project_workspace : /TopsailAI/src/topsailai
pwd               : /TopsailAI/src/topsailai
```

## Reproduction

Launch any task whose `workspace` differs from `/TopsailAI/src/topsailai`, then
read the receipt:

```bash
topsailai workspace agent -m raw --background --non-interactive --json \
  /TopsailAI/src/topsailai_scheduler/.tmp/live-topsailai/agent-workspace
```

The `response.workspace` field reports `/TopsailAI/src/topsailai`.

## Root cause

Two things combine, and neither is in the provider.

The `topsailai` wrapper at `/TopsailAI/src/topsailai/bin/topsailai` does:

```bash
CWD=$(dirname "$(readlink -f $0)")
cd "${CWD}/../"
```

so it always runs from `/TopsailAI/src/topsailai`, regardless of the caller's
working directory.

That folder's `.topsailai/settings.yaml` then sets:

```yaml
workspace: /TopsailAI/src/topsailai
```

and that configured value wins over the path passed on the command line.

## Impact

A live test cannot confine the agent to a scratch folder. The agent runs in the
real project folder, so any tool that can write files can modify real source.

This is why the live test in `providers/scheduler-provider-topsailai/docs/Live_Test.md`
relies on `TOPSAILAI_ENABLED_TOOLS=time_tool` for safety rather than on workspace
isolation. The allow-list is the only effective guard until this is fixed.

## Suggested fix

Either honour the path argument over the configured `workspace`, or make the
wrapper not change directory before resolving configuration. The first is
preferable: an explicit argument should beat a configuration default.

## Note

This defect is in the upstream `topsailai` CLI, not in this repository. It is
recorded here because it blocks this provider's live test.
