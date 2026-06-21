---
maintainer: AI
status: open
related_test: AGENT-013
created: 2026-06-21
---

# Issue: Per-Group Work-Pool Semaphore Timeout Too Short

## Summary
When `ACS_AGENT_WORK_POOL_PER_GROUP=1` and a single message triggers two agents in the same group, the second agent fails with `failed to acquire per-group semaphore: context deadline exceeded` instead of waiting for the first agent to finish and then executing sequentially.

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

## Reproduction Steps
1. Start ACS server with `ACS_AGENT_WORK_POOL_PER_GROUP=1`.
2. Create a group `AGENT013Test`.
3. Add two worker-agents (`worker-1`, `worker-2`) to the group, both using a chat command that sleeps for 30 seconds.
4. Send a message mentioning both agents: `@worker-1 @worker-2 concurrent?`.
5. Observe the results over ~70 seconds.

## Expected Behavior
Per `docs/Environment_Variables.md` and `ORIGIN.md`, when the per-group concurrency limit is reached, messages should be delayed/redelivered via NATS JetStream. The two agents should execute sequentially, with a total elapsed time of approximately 60 seconds (30s + 30s).

## Actual Behavior
- `worker-2` acquires the per-group slot and completes after ~30 seconds.
- `worker-1` fails after ~30 seconds with:
  ```
  failed to acquire work pool slot: failed to acquire per-group semaphore: context deadline exceeded
  ```
- A system error message is created for `worker-1`.
- After NATS redelivery (~30s later), `worker-2` processes the message again and succeeds, while `worker-1` fails again.
- `worker-1` never successfully executes.

## Evidence

### Database output (excerpt)
```
 message_id | sender_id | sender_type | create_at_ms | message_text
------------|-----------|-------------|--------------|--------------
 faa7a738... | acc-... | user | 1782013113941 | @worker-1 @worker-2 concurrent?
 dd90fd9c... | acs-system | manager-agent | 1782013143952 | [System Error] Agent worker-1 failed: failed to acquire work pool slot: failed to acquire per-group semaphore: context deadline exceeded
 2b76b52a... | worker-2 | worker-agent | 1782013143954 | MOCK_AGENT_RESPONSE from worker-2 ... after 30s sleep
 c7ff5c87... | acs-system | manager-agent | 1782013173976 | [System Error] Agent worker-1 failed: ... context deadline exceeded
 a0d6dfdb... | worker-2 | worker-agent | 1782013173976 | MOCK_AGENT_RESPONSE from worker-2 ... after 30s sleep
```

### Server log excerpt
```json
{"level":"WARN","message":"pool acquire timeout","module":"workpool","wait_ms":30007,"error":"failed to acquire per-group semaphore: context deadline exceeded"}
{"level":"ERROR","message":"failed to process agent target","module":"consumer","agent_id":"worker-1","error":"failed to acquire work pool slot: failed to acquire per-group semaphore: context deadline exceeded"}
{"level":"INFO","message":"system error message sent with system identity","module":"consumer","failed_agent":"worker-1"}
```

## Root Cause
The work-pool semaphore acquisition used a hardcoded 30-second timeout. When an agent's chat command takes 30 seconds (or longer), a second agent in the same group timed out before the first agent released the per-group slot. The consumer then treated the timeout as a processing failure and emitted a system error message, rather than negatively acknowledging (Nak) the NATS message for redelivery once the slot became available.

## Fix Applied
1. **New sentinel error** `ErrPoolLimitReached` in `internal/workpool/semaphore.go` wraps the underlying `context.DeadlineExceeded` so callers can distinguish saturation from other failures.
2. **Configurable acquire timeout** `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT` (default `30s`) added to `internal/config/config.go`.
3. **Consumer refactor** in `internal/nats/consumer.go`:
   - `processMessage` no longer holds a single pool slot for the entire pending message.
   - `dispatchTargets` runs agent targets concurrently.
   - `processAgentTarget` acquires per-node/per-user/per-group slots per individual agent invocation.
   - When any slot cannot be acquired, `ErrPoolLimitReached` is returned and the NATS handler calls `msg.Nak()` for JetStream redelivery instead of logging a processing failure.
4. **Unit tests** added in `internal/nats/consumer_test.go`:
   - `TestDispatchTargets_ExecutesConcurrently`
   - `TestDispatchTargets_PropagatesError`
5. **Existing workpool tests** updated to assert `ErrPoolLimitReached` on timeout.

## Verification
- `go test ./...` → PASS
- `make build` → OK

## Status
fixed

## Related Documentation
- `docs/Environment_Variables.md` — AgentWorkPool Configuration
- `docs/API.md` — Agent Triggering / Work-Pool behavior
- `ORIGIN.md` — AgentWorkPool section

## Test Plan Reference
- `docs/cases/TestCase_manual_cli_agent_trigger.md` — AGENT-013
