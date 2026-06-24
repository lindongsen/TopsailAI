----
status: fixed
priority: medium
component: agent-trigger
----

# Issue: Multiple worker-agent mentions execute sequentially instead of concurrently

## Summary
When a user message mentions multiple worker-agents and no manager-agent is present, the documentation states that all mentioned agents should be invoked concurrently. In practice, the agents executed sequentially, with each agent waiting for the previous one to complete.

## Environment
- ACS server: built from `/TopsailAI/src/topsailai_server/agent_community` at 2026-06-21
- Go version: 1.25
- PostgreSQL: running on localhost:5432
- NATS: running on localhost:4222 with JetStream
- AgentWorkPoolPerNode: 10
- AgentWorkPoolPerUser: 5
- AgentWorkPoolPerGroup: 5

## Reproduction Steps
1. Start ACS server with default work-pool settings.
2. Create a group with only a user member and two worker-agent members (`worker-1`, `worker-2`).
3. Configure each worker-agent `member_interface` to use a chat command that sleeps for 3 seconds before replying:
   - `cmd_chat`: `/tmp/acs-agent-test/scripts/mock_agent_cmd_chat_sleep.sh`
   - environment `MOCK_DELAY=3`
4. Send a message mentioning both agents: `@worker-1 @worker-2 solve this together`.
5. Wait and list messages.

## Expected Behavior
Both worker-agents should be invoked concurrently. With a 3-second sleep per agent, both replies should appear within ~3–4 seconds of the original message.

## Actual Behavior (before fix)
The agents replied sequentially:
- Original message timestamp: `1782005510463`
- `worker-1` reply timestamp: `1782005513472` (~3 seconds later)
- `worker-2` reply timestamp: `1782005516483` (~6 seconds later)

The ~3-second gap between replies matched the configured `MOCK_DELAY`, indicating the second agent did not start until the first agent finished.

## Root Cause
`Consumer.processMessage` in `internal/nats/consumer.go` iterated over trigger targets with a sequential `for` loop calling `processAgentTarget`, serializing all agent executions for a single pending message.

## Fix
Refactored the target loop in `internal/nats/consumer.go` to dispatch each target in its own goroutine and wait on a `sync.WaitGroup`. This preserves per-target error handling and system-error-message fallback while allowing multiple worker-agent mentions to run in parallel. AgentWorkPool limits are still enforced inside `processAgentTarget`.

## Verification
- `go test ./...` passed.
- `make build` succeeded.
- Manual re-test pending by tester.

## References
- `docs/API.md` — Agent Triggering section: "Multiple agent mentions without manager-agent: All mentioned agents are invoked concurrently"
- `ORIGIN.md` — trigger via mentions section: "mentions 有多个member时...不存在 manager-agent，可以并发调用"
- `docs/cases/TestCase_manual_cli_agent_trigger.md` — AGENT-003

## Review Follow-up

During re-review the following additional items were addressed:

1. **Stable concurrency unit test under `-race`.** `TestProcessMessage_MultipleWorkerAgents_ExecuteConcurrently` was updated to use a stub `processAgentTarget` hook so it proves goroutine-level concurrency without relying on concurrent SQLite writes. It passes `go test ./internal/nats/... -race -count=10`.
2. **Data race on shared `members` slice.** `dispatchTargets` now passes a copy of each target `models.GroupMember` into its goroutine; status mutations use the copied IDs.
3. **AgentWorkPool limit semantics.** Added code comments in `processMessage` documenting that one pending message with N targets may consume up to N per-user and N per-group slots, and updated `docs/Environment_Variables.md` to clarify that limits are enforced per active agent invocation.
4. **Goroutine safety of shared dependencies.** Added comments in `processMessage` noting that `contextBuilder`, `publisher`, `executor`, and `db` must be safe for concurrent use by design.
5. **Pre-existing flaky race test.** `TestCheckAndCreateRunningRecord_Concurrent` in `internal/nats/consumer_duplicate_test.go` was stabilized by switching from `file::memory:?cache=shared` to a unique file-backed SQLite database per test run (`t.TempDir()` + WAL + busy timeout), eliminating state leakage across `-count=N` iterations.

## Final Verification

```bash
go test ./internal/nats/... -race -count=10   # PASS
go test ./...                                   # PASS
make build                                      # OK
```
