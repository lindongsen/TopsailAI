---
maintainer: AI
author: DawsonLin
status: open
severity: medium
created: 2026-11-21
---

# The scheduler's default call timeout is shorter than the provider's launch budget

## Symptom

With default settings, a provider call is abandoned after 30 seconds, but the
provider itself waits up to 120 seconds before giving up. The scheduler therefore
reports its own timeout and the provider's real diagnosis is never seen.

Observed with defaults:

```text
start did not answer within 30s
```

Observed with `SCHEDULER_PROVIDER_CALL_TIMEOUT=180s`, which lets the provider
finish and report the actual cause:

```text
start run: provider "..." start exited 1: topsailai-provider: topsailai did not answer within 120s
```

## Root cause

Two independent defaults that were never reconciled:

| Side | Setting | Default |
|---|---|---|
| Scheduler | `SCHEDULER_PROVIDER_CALL_TIMEOUT` | `30s` (`src/config/config.go:59`) |
| Provider | `LAUNCH_TIMEOUT` | `120` seconds (`bin/scheduler-provider-topsailai:61`) |

The scheduler's budget must exceed the provider's, otherwise the outer timeout
always fires first.

## Impact

Diagnosis is harder than it needs to be: the visible error names the scheduler's
timeout rather than the provider's, so the real failure is hidden. Any provider
whose internal budget exceeds 30 seconds is affected, not just this one.

## Suggested fix

Make the relationship explicit rather than coincidental. Either raise the
scheduler default above the largest supported provider budget, or have the
provider advertise its budget so the scheduler can derive its own. At minimum,
document the constraint so a provider author knows the ceiling.

## Workaround

Set `SCHEDULER_PROVIDER_CALL_TIMEOUT` above the provider's budget:

```bash
SCHEDULER_PROVIDER_CALL_TIMEOUT=180s
```

The live test does this and records why in
`providers/scheduler-provider-topsailai/docs/Live_Test.md`.
