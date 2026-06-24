---
status: open
severity: critical
phase: CLI Manual Testing Phase 6
related_test_cases:
  - CLI-AGENT-001
  - CLI-AGENT-002
  - CLI-AGENT-003
  - CLI-AGENT-004
  - CLI-AGENT-005
  - CLI-AGENT-006
  - CLI-AGENT-007
  - CLI-AGENT-008
  - CLI-AGENT-009
  - CLI-AGENT-010
  - CLI-AGENT-011
  - CLI-AGENT-012
  - CLI-AGENT-013
  - CLI-AGENT-014
  - CLI-AGENT-015
---

# Agent Response Messages Persist but Are Invisible to API

## Summary
After a successful agent trigger (server log reports `"agent processed message successfully"`), the agent's response message is inserted into `group_messages` and visible in PostgreSQL, but it cannot be retrieved through the HTTP API. This blocks all Phase 6 agent-trigger manual test cases that assert on the agent reply.

## Test Case
CLI-AGENT-001 through CLI-AGENT-015 (consolidated plan: `/TopsailAI/src/topsailai_server/agent_community/docs/cases/TestCase_manual_cli_complete.md`).

## Expected Behavior
- `GET /api/v1/groups/{group_id}/messages/{message_id}` should return the agent response message when `message_id` exists in the database.
- `GET /api/v1/groups/{group_id}/messages?limit=N` should include the most recent agent response message.

## Actual Behavior
- Database query confirms the row exists:
  - `message_id = d0763fa3-74b1-48b6-bb37-fe4d844bf8e4`
  - `group_id = <test_group_id>`
  - `sender_id = worker-1`
  - `sender_type = worker-agent`
  - `processed_msg_id = <triggering_user_message_id>`
  - `is_deleted = false`
- `GET /api/v1/groups/{group_id}/messages/d0763fa3-74b1-48b6-bb37-fe4d844bf8e4` returns **404 Not Found**.
- `GET /api/v1/groups/{group_id}/messages?limit=5` returns only the triggering user message and older records; the agent response is omitted.

## Reproduction Steps
1. Start ACS server with manager-agent and worker-agent mock commands configured:
   - `ACS_GROUP_MANAGER_AGENT_CMD_CHAT=/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_chat.sh`
   - Worker member interface `cmd_chat` pointing to `/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_chat.sh`
   - Health/status scripts pointing to `/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_check_health.sh` and `mock_agent_cmd_check_status.sh`
2. Create a group and join a worker-agent member.
3. Send a user message mentioning `@worker-1`.
4. Wait for server log to show successful agent processing with a `response_id`.
5. Query PostgreSQL: `SELECT * FROM group_messages WHERE sender_type = 'worker-agent';` — row exists.
6. Call API:
   - `GET /api/v1/groups/{group_id}/messages/{response_id}` → 404
   - `GET /api/v1/groups/{group_id}/messages?limit=5` → agent response missing

## Evidence
- Server log snippet:
  ```
  agent processed message successfully
  response_id=d0763fa3-74b1-48b6-bb37-fe4d844bf8e4
  ```
- PostgreSQL query result: row present with `sender_type='worker-agent'`, `is_deleted=false`.
- API response: `{"error":"message not found","trace_id":"..."}` (404).

## Suspected Root Cause
The message list/get handlers likely apply a filter that excludes messages with `sender_type` ending in `-agent`, or there is a query-scope bug (e.g., soft-deletion filter, member visibility filter, or sender membership check) that incorrectly excludes agent-generated messages.

## Suggested Fix
Inspect `/TopsailAI/src/topsailai_server/agent_community/internal/api/handlers/message.go` (or equivalent message list/get service) for:
1. Hard-coded exclusion of `sender_type = 'worker-agent'` or `'manager-agent'`.
2. A `sender_id` membership check that fails because the agent member is not treated as a group member.
3. Soft-deletion or status filter that incorrectly marks agent messages as deleted.
4. Query ordering/limit logic that skips the latest row.

## Severity
**Critical** — Agent triggering is a core ACS feature; replies must be visible to clients.

## Blocking
All Phase 6 agent-trigger manual test cases are blocked until this is fixed.

## Verification

status: fixed
fixed_by: AIMember.km3-programmer
fixed_at: 2026-06-23

### Root Cause
1. **GET by ID returned 404** because the route `GET /api/v1/groups/:group_id/messages/:message_id` was never registered in `internal/api/router.go`; no `GetMessage` handler existed.
2. **List endpoint soft-delete consistency** — `ListMessages` relied only on GORM's `deleted_at IS NULL` default scope. Because `DeleteMessage` sets `is_deleted = true` and `delete_at_ms` but does not set `gorm.DeletedAt`, soft-deleted records could still be returned. The fix explicitly adds `is_deleted = false` to both list and get queries.

### Changes Applied
- `internal/api/handlers/message.go`
  - Added `GetMessage` handler with group existence, authorization, and `is_deleted = false` filtering.
  - Updated `ListMessages` query to include `AND is_deleted = ?`.
- `internal/api/router.go`
  - Registered `GET /api/v1/groups/:group_id/messages/:message_id`.
- `internal/api/handlers/message_test.go`
  - `TestGetMessage_AgentMessageVisible`
  - `TestGetMessage_SoftDeletedNotFound`
  - `TestListMessages_IncludesAgentMessages`
  - `TestListMessages_SoftDeletedExcluded`

### Test Output
```
go test -v ./internal/api/handlers/ -run 'TestGetMessage|TestListMessages'
--- PASS: TestGetMessage_AgentMessageVisible
--- PASS: TestGetMessage_SoftDeletedNotFound
--- PASS: TestListMessages_IncludesAgentMessages
--- PASS: TestListMessages_SoftDeletedExcluded
PASS
ok      github.com/topsailai/agent-community/internal/api/handlers

go build ./...
# success
```

### Notes
- The pre-existing failure in `internal/discovery.TestDiscovery_IsLeader` is unrelated to this fix.
- Agent response messages use a plain UUID `message_id` (e.g., `d0763fa3-74b1-48b6-bb37-fe4d844bf8e4`) generated by `uuid.New().String()` in the NATS consumer. The new `GetMessage` endpoint accepts any `message_id` value, so this is not a problem.
