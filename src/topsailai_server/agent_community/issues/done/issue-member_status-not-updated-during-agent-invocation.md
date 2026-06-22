---
maintainer: AI
status: resolved
---

# Issue: group_member.member_status not updated during agent invocation

## Description

Integration tests `test_member_status_processing_then_idle_success` and `test_member_status_idle_after_agent_failure` in `tests/integration/test_member_status.py` failed because the agent member's `member_status` was never observed as `"processing"` during agent execution, nor did it return to `"idle"` afterward.

The diagnostic test in the same file proved that the agent invocation path itself worked end-to-end (message parsed, pending message consumed, mock agent invoked, response message created).

## Root Cause

The server source code in `internal/nats/consumer.go` already implements the required status transitions:

- `processAgentTarget` calls `updateMemberStatus(..., MemberStatusProcessing, ...)` before invoking the agent.
- A deferred call resets the status to `MemberStatusIdle` after the agent call completes.

The failure was caused by a **stale `bin/acs-server` binary** running in the background. The running server process predated the current source code that contains the status-transition logic. Running `pytest` directly against the stale server reproduced the failure; restarting the server from the freshly built binary made the tests pass.

## Fix

1. Rebuilt the server binary with `make build-server`.
2. Updated `tests/integration/manage_test_server.sh` to:
   - Always stop any existing server on the test port before starting a new one.
   - Run `make build-server` before each test run so integration tests execute against the current source code.
   - Redirect server stdout/stderr to `tests/integration/.tmp/acs-server.log` for easier debugging.

No changes were required in `internal/nats/consumer.go` or other server packages.

## Verification

```text
$ bash tests/integration/manage_test_server.sh -v tests/integration/test_member_status.py
============================== 5 passed in 17.04s ==============================
```

All five member-status integration tests pass consistently.

## Files Modified

- `tests/integration/manage_test_server.sh`

## Files Not Modified

- `internal/nats/consumer.go` (already correct)
- `internal/models/group_member.go` (already correct)
- `tests/integration/test_member_status.py` (test expectations already correct)
