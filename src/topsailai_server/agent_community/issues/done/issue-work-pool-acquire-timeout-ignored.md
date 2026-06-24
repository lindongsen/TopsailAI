---
status: fixed
severity: high
phase: CLI Manual Testing Phase 8
related_test_cases:
  - CLI-ENV-005
---

# ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT Is Ignored by NATS Consumer

## Summary
During `CLI-ENV-005` (Work-Pool Acquire Timeout), a message mentioning two long-running worker-agents was sent to a group while the server was configured with `ACS_AGENT_WORK_POOL_PER_NODE=1` and `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT=5s`. The expected behavior was that the second agent invocation would wait up to 5 seconds for a work-pool slot. Instead, the second invocation failed immediately with `work pool limit reached`, proving that the configured acquire timeout was never honored.

## Root Cause

`internal/nats/consumer.go` called `c.pool.TryAcquire(...)` in `processAgentTarget`. `TryAcquire` is non-blocking: it returns `ErrPoolLimitReached` instantly when the semaphore is full. The configured `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT` was loaded into `cfg.AgentWorkPool.AcquireTimeout` by `internal/config`, but the consumer never used `Pool.AcquireWithTimeout`.

## Fix

### `internal/nats/consumer.go`

In `processAgentTarget`, the consumer now reads `cfg.AgentWorkPool.AcquireTimeout`:

- If the timeout is greater than zero, it calls `c.pool.AcquireWithTimeout(timeout, pendingMsg.SenderID, group.GroupID, traceID)`.
- If the timeout is zero or negative, it falls back to the original `c.pool.TryAcquire(...)` behavior.

This preserves the existing immediate-redelivery behavior when no timeout is configured, while honoring the documented wait-with-timeout behavior when one is set.

### `internal/nats/consumer_test.go`

Added two unit tests:

- `TestProcessAgentTarget_AcquireTimeoutWaits`: verifies that with a positive timeout and a saturated pool, `processAgentTarget` waits for approximately the configured duration before returning `ErrPoolLimitReached`.
- `TestProcessAgentTarget_ZeroAcquireTimeoutFailsFast`: verifies that with a zero timeout and a saturated pool, `processAgentTarget` returns `ErrPoolLimitReached` immediately.

## Verification

- `go test ./internal/nats/... ./internal/workpool/... -count=1` — PASS
- `make build-server` — SUCCESS

## Next Steps

1. Re-run `CLI-ENV-005` with the rebuilt server.
2. Confirm that the second agent invocation waits up to `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT` before failing or being redelivered.
3. Update `docs/cases/TestCase_manual_cli_complete.md` with the result.

## Notes

- The fix does NOT introduce or change soft-delete behavior for `groups` or `group_member`.
- Existing `internal/workpool/semaphore.go` already implements `AcquireWithTimeout`; this fix only wires the consumer to use it.
