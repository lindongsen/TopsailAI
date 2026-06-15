# Issue: Manual Trigger API for Messages

**Status:** Done

**Date:** 2026-06-15

---

## Description

Support an API interface to actively trigger specific messages, bypassing `NO_TRIGGER_CASES` restrictions.

Previously, agent triggering was fully automatic and governed by `NO_TRIGGER_CASES` in `internal/trigger/evaluator.go`:
1. Sender type is `xxx-agent`
2. `processed_msg_id` has a value
3. A sliding window of 20 messages contains >10 consecutive `xxx-agent` messages

There was no way for a client (human or system) to force agent processing on a message that fell into one of these excluded categories. This feature adds a manual trigger endpoint that reuses the existing NATS pending-message pipeline while skipping the `NO_TRIGGER_CASES` checks.

---

## Changes Made

### 1. `internal/api/handlers/message.go`

Added `TriggerMessage` handler method to handle `POST /api/v1/groups/:group_id/messages/:message_id/trigger`.

Key behaviors:
- Validates group exists and is not deleted
- Validates message exists and belongs to the group
- If `agent_id` is specified in request body, validates the agent is a member of the group with type ending in `-agent`
- Builds `TriggerInfo{Type: "manual", AgentID: targetAgentID}`
- Publishes pending message directly via NATS, bypassing `Evaluate()` and `NO_TRIGGER_CASES`
- Returns `202 Accepted` with trigger details

### 2. `internal/api/router.go`

Added route registration:
```go
messageGroup.POST("/:message_id/trigger", messageHandler.TriggerMessage)
```

### 3. `docs/API.md`

Documented the new endpoint with:
- Description explaining bypass of `NO_TRIGGER_CASES`
- Path parameters (`group_id`, `message_id`)
- Optional request body with `agent_id`
- Response `202 Accepted` example
- Error responses: `404` (group/message/agent not found), `400` (non-agent member), `500` (database/NATS failure)
- Updated Create Message section to reference the new trigger endpoint

### 4. `internal/api/handlers/message_trigger_test.go`

Added 10 unit tests covering:
- Manual trigger with `agent_id` → 202
- Manual trigger without `agent_id` → 202
- Non-existent group → 404
- Non-existent message → 404
- Non-existent `agent_id` → 404
- Non-agent member_id → 400
- Agent-sent message bypasses NO_TRIGGER_CASES → 202
- Processed message bypasses NO_TRIGGER_CASES → 202
- NATS publish error → 500
- No agents in group → 202 (no-op at consumer)

All tests pass: `ok github.com/topsailai/agent-community/internal/api/handlers 0.047s`

### 5. `tests/integration/test_api.py`

Added `TestManualTrigger` class with 7 integration test cases covering all required scenarios. Tests are written but blocked from execution due to missing infrastructure (PostgreSQL, NATS, ACS server not running). Tracked in `issues/undo/issue-manual-trigger-integration-test-blocked.md`.

---

## Design Decisions

- The manual trigger **does not** call `Evaluate()`. It directly publishes to NATS, ensuring `NO_TRIGGER_CASES` are ignored.
- If `agent_id` is omitted, the handler calls `ResolveAgents()` to let the system decide target agent(s) naturally.
- `TriggerInfo.Type = "manual"` allows the consumer to distinguish manual triggers from automatic ones for logging, metrics, or future policy differences.
- NATS JetStream `MsgID` deduplication (`{message_id}:{agent_id}`) prevents duplicate processing if the same manual trigger is issued twice.

---

## Related Files

- `.task/Code_Improvement_Proposal.md` — Original proposal by km2-reviewer
- `issues/undo/issue-manual-trigger-integration-test-blocked.md` — Integration test blocker

---

## Verification

- [x] Code implemented
- [x] Unit tests pass
- [x] API documentation updated
- [x] Integration tests written
- [ ] Integration tests executed (blocked by infrastructure)
