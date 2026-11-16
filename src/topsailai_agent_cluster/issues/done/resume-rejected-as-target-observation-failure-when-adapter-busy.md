---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# `resume` is rejected as a target observation failure when the adapter is merely busy

## Trigger

Human report (verbatim):

```
workspace> resume 28
resume session (检查部署会话运行状态) (wa-470fab9b316a)? Confirm resume? [y/N]
answer> y
resuming agent session (检查部署会话运行状态) (wa-470fab9b316a) (ac.ai-dev)...
  request delivered
  failed
CommandID: cli-1794789357490516652
Status: rejected
DeliveryBoundary: not_started
EffectCertainty: not_applied
ErrorCode: target_observation_failed
history row numbers are stale after resume; run history to refresh
```

## Observed behavior

`resume` was rejected with `target_observation_failed` and `EffectCertainty: not_applied`, so no
provider mutation happened. The target session was valid and its mapping existed
(`res_ddf8524762717c575fc4aaf07b81a9d3` → `session:v1:OuzN4iFDLx8oHSECG28zfq9IGzN80TY6E59zTto60_U`,
adapter `topsailai-ai-dev`).

The Endpoint log at the same time reported capacity contention, not a provider fault:

```
08:33:44 ERROR query adapter history | provider adapter capacity exhausted: discovery
08:33:56 ERROR query adapter history | provider adapter capacity exhausted: discovery
08:34:13 ERROR query adapter projects | provider adapter capacity exhausted: discovery
```

The failed command ID decodes to `2026-11-16 08:35:57 +08`, inside that contention window.

## Root cause

Two independent layers.

### Layer 1: the deployed binary predates the capacity-wait fix

Commit `6e00bb89 fix: wait for adapter capacity inside the caller budget` (2026-11-16 08:00:17) is an
ancestor of HEAD and `acquireWithin` is present in source
(`internal/adapter/genericcli/scheduler.go:88`). The deployed
`/opt/agent-cluster/bin/agent-cluster-endpoint` is dated 2026-11-16 06:00:06, and `strings` on that
binary shows `provider adapter capacity exhausted` but zero occurrences of `acquireWithin`. The running
Endpoint therefore still fails on the first capacity refusal instead of waiting inside the caller's
budget.

The effective discovery concurrency is 1: the TopsailAI provider declares `Discovery = 1`
(`providers/topsailai/descriptor.go:44-49`) and the Endpoint ceiling is 2
(`src/main/agent-cluster-endpoint/adapter_factory.go:45`), so `minPositive` yields 1. One
`topsailai workspace list --json --local` invocation costs about 0.8 s on this host, so every
`Inspect`, `history.messages`, `model.catalog`, `launch.options` and `session.messages` read competes
with the periodic collection cycle for that single slot.

### Layer 2: one error code conflates two different facts

`internal/endpoint/executor.go` mapped every `Inspect` error to `target_observation_failed` at three
sites (resume, drive stop, generationless clean). A capacity collision is a transient condition that
says nothing about the target: the same intent may succeed unchanged once the competing invocation
finishes. Reporting it as a target observation failure sends the operator to inspect a session that was
never the problem, and hides the only correct recovery, which is to retry.

## Fix

Layer 2 is fixed in this change. Layer 1 is a deployment gap, not a source defect.

- `internal/adapter/adapter.go` gains `ErrBusy`, the cluster-owned sentinel for "capacity was not
  available within the caller's budget". It lives in the contract package so the Endpoint can
  recognise the condition without importing a concrete adapter implementation.
- `internal/adapter/genericcli/scheduler.go` makes `ErrCapacity` wrap `adapter.ErrBusy`, so
  `errors.Is(err, adapter.ErrBusy)` is true for every capacity refusal while `ErrCapacity` keeps its
  existing identity for the scheduler's own retry loop.
- `internal/endpoint/executor.go` gains `observationFailureCode`, which returns `adapter_busy` for a
  capacity condition and keeps `target_observation_failed` for every other error. All three preflight
  sites use it, so the mapping has one definition.

`adapter_busy` is a new code. It is deliberately retryable and is never reported as a provider
failure, because only a capacity condition is provably unrelated to the target.

## Verification

- `go build ./...` and `go vet` on the touched packages pass.
- `make test-unit-common test-unit-endpoint` passes.
- Both new executor cases were proven to fail when `observationFailureCode` ignored `ErrBusy`, and the
  new scheduler case was proven to fail when `ErrCapacity` wrapped the wrong sentinel. Each break was
  reverted and the suites re-run green.

## Not a defect

`history row numbers are stale after resume; run history to refresh` is correct behaviour.
`invalidateResumeRowBindings` (`internal/tui/interactive_history.go:615-627`) clears both tables
because a resume changes the inventory, so pre-resume row numbers must not survive.

## Resolution

The remaining work was a redeploy, and it has happened. The deployed Endpoint is now
`vcs.revision=b33157dcd2e4acc07214d93f78c32ae8b982b6fd`, built `2026-11-16 10:27:06 +0800` with
`vcs.modified=true`, which is newer than the `2026-11-16 08:00:17` acceptance bound. `strings` on that
binary reports three occurrences of `acquireWithin`, so a capacity collision now waits inside the
caller's budget instead of failing.

The classification this record asked for is also in place: `1bdee96a fix: distinguish adapter capacity
from target observation failure` keeps `adapter.ErrBusy` distinguishable through
`revalidateGeneration` (`internal/endpoint/executor.go:378-380`), so a busy adapter is reported as a
retryable capacity condition rather than as a stale generation.

The underlying design question was answered separately by
`b33157dc fix: give operator reads their own adapter capacity class`: `Inspect` now uses `classRead`,
so a resume preflight no longer competes with the periodic collection for the discovery slot. See
`.task/plan_20261116T094500_operator-reads-own-capacity-class.md` (status `done`).
