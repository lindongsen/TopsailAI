---
status: fixed
priority: high
labels:
  - bug
  - permissions
  - agent-trigger
  - race-condition
related_test_plan: docs/cases/TestCase_manual_cli_agent_trigger.md
---

# Issue: Group owner cannot update agent member_interface; duplicate agent processing race

## Summary
During manual execution of `TestCase_manual_cli_agent_trigger.md` (steps AGENT-013 through AGENT-016), two blockers were encountered that prevent non-admin users from configuring agents in their own groups and that cause unstable agent triggering when multiple worker agents are mentioned.

## Environment
- ACS server built from latest `main` (post work-pool and default-key fixes).
- Database: SQLite (`ACS_DATABASE_DRIVER=sqlite`).
- NATS: local single-node (`nats://localhost:4222`).
- Server port: `7370`.
- Test account: `UserA` (role `user`), owner of group `AgentTriggerGroup`.

## Blocker 1: Group owner cannot update agent `member_interface`

### Reproduction steps
1. Create a `user` account `UserA` and an API key.
2. As `UserA`, create a group `AgentTriggerGroup`.
3. As `UserA`, join a worker-agent member with a minimal `member_interface`.
4. As `UserA`, call `PUT /api/v1/groups/{group_id}/members/{agent_id}` with an updated `member_interface` containing `cmd_check_health`, `cmd_check_status`, and `cmd_chat` scripts.

### Expected behavior
The group owner (`UserA`) should be able to update the agent member's interface, because the owner manages agents in their own group.

### Actual behavior
Server returns HTTP `403 Forbidden` with an error such as:
```json
{"error":"forbidden"}
```
Only an `admin` API key can successfully update the agent member interface.

### Impact
Non-admin manual test scenarios (and real-world group owners) cannot reconfigure agent commands after the agent has been joined, forcing all agent-trigger tests to use `admin` credentials and contradicting the documented group-owner permission model.

## Blocker 2: Duplicate agent processing / running-record race

### Reproduction steps
1. Configure health/status/chat scripts for three worker agents in `AgentTriggerGroup`.
2. Send a message mentioning all three worker agents, e.g.:
   ```
   @agent-a @agent-b @agent-c please summarize the latest docs
   ```
3. Observe NATS pending-message processing and resulting group messages.

### Expected behavior
- Each mentioned worker agent is invoked exactly once.
- A single running record is created per `(group_id, message_id, agent_id)`.
- Agent responses are added once per agent.

### Actual behavior
- Multiple responses per agent appear in the group.
- Server logs contain repeated errors:
  ```
  [System Error] failed to check and create running record
  ```
- This indicates concurrent NATS deliveries are not being fully deduplicated, or the `checkAndCreateRunningRecord` logic has a race window that allows two workers to pass the existence check simultaneously.

### Impact
Agent triggering is unreliable: agents may process the same message multiple times, producing duplicate responses and potentially consuming extra work-pool slots.

## Root causes

1. **Member update authorization:** `canUpdateMember` in `internal/api/handlers/group_member.go` only allowed `admin` or the member's own account to update a member record. It did not grant the group `owner_id` permission to update members in the group they own.

2. **Duplicate processing race:** `checkAndCreateRunningRecord` in `internal/nats/consumer.go` first queried for an existing record and then inserted a new one. Two concurrent NATS deliveries could both observe "no record" and both insert, leading to duplicate processing and repeated error logs.

## Fixes applied

1. **Member update authorization:**
   - Updated `canUpdateMember` in `internal/api/handlers/group_member.go` to allow the group `owner_id` (in addition to `admin`) to update any member record in that group.
   - Regular users still may only update their own member record.

2. **Duplicate processing guard:**
   - Added a unique composite index on `agent_message_processing(group_id, message_id, agent_id)` in `internal/models/agent_processing.go`.
   - Refactored `checkAndCreateRunningRecord` in `internal/nats/consumer.go` to insert the running record directly inside a transaction and treat a unique-constraint violation as "already exists" (returns `created=false, err=nil`).
   - This closes the race window: the database enforces a single record per `(group_id, message_id, agent_id)` pair.

3. **Tests:**
   - Updated `internal/nats/consumer_duplicate_test.go`:
     - `TestCheckAndCreateRunningRecord_CompletedRecord` now asserts that a completed record prevents re-processing and that only one record exists.
     - `TestCheckAndCreateRunningRecord_Concurrent` uses a file-backed SQLite database with WAL mode and a single connection pool to reliably verify that exactly one goroutine creates the record.
   - Existing handler tests still pass; the group-owner update path is covered by the manual test plan AGENT-013.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./...
make build
```

Results:
- `go test ./...` — all packages pass.
- `make build` — server, CLI, and natsctl build successfully.

## Files changed
- `internal/api/handlers/group_member.go`
- `internal/models/agent_processing.go`
- `internal/nats/consumer.go`
- `internal/nats/consumer_duplicate_test.go`

## Test plan references
- `docs/cases/TestCase_manual_cli_agent_trigger.md`
  - AGENT-013: Multiple groups in parallel
  - AGENT-014: Mock agent reply delays
  - AGENT-015: Multiple worker-agents without manager-agent
  - AGENT-016: Per-group work-pool concurrency

## Next step
Re-run agent-trigger manual tests starting from **AGENT-013**. If all steps pass, update `.task/Test_Execution_Checklist.md` and mark all manual test plans complete.
