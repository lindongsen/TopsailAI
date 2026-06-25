---
status: fixed
severity: medium
phase: Code Review
related_test_cases:
  - API-MESSAGE-LIST-001
  - API-MESSAGE-LIST-002
  - API-MESSAGE-LIST-003
---

# List Messages: Only Admin May Query Deleted Messages

## Summary
The `ListMessages` handler in `internal/api/handlers/message.go` previously excluded soft-deleted messages (`is_deleted = true`) for all callers. The requirement is to allow **only admin** callers to retrieve deleted messages, and only when they **explicitly** request it via a query parameter.

## Expected Behavior
- `GET /api/v1/groups/:group_id/messages` (no `include_deleted`) excludes soft-deleted messages for all roles.
- `GET /api/v1/groups/:group_id/messages?include_deleted=true` returns soft-deleted messages **only** when the caller is `admin`.
- Non-admin callers who explicitly pass `include_deleted=true` receive `403 Forbidden`.

## Actual Behavior (Before Fix)
- Soft-deleted messages were always excluded regardless of caller role or query parameters.
- There was no way for an admin to audit or inspect deleted messages through the API.

## Changes Applied

### `internal/api/handlers/message.go`
- Added parsing of the `include_deleted` query parameter (`true`/`1`).
- Rejected non-admin callers with `403 Forbidden` when `include_deleted=true` is requested.
- Default query continues to filter `is_deleted = false`.
- When an admin explicitly requests `include_deleted=true`, the `is_deleted` filter is removed so all group messages are returned.

### `internal/api/handlers/message_test.go`
- Renamed `TestListMessages_SoftDeletedExcluded` to `TestListMessages_SoftDeletedExcludedByDefault` and extended it to verify:
  - Non-admin default request excludes deleted messages.
  - Admin request with `include_deleted=true` returns both visible and deleted messages.
- Added `TestListMessages_NonAdminCannotIncludeDeleted` to verify `403 Forbidden` for non-admin callers.
- Added `TestListMessages_AdminWithoutIncludeDeletedExcludesDeleted` to verify admin default behavior still excludes deleted messages.

### `docs/API.md`
- Documented the new `include_deleted` query parameter under `GET /api/v1/groups/:group_id/messages`.
- Added the `403 Forbidden` response description for non-admin callers.

### `ORIGIN.md`
- Added a note under the `group_messages` table section clarifying that only admins can query deleted messages by explicit parameter.
- Updated the `NO_TRIGGER_CASES` sliding-window rule to exclude deleted messages from the 20-message window.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/... -count=1
```

Output:
```
ok  	github.com/topsailai/agent-community/internal/api/handlers	2.562s
```

## Fixed By
- fixed_by: AIMember.km3-programmer
- fixed_at: 2026-06-25
