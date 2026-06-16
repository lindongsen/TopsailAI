# Issue: group_member.member_status Not Updated During Agent Trigger

> **Issue ID**: member-status-not-updated
> **Category**: Bug Fix / State Transition
> **Status**: Fixed
> **Created**: 2026-06-16
> **Last Updated**: 2026-06-16

----

## Problem Description

The `group_member.member_status` field was not being reliably updated when agents were triggered. According to `ORIGIN.md` section "member_status of group_member":

> 主动更新机制
> 1. 当 agent 被调用时，直接设置为 `processing`；调用结束时，直接设置为 `idle`。

In practice, the status transition was either invisible or not observable by clients in real time.

----

## Root Cause Analysis

### Cause 1: `processing` Status Set Too Early

In `internal/nats/consumer.go` function `processAgentTarget`, the member status was changed to `processing` **before**:
- Agent health check
- Duplicate running record check (`checkAndCreateRunningRecord`)
- Actual agent chat execution

When any of these pre-checks failed, the `defer` immediately reset status to `idle`. The `processing` window could be only a few milliseconds, making it effectively invisible to API polling.

### Cause 2: Missing Real-Time Status Change Events

`internal/nats/publisher.go` only implemented:
- `PublishGroupMemberCreate`
- `PublishGroupMemberDelete`

There was no `PublishGroupMemberModify`. As a result, clients subscribing to group events (`{ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX}.{group_id}`) were never notified when `member_status` changed. Users had to poll the API to observe transitions, and transient transitions were often missed.

### Cause 3: Published Events Carried Stale `member_status`

Even after adding `PublishGroupMemberModify`, the in-memory `agentMember` object was not synchronized with the database update. The published `group_member/modify` event therefore contained the old `member_status` value instead of the new `processing` or `idle` value.

----

## Fix

### 1. `internal/nats/consumer.go`

In `processAgentTarget`:
- Moved `updateMemberStatus(..., processing)` to **after** health check and duplicate running record check succeed.
- Added a `statusSet` flag to track whether `processing` was successfully set.
- The `defer` reset to `idle` only runs when `statusSet` is true, avoiding unnecessary DB writes.
- After each successful status update (`processing` and `idle`), synchronize `agentMember.MemberStatus` in memory and publish a `group_member/modify` event via `PublishGroupMemberModify`.

### 2. `internal/nats/publisher.go`

Added:

```go
func (p *Publisher) PublishGroupMemberModify(member *models.GroupMember) error {
    return p.PublishGroupEvent("group_member", "modify", member.GroupID, member)
}
```

### 3. `internal/api/handlers/group_member.go`

In `UpdateMember`, when `member_status` is changed via `PUT /api/v1/groups/:group_id/members/:member_id`, call `PublishGroupMemberModify` to notify subscribers in real time.

### 4. Tests

- Updated `internal/nats/consumer_test.go` with unit tests covering:
  - Health-check failure: status unchanged, no modify event published
  - Duplicate running record: status unchanged, no modify event published
  - Successful execution: `processing` then `idle` status updates, both with correct `PublishGroupMemberModify` events
- Updated `tests/integration/test_member_status.py`:
  - `test_member_status_processing_then_idle_success` now subscribes to NATS group events and asserts that `group_member/modify` events with `member_status=processing` and `member_status=idle` are received in the correct order when an agent is triggered by a message mention.
  - `test_member_status_modify_event_published` was fixed to use async NATS subscription (`await nats_client.subscribe`) and asserts a `group_member/modify` event is received when status is changed via the API.

----

## Files Changed

| File | Change |
|------|--------|
| `internal/nats/consumer.go` | Reordered status transition, added `statusSet` guard, synchronized in-memory status, published modify events |
| `internal/nats/publisher.go` | Added `PublishGroupMemberModify` |
| `internal/api/handlers/group_member.go` | Publish modify event on API status update |
| `internal/api/handlers/message_trigger_test.go` | Updated mock publisher to implement `PublishGroupMemberModify` |
| `internal/nats/consumer_test.go` | Added/updated status transition unit tests |
| `tests/integration/test_member_status.py` | Added NATS event subscription assertions for consumer-triggered transitions and fixed async subscription handling |

----

## Verification

- `go test ./internal/nats/... -count=1` passed
- `go test ./internal/api/handlers/... -count=1` passed
- `go test ./... -count=1` passed (one transient `internal/discovery` flake passed on rerun)
- Python integration tests for `member_status` should be run separately with the full ACS server, PostgreSQL, and NATS stack.

----

## Related Documents

- `/TopsailAI/src/topsailai_server/agent_community/ORIGIN.md`
- `/TopsailAI/src/topsailai_server/agent_community/docs/API.md`
- `/TopsailAI/src/topsailai_server/agent_community/issues/91critical-issues.md`
