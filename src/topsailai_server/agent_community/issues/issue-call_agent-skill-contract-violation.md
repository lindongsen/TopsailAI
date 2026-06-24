# Issue: call_agent skill contract violated by ACS server message creation

## Status
**Closed** — Server-side implementation merged, unit tests passing, and manual skill tests verified.

## Summary
The `agent_community_client` skill (`call_agent.py`) expects to send a message with explicit `sender_id`, `sender_type`, and `processed_msg_id` fields. The ACS server previously derived `sender_id`/`sender_type` from the authenticated caller and ignored `processed_msg_id` in the request body. This broke the skill contract documented in `/TopsailAI/src/topsailai_server/agent_community/skills/agent_community_client.md`.

## Decision
Adopt **Option A**: Extend `POST /api/v1/groups/{group_id}/messages` to accept caller-provided `sender_id`, `sender_type`, and `processed_msg_id`.

## Validation Rules

### `sender_id` / `sender_type`
- Both fields are optional. When omitted, the server keeps the existing behavior: derives `sender_id` from the authenticated account and sets `sender_type = user`.
- When provided:
  - Both must be provided together; otherwise return `400 Bad Request`.
  - The caller must be a member of the target group; otherwise return `403 Forbidden`.
  - The requested `sender_id` must identify an existing member of the target group; otherwise return `400 Bad Request`.
  - The requested `sender_type` must match the member's actual `member_type`; otherwise return `400 Bad Request`.
  - The requested sender is authorized only when **either**:
    - It matches the caller's own group member record (`member_id` and `member_type` both match), **or**
    - The requested member's `member_type` is `manager-agent`.
  - Otherwise return `403 Forbidden`.

### `processed_msg_id`
- Optional; empty or omitted means the new message has no parent message.
- When provided:
  - The referenced message must exist in the **same group**; otherwise return `400 Bad Request`.
  - The referenced message must not be soft-deleted (`is_deleted = false`); otherwise return `400 Bad Request`.
  - The referenced message must not be the new message itself (self-reference); otherwise return `400 Bad Request`.

### Trigger Behavior
- Messages with a non-empty `processed_msg_id` are never auto-triggered (defense-in-depth guard in the handler).
- Such messages can still be triggered manually via `POST /api/v1/groups/{group_id}/messages/{message_id}/trigger`.

## Files Involved
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/handlers/message.go` — implementation
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/handlers/message_test.go` — unit tests
- `/TopsailAI/src/topsailai_server/agent_community/skills/agent_community_client/scripts/call_agent.py` — skill script (no changes required if server contract is fixed)
- `/TopsailAI/src/topsailai_server/agent_community/skills/agent_community_client.md` — skill documentation

## Implementation Notes
- `CreateMessageRequest` extended with `sender_id`, `sender_type`, and `processed_msg_id`.
- Added `validateProcessedMsgID` helper for parent-message validation.
- Added `resolveSenderIdentity` helper for sender override authorization.
- Added handler-level guard in `evaluateAndTrigger` to skip messages that already have `processed_msg_id`.

## Test Coverage

### Unit Tests
- [x] Backward compatibility: omitting new fields uses auth-derived sender.
- [x] Caller sends as their own group member (user type) with `processed_msg_id`.
- [x] Caller sends as their own group member (worker-agent type).
- [x] Caller sends on behalf of a manager-agent member.
- [x] Caller tries to send as another user member → 403.
- [x] Caller tries to send as another worker-agent member → 403.
- [x] Caller is not a group member and tries sender override → 403.
- [x] `processed_msg_id` references non-existent message → 400.
- [x] `processed_msg_id` references deleted message → 400.
- [x] `processed_msg_id` references message in another group → 400.
- [x] `processed_msg_id` blocks automatic trigger.

### Manual Skill Tests (Post-Fix)
- [x] Happy path: `call_agent.py` sends as worker-agent, triggers target worker-agent, receives reply.
- [x] Contract verified: sent message has `sender_id=ACS_AGENT_ID`, `sender_type=ACS_AGENT_TYPE`, `processed_msg_id=ACS_MESSAGE_ID`.
- [x] Timeout behavior when target agent does not reply within `ACS_AGENT_TIMEOUT`.
- [x] User member can use `call_agent.py` to send as themselves and trigger an agent.
- [x] User member can send on behalf of a manager-agent member and trigger an agent.
- [x] Impersonation of another worker-agent member is rejected with 403.
- [x] Non-member caller attempting sender override is rejected with 403.

## Manual Test Artifacts
- Setup log: `/tmp/acs_manual_test/setup.log`
- Happy-path log: `/tmp/acs_manual_test/call_agent_happy2.log`
- Verification log: `/tmp/acs_manual_test/verify_happy.log`
- Timeout log: `/tmp/acs_manual_test/call_agent_timeout.log`
- User-member log: `/tmp/acs_manual_test/call_agent_user.log`
- Manager-agent log: `/tmp/acs_manual_test/call_agent_manager.log`
- Impersonation log: `/tmp/acs_manual_test/test_impersonation.log`
- Server log: `/tmp/acs_manual_test/server.log`
- Test config: `/tmp/acs_manual_test/test_config.json`

## Suggested Fix (Historical)
Option A (preferred): Update `CreateMessageRequest` in `internal/api/handlers/message.go` to include `sender_id`, `sender_type`, and `processed_msg_id`, and use them when provided by trusted callers. **Implemented and verified.**

Option B: Update skill doc and `call_agent.py` to remove the `processed_msg_id` requirement and adapt to server-derived sender fields. **Not needed.**
