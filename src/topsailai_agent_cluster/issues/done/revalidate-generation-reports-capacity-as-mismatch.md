---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---
# Generation revalidation reported a busy adapter as a stale generation

## Symptom

A command whose target generation could not be revalidated because the adapter was
out of capacity was reported as a generation mismatch. The operator was told the
target had changed, so they re-inspected a session that was never the problem, while
the same intent would have succeeded unchanged once the competing invocation
finished.

## Root cause

`internal/endpoint/executor.go` discarded the inspection error:

```go
inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: target})
if inspectErr != nil || !inspection.Found || inspection.ProviderGeneration != target.ProviderGeneration {
    return fmt.Errorf("resource generation does not match")
}
```

A capacity refusal means the adapter was never invoked, so it proves nothing about
the target. Flattening it into the mismatch message destroyed the only evidence that
distinguished "the adapter was busy" from "the generation really changed".

Three call sites then flattened the result differently, so one cause produced three
different wrong answers:

| Call site | Operation family | Reported when busy |
|---|---|---|
| `executor.go` mutating path | `message.send`, `agent.stop`, `execution.interrupt`, `ctl.*` | `target_generation_mismatch` |
| `executor.go` read path | `output.read` | `generation_mismatch` |
| `executor.go` follow path | `output.follow` | bare error, so `follow.go` defaulted to `provider_error` |

The follow surface was the worst of the three: it had no mismatch code of its own, so
the flattened error reached the end-frame default and told the operator the provider
had failed, when the provider had never been called.

## Scope of the defect

The snapshot fast path in `revalidateGeneration` returns without inspecting when the
persisted snapshot is known, fresh and contains the resource. The defect therefore
only triggers when the snapshot cannot answer: unknown data, stale data, or a
resource absent from it. That lowers the frequency but does not remove the defect,
because those are exactly the cases where the live inspection is the only evidence.

## Fix

`revalidateGeneration` now preserves the capacity cause instead of flattening it, and
each caller classifies it through one shared primitive:

- `capacityCode(err) (string, bool)` is the single place that decides whether an error
  is a capacity refusal. `observationFailureCode`, `readFailureCode` and the new
  `revalidationFailureCode` all delegate to it, so a second spelling of "capacity"
  cannot appear.
- `revalidationFailureCode(err, mismatchCode)` returns the retryable capacity code
  when the cause is capacity, and otherwise keeps the caller's own mismatch code.
  The mismatch vocabulary genuinely differs per surface and is already part of each
  surface's contract, so only the capacity classification is shared.
- `follow.go` gained an `adapter.ErrBusy` case before the `provider_error` default,
  because the default is what misreported it.

The shared primitive exists because this defect family was created by updating one
path and leaving its siblings alone. A repeated check would recreate that condition.

## Verification

Five new tests, each proven to fail before it passed:

- `TestRevalidationCapacityIsNotReportedAsMismatch` (mutating path, two cases)
- `TestReadOutputRevalidationCapacityIsNotReportedAsMismatch` (read path, two cases)
- `TestFollowOutputRevalidationCapacityPreservesCause`
- `TestFollowOutputRevalidationFailureIsNotCapacity`
- `TestStartFollowReportsCapacityAsRetryable`

Removing the capacity branch in `revalidateGeneration` failed the first three with the
old codes (`target_generation_mismatch`, `generation_mismatch`, and the flattened
mismatch message). Removing the `adapter.ErrBusy` case in `follow.go` failed the last
one with `provider_error`. Both were restored and the suite returned green.

The genuine-failure cases are asserted in the same table as the capacity cases, so a
fix that classified every error as capacity would fail too.

## Not covered

The deployed Endpoint binary is older than this fix, so the behaviour on a running
node is unchanged until it is redeployed. No live command was executed to confirm the
new codes end to end; the evidence is unit-level.
