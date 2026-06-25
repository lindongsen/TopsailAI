---
status: done
severity: high
component: trigger-evaluation / message-processing
related_test: docs/cases/TestCase_manual_cli_agent_trigger.md
related_step: AGENT-011
---

# Issue: Message with `processed_msg_id` still triggers agent via mention

## Summary
A message created via the API with an explicit, non-empty `processed_msg_id` is still being evaluated for agent triggers. When the message text also contains a mention of a worker-agent, the agent is invoked, violating the documented **NO_TRIGGER_CASES** rule #2.

## Environment
- Project: AI-Agent Community Server (ACS)
- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Build: `acs-server` built from latest source after concurrency fix approval
- Database: PostgreSQL (existing test instance)
- Message bus: NATS with JetStream
- CLI: `acs-cli` running inside tmux session `acs-agent`
- Authentication: System Admin API key from freshly generated `ACS_ACCOUNT_ADMIN_API_KEY.acs`

## Reproduction Steps
1. Start PostgreSQL, NATS, and `acs-server`.
2. Authenticate as System Admin via `acs-cli`.
3. Create a group `trigger-test`.
4. Join a worker-agent `worker-2` with a mock chat command that sleeps for 3 seconds and then echoes a reply.
5. Send a normal user message, e.g. `hello`, and note its `message_id` (call it `msg-base`).
6. Create a second message via the API with:
   - `message_text`: `"reply to @worker-2 with processed_msg_id"`
   - `processed_msg_id`: `<msg-base>`
7. Observe that `worker-2` is invoked and eventually posts a reply message.

## Expected Behavior
Per `docs/API.md` and `ORIGIN.md` **NO_TRIGGER_CASES**:

> A message will **not** be automatically triggered when ... The message has a non-empty `processed_msg_id`.

Therefore, the message created in step 6 should **not** produce a pending message, should **not** invoke `worker-2`, and should appear in the group history as a plain user message with no agent reply.

## Actual Behavior
`worker-2` was triggered. A new agent reply message appeared in the group history with:
- `sender_id`: `worker-2`
- `sender_type`: `worker-agent`
- `processed_msg_id`: the ID of the message created in step 6

This confirms that the trigger evaluator processed the mention before checking `processed_msg_id`, or the `NO_TRIGGER_CASES` guard is missing/skipped for mention triggers.

## Impact
- Breaks the contract for `processed_msg_id`.
- Can cause unwanted agent replies and potential infinite loops if agent-generated messages are later marked with `processed_msg_id`.
- Blocks completion of `TestCase_manual_cli_agent_trigger.md` (testing stopped at AGENT-011).

## Suggested Fix
In the trigger evaluation path (likely `internal/trigger/` or the message creation handler), check `NO_TRIGGER_CASES` **before** resolving mentions or auto-triggers. Specifically, if `processed_msg_id` is non-empty, skip trigger evaluation entirely and do not publish a pending message.

## Verification After Fix
Re-run `AGENT-011` from `docs/cases/TestCase_manual_cli_agent_trigger.md`:
- The message with non-empty `processed_msg_id` and a mention should **not** trigger the agent.
- No agent reply should appear.
- Then continue with AGENT-010, AGENT-012, and AGENT-013.

## Fix Summary (added by programmer)

### Root Cause
The trigger evaluator (`internal/trigger/evaluator.go`) already returned `ShouldTrigger=false` when `ProcessedMsgID != ""`. However, the manual test `AGENT-011` sent `processed_msg_id` in the API request body, which the `CreateMessageRequest` struct does not expose. The field was silently dropped, so the created message had an empty `processed_msg_id` and triggered normally.

### Fix Applied
1. **Defense-in-depth guard in handler**: Added an explicit early return in `MessageHandler.evaluateAndTrigger` when `msg.ProcessedMsgID != ""`, before calling the evaluator or publisher. This ensures no pending message can be published regardless of evaluator behavior.
2. **Unit tests**:
   - `TestEvaluateAndTrigger_ProcessedMsgIDBlocksTrigger` — uses a mock evaluator that claims the message should trigger; verifies the handler guard suppresses publication.
   - `TestCreateMessage_NoTriggerForProcessedMsgID` — verifies the real evaluator also suppresses trigger for processed messages.

### Verification
- `go test ./internal/api/handlers/... -run 'TestEvaluateAndTrigger_ProcessedMsgIDBlocksTrigger|TestCreateMessage_NoTriggerForProcessedMsgID' -v` → PASS
- `go test ./...` → PASS
- `make build` → OK

### Note for Manual Testing
`AGENT-011` should be updated to set `processed_msg_id` via a direct database update or by creating the message through a code path that populates it (e.g., agent result messages), because the public `POST /api/v1/groups/:group_id/messages` endpoint intentionally does not accept `processed_msg_id` from clients.
