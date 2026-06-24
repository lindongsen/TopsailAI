---
status: done
fix_date: 2026-06-23
---
# Group Member Re-Add After Soft-Delete Returns 500

## Symptom
Re-adding a member who previously left a group returned HTTP 500 due to a unique-constraint violation on `group_member_pkey`.

## Root Cause
`JoinGroup` in `internal/api/handlers/group_member.go` used `h.db.Where(...)` to look for an existing member. Soft-deleted rows are excluded by default, so the handler attempted to insert a new row with the same `(group_id, member_id)` primary key, causing the database to reject it.

## Fix
- Use `h.db.Unscoped()` to include soft-deleted rows when checking for an existing member.
- If an existing row is found and `DeletedAt.Valid` is true, restore it by clearing `deleted_at` and applying the new fields from the request (`member_name`, `member_description`, `member_type`, `member_interface`, `member_status=online`, `update_at_ms`).
- If the row is not soft-deleted, return `409 Conflict` as before.
- If no row exists, insert a new member as before.
- Publish a `group_member` create event after restoring.

## Files Changed
- `internal/api/handlers/group_member.go`
- `internal/api/handlers/group_member_test.go`
- `internal/discovery/discovery_test.go` (flaky test stabilization)

## Tests Added
- `TestJoinGroup_RestoresSoftDeletedMember`
- `TestJoinGroup_SelfJoinRestoresSoftDeletedMember`

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -count=1 ./...
go build ./...
```
All packages passed.

## Severity
High — blocked any member from rejoining a group after leaving.
