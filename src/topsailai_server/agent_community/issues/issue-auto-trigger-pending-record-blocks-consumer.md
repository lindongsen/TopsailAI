---
maintainer: AI
status: open
assignee: km3-programmer
---

# Issue: Auto-trigger pending record blocks consumer from processing the message

## Summary
When the auto-trigger periodic task detects an idle-timeout condition, it inserts a `pending` record into `agent_message_processing` and publishes the pending message to NATS. The consumer then tries to INSERT a `running` record with the same `(group_id, message_id, agent_id)` tuple, which fails due to the unique index. The consumer interprets the duplicate-key error as "already processing" and skips the message permanently. Because the `pending` record persists, all future auto-trigger scans also skip the message, so the manager-agent never responds.

## Affected Components
- `internal/nats/auto_trigger.go` — creates `pending` record before publishing.
- `internal/nats/consumer.go` — `checkAndCreateRunningRecord` only INSERTs, never updates an existing `pending` record.

## Steps to Reproduce
1. Create a group with one user and one manager-agent.
2. Send a plain message from the user.
3. Wait for the idle timeout (`ACS_AGENT_AUTO_TRIGGER_TIMEOUT`) plus one auto-trigger interval (`ACS_AUTO_TRIGGER_INTERVAL_SECONDS`).
4. Observe server logs:
   - `auto-trigger published pending message`
   - `agent health check failed` or `agent already processing this message, skipping duplicate`
5. Query `agent_message_processing`:
   ```sql
   SELECT * FROM agent_message_processing WHERE group_id = '<group_id>' AND message_id = '<msg_id>';
   ```
   A row with `status = 'pending'` exists and is never updated.

## Expected Behavior
The consumer should treat an existing `pending` record as a reservation that it owns, update it to `running`, and proceed with agent invocation. The unique index should still protect against true concurrent duplicates.

## Actual Behavior
The consumer INSERT fails with a unique-key violation, logs a warning, and returns `nil`. The message is acknowledged (or dropped in no-ack mode), and the agent never runs.

## Proposed Fix
Modify `checkAndCreateRunningRecord` in `internal/nats/consumer.go` to:
1. First attempt to update an existing record with `status = 'pending'` to `status = 'running'` for the same `(group_id, message_id, agent_id)`.
2. If the update affects 0 rows, fall back to the current INSERT behavior.
3. Return `(true, nil)` when either the update or the INSERT succeeds.

This keeps the unique-index guard against cross-consumer races while allowing the auto-trigger's `pending` reservation to be claimed by the consumer.

## Related Code
- `internal/nats/consumer.go:390-416`
- `internal/nats/auto_trigger.go:289-299`

## Notes
- This issue was discovered during manual CLI test `CLI-AGENT-009`.
- User directive: NO NEED SOFT-DELETE for table `groups` and `group_member`; this issue is unrelated to soft-delete.
