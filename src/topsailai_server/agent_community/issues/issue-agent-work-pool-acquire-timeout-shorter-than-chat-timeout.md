---
status: fixed
priority: high
created_by: AIMember.km1-tester
fixed_by: AIMember.km3-programmer
fixed_at: 2026-06-21T04:35:00+08:00
related_test: docs/cases/TestCase_manual_cli_agent_trigger.md#AGENT-013
related_issue: issue-per-group-work-pool-semaphore-timeout-too-short.md
---

# AgentWorkPool Acquire Timeout Shorter Than Agent Chat Timeout

## Problem Summary
After the fix for `issue-per-group-work-pool-semaphore-timeout-too-short.md`, the consumer correctly called `msg.Nak()` when `ErrPoolLimitReached` was returned. However, the default `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT` was `30s`, the same order of magnitude as typical agent chat commands. When an agent chat command took ~30s and the per-group limit was `1`, the second agent in the same group timed out while waiting for the first agent to release the per-group semaphore. This produced repeated `context deadline exceeded` failures and unnecessary NATS JetStream redeliveries before the second agent eventually succeeded.

## Root Cause
`internal/nats/consumer.go` used `pool.AcquireWithTimeout(c.cfg.AgentWorkPool.AcquireTimeout, ...)` to hold a single pool slot for the entire pending message. When the per-group slot was held for the duration of a long chat command, the next acquire timed out and caused duplicate JetStream redeliveries.

## Fix Applied
1. **Non-blocking try-acquire** in `internal/workpool/semaphore.go`:
   - Added `Semaphore.TryAcquire()`.
   - Added `Pool.TryAcquire(userID, groupID, traceID)` which attempts to acquire global, per-user, and per-group slots without blocking.
   - On partial failure, all already-acquired slots are released.
   - Returns the existing sentinel `ErrPoolLimitReached` when any limit is saturated.

2. **Consumer refactor** in `internal/nats/consumer.go`:
   - Removed the single pool slot acquisition around the entire pending message.
   - `processMessage` now dispatches each agent target concurrently via `dispatchTargets`.
   - `processAgentTarget` calls `pool.TryAcquire` at the start of each individual agent invocation.
   - When `TryAcquire` returns `ErrPoolLimitReached`, the error is propagated back to the NATS handler, which calls `msg.Nak()` so JetStream redelivers the message once a slot is free.
   - Genuine processing failures still emit a system error message; pool-limit failures do not, avoiding duplicate error responses.

3. **Sentinel error wrapping** in `internal/workpool/semaphore.go`:
   - `AcquireWithTimeout` now wraps `context.DeadlineExceeded` with `ErrPoolLimitReached` so callers can distinguish saturation from other failures consistently.

4. **Unit tests**:
   - Updated `internal/workpool/semaphore_test.go` to assert `ErrPoolLimitReached` wrapping `context.DeadlineExceeded`.
   - Added `TestPool_TryAcquire_SuccessAndFailure` and `TestPool_TryAcquire_PartialFailureRollback`.
   - Added `TestDispatchTargets_ExecutesConcurrently` and `TestDispatchTargets_PropagatesError` in `internal/nats/consumer_test.go`.

## Verification
- `go test ./...` → PASS
- `make build` → OK

## Next Step
Re-run manual test step AGENT-013 with the default configuration. Both worker agents should execute sequentially without `context deadline exceeded` errors, and each should produce exactly one response message.

## Final Verification (km3-programmer re-check)
- `go test ./...` → PASS
- `make build` → OK (bin/acs-server, bin/acs-cli, bin/natsctl built successfully)
- Status: fixed, ready for km1-tester to resume AGENT-013.
