---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The inventory collector ignores its own context when resolving resource IDs

## Trigger

An inventory collection cycle runs while the Endpoint is shutting down, or while
a forced collection request is cancelled or times out. The cycle reaches the
resource-ID resolution step for a discovered session.

## Observed behavior

`internal/endpoint/collector.go` calls the resource store with
`context.Background()` instead of the context the collector was given:

```text
mapping, lookupErr := c.store.LookupResourceID(context.Background(), providerKey)
...
mapping, lookupErr = c.store.GetOrCreateResourceID(context.Background(), item.binding.AdapterID, providerKey, nowMS)
```

Both calls therefore ignore cancellation, deadline and shutdown. The same hazard
class was fixed in the TopsailAI adapter during the output follow work, where
`providerTarget` was changed to accept the caller's context instead of creating
its own; this site was out of scope for that change and remains.

## Impact

- A cancelled or timed-out collection still performs store work, so shutdown can
  be delayed by a cycle that was already abandoned.
- A store call that blocks cannot be interrupted, so the collector goroutine can
  outlive the request that started it.
- The inconsistency is a trap for the next reader: one path in the same package
  honours cancellation and another silently does not, so a future change that
  relies on cancellation will work in one place and fail in the other.

## Root cause

The collector was written before cancellation was threaded through the store
calls, and `context.Background()` was used as a placeholder to satisfy the
signature. Nothing failed, because the store calls are fast in the current
implementation, so the placeholder was never revisited.

## Proposed resolution

- Thread the collector's own context into both store calls, so cancellation and
  deadlines propagate.
- Audit the package for other `context.Background()` uses and fix them in the
  same change, so the package has one rule rather than a per-call decision.
- Treat a cancelled store call as an aborted cycle rather than a collection
  failure, so a shutdown does not publish a degraded report.

## Verification

- A collector test cancels the context before the resolution step and asserts the
  store is not called, or that the call returns promptly with a cancellation
  error.
- A test asserts a normal cycle still resolves and creates mappings exactly as
  before, so the change is behaviour-preserving on the happy path.
- A grep-based check in review confirms no remaining `context.Background()` in
  the collector path.
