---
maintainer: AI
status: fixed
priority: high
created: 2026-06-21
fixed: 2026-06-21
related_test: docs/cases/TestCase_manual_cli_agent_trigger.md#AGENT-013
related_issue: issue-agent-work-pool-acquire-timeout-shorter-than-chat-timeout.md
---

# Issue: NATS MaxDeliver(3) Exhausted by Immediate Nak on Pool Saturation

## Summary
When `ACS_AGENT_WORK_POOL_PER_GROUP=1` and a single message triggers multiple agents in the same group, only the first agent succeeded. The remaining agents failed permanently because the pending message was negatively acknowledged immediately on pool saturation, and NATS redelivered it at most 3 times (hardcoded `MaxDeliver(3)`) before dropping it. All redelivery attempts happened before the first agent finished, so the saturated agents never got a chance to run.

## Environment
- ACS server: built from `/TopsailAI/src/topsailai_server/agent_community`
- Go version: 1.25+
- Database: PostgreSQL (local)
- NATS: local with JetStream
- Configuration:
  - `ACS_AGENT_WORK_POOL_PER_GROUP=1`
  - `ACS_AGENT_WORK_POOL_PER_NODE=10`
  - `ACS_AGENT_WORK_POOL_PER_USER=5`
  - `ACS_NATS_ACK_WAIT_SECONDS=3600`
  - `ACS_NATS_MAX_ACK_PENDING=10`
  - `ACS_NATS_PENDING_MESSAGE_NO_ACK=false`

## Reproduction Steps
1. Start ACS server with `ACS_AGENT_WORK_POOL_PER_GROUP=1`.
2. Create a group `WorkPoolGroup`.
3. Add two worker-agents (`worker-slow-a`, `worker-slow-b`) to the group, both using a chat command that sleeps for 30 seconds and a noop health-check script.
4. Send a message mentioning both agents: `@worker-slow-a @worker-slow-b run serialized`.
5. Wait ~70 seconds and inspect messages.

## Expected Behavior
Per `docs/Environment_Variables.md` and `ORIGIN.md`, when the per-group concurrency limit is reached, messages should be delayed/redelivered via NATS JetStream. The two agents should execute sequentially, with a total elapsed time of approximately 60 seconds (30s + 30s). Each agent should produce exactly one response message.

## Actual Behavior (Before Fix)
- `worker-slow-b` acquires the per-group slot and completes after ~30 seconds.
- `worker-slow-a` fails immediately on each redelivery with:
  ```
  failed to acquire work pool slot: failed to acquire per-group semaphore: work pool limit reached
  ```
- After 3 deliveries, NATS drops the pending message.
- `worker-slow-a` never produces a response message.

## Root Cause
`internal/nats/client.go` hardcoded `nats.MaxDeliver(3)` when creating the pending-message consumer. The consumer handler in `internal/nats/consumer.go` uses `pool.TryAcquire` and calls `msg.Nak()` immediately when `ErrPoolLimitReached` is returned. Because Nak triggers instant redelivery and the per-group slot is held for the duration of the first agent's chat command (30s in the test), all 3 delivery attempts occur before the slot is released. After the 3rd failed delivery, NATS permanently removes the message.

## Fix
1. Made `MaxDeliver` configurable via the new environment variable `ACS_NATS_MAX_DELIVER` (default `0`, meaning unlimited redeliveries).
2. Added explicit `v.BindEnv` calls for all NATS configuration fields in `internal/config/config.go` to ensure documented environment variables are honored.
3. Updated `internal/nats/client.go` to use `nats.MaxDeliver(c.cfg.MaxDeliver)` instead of the hardcoded `3`.
4. Updated `internal/config/config_test.go` and `internal/nats/client_test.go` to cover the new field.
5. Updated `docs/Environment_Variables.md` to document `ACS_NATS_MAX_DELIVER`.

## Files Changed
- `internal/config/config.go`
- `internal/config/config_test.go`
- `internal/nats/client.go`
- `internal/nats/client_test.go`
- `docs/Environment_Variables.md`

## Verification
- `go test ./...` passes.
- `make build` passes.

## Next Step
Re-run manual test AGENT-013. With the default `ACS_NATS_MAX_DELIVER=0`, the second worker-agent in the same group should now be redelivered indefinitely until the per-group slot is free, resulting in serialized execution.
