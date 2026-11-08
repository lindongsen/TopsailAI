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

## Resolution

Fixed. The issue understated the defect in two ways, both verified by reading the
code rather than trusting the report.

### There were three sites, not two

The report named `LookupResourceID` and `GetOrCreateResourceID`. A grep found a
third: `ApplySourceSnapshot(context.Background(), snapshot, nowMS)` at the end of
`apply`. It is the same hazard class and would have been left behind by a fix
that followed the report literally.

### The real gap was a missing parameter, not a wrong argument

The report framed this as passing the wrong context. In fact `apply` had no
context parameter at all:

```text
func (c *Collector) apply(item discoveryResult, nowMS int64)
```

There was no context to pass, which is why the placeholder survived: it was not
an oversight at a call site, it was structurally impossible to thread the context
without changing the signature and its caller.

### What changed

| File | Change |
|---|---|
| `internal/endpoint/collector.go` | `apply` now takes `ctx context.Context` and returns `error`. `Collect` aborts the cycle when `apply` fails. All three store calls use `ctx`. |
| `internal/endpoint/service.go` | Both collector call sites log an aborted cycle at info level instead of an ERROR. |

A cancelled cycle mutates nothing: there is an early `ctx.Err()` check, a second
check immediately before writing `c.sources`, and a cancellation-aware branch
around `ApplySourceSnapshot`. A store failure that is not caused by cancellation
still reports `resource_mapping_failed`, because that is a real defect the
operator must see.

The `results` channel is buffered for every binding, so the remaining discovery
goroutines can still send and exit when `Collect` returns early. No goroutine
leak was introduced.

### One intentional exception

`internal/endpoint/follow.go` still uses `context.Background()` for
`s.logger.Log(...)`. That is correct and must not be "fixed": a log call must not
be cancelled, otherwise the record of a lost output follow terminal frame
disappears exactly when the system is shutting down, which is when it matters
most.

### Evidence

| Check | Result |
|---|---|
| `go build ./...` | clean |
| `go test ./... -count=1` | all packages pass |
| `go test ./internal/endpoint/ -cover` | 82.6% (was 79.3%) |
| `gofmt -l internal/endpoint/` | clean |
| `go vet ./internal/endpoint/` | clean |
| `grep -c "context.Background()" internal/endpoint/collector.go` | 0 |

New tests:

| Test | Asserts |
|---|---|
| `TestCollectAbortsCancelledCycleWithoutTouchingStore` | A cancelled cycle returns `context.Canceled`, mutates no cache entry and persists no snapshot |
| `TestCollectResolvesMappingsOnHealthyCycle` | The happy path still creates mappings and replaces the provider session ID with an opaque resource ID |
| `TestCollectReportsStoreFailureThatIsNotCancellation` | A broken store is still a collection failure, not a silent abort |
| `TestPublishRefreshLogsAbortedCollectionAsInfo` | A cancelled forced collection logs at info, not ERROR |
| `TestPublishRefreshKeepsErrorForGenuineFailure` | A real refresh failure still logs at ERROR |
| `TestCollectionLoopAbortsCancelledCycleWithoutError` | A cycle cancelled while running logs an abort, not an ERROR |
| `TestCollectionLoopKeepsErrorForGenuineFailure` | A real periodic failure still logs at ERROR |

### Reverse verification

The tests were shown to fail without the fix, otherwise they would prove nothing.

- Reverting the three store calls to `context.Background()` and removing the
  cancellation guards made `TestCollectAbortsCancelledCycleWithoutTouchingStore`
  fail with `Collect error=<nil>, want context.Canceled`. The other two collector
  tests still passed, which is correct: they guard the healthy path.
- Removing both log guards made the abort tests fail with the exact spurious
  ERROR the issue describes:
  `level=ERROR msg="refresh inventory" error="context canceled"` and
  `level=ERROR msg="collect inventory" error="context canceled"`.

Both reverts were restored and the full suite re-run green.

### A note on reachability

Cancelling between cycles never reaches the aborted branch, because the loop
checks `ctx.Done()` before publishing. The branch is only reachable when
cancellation happens during a collection, so the test blocks inside `Collect`
until the context is cancelled. A test that cancels between cycles would pass
without ever exercising the code it claims to cover.
