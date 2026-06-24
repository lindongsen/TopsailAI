---
maintainer: AI
status: fixed
labels: bug, auto-trigger, race-condition
---

# Auto-Trigger Pending Record Race Causes Messages to Be Dropped

## Original Observation (Misdiagnosed)
During CLI-AGENT-009 (idle-timeout auto-trigger) it appeared that the manager-agent response message had a `processed_msg_id` set to a UUID instead of the original user message ID. Further investigation showed this was a misdiagnosis.

## Actual Root Cause
The auto-trigger path in `internal/nats/auto_trigger.go` published the pending NATS message **before** inserting the `pending` record into `agent_message_processing`. This created a race condition:

1. Auto-trigger publishes `acs.group.pending-message.{group_id}`.
2. A consumer receives the message and calls `checkAndCreateRunningRecord`.
3. The consumer first tries `UPDATE agent_message_processing SET status='running' WHERE ... AND status='pending'`.
   - If the auto-trigger has not yet committed the `pending` record, this UPDATE matches 0 rows.
4. The consumer falls back to `INSERT` a new `running` record.
   - If the auto-trigger commits the `pending` record between steps 3 and 4, the INSERT violates the unique index on `(group_id, message_id, agent_id)`.
5. The consumer treats the unique-key error as a duplicate and skips processing.
6. The auto-trigger's `pending` record remains stuck in `pending` status forever, and no agent response is produced.

## Fix
1. In `internal/nats/auto_trigger.go`, create the `pending` `agent_message_processing` record **before** publishing the pending message.
2. If publishing fails after the record is created, the pending record is deleted so the message-agent pair can be retried.
3. Duplicate-key errors during pending-record creation are treated as already-in-flight and skipped cleanly.
4. In `internal/nats/consumer.go`, `checkAndCreateRunningRecord` now first attempts to upgrade an existing `pending` record to `running`; only if no pending record exists does it insert a new `running` record.

## Tests Added/Updated
- `internal/nats/auto_trigger_test.go`
  - `TestCheckGroup_ProcessingRecordCreateError`: verifies no publish when pending record cannot be created.
  - `TestCheckGroup_PublishFailureRollsBackPendingRecord`: verifies pending record is removed on publish failure.
  - `TestCheckGroup_PendingRecordExistsBeforePublish`: verifies the pending record exists before `PublishAutoTriggerPendingMessage` is called.
- `internal/nats/consumer_duplicate_test.go`
  - `TestCheckAndCreateRunningRecord_PendingRecord_ClaimsRunning`: verifies a pre-existing pending record is upgraded to running.
  - `TestCheckAndCreateRunningRecord_ConcurrentPendingClaim`: verifies only one of many concurrent consumers can claim the same pending record.

## Verification
- `make build-server`: PASS
- `go test ./internal/nats/...`: PASS

## Affected Files
- `internal/nats/auto_trigger.go`
- `internal/nats/auto_trigger_test.go`
- `internal/nats/consumer.go`
- `internal/nats/consumer_duplicate_test.go`

## Notes
- This issue is **not** related to `processed_msg_id` being a UUID.
- No soft-delete changes for `groups` or `group_member` per user directive.
