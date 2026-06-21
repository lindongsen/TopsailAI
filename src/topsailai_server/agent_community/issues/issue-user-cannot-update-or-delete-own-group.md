---
maintainer: AI
status: fixed
---

# Issue: User Cannot Update or Delete Own Group

## Summary
A user account that creates a group cannot subsequently update or delete that group. The server returns `403 Forbidden` even though the API documentation states that a `user` can update and delete groups they own.

## Reproduction Steps
1. Start the ACS server with a fresh database.
2. Create a user account and obtain an API key or session key for it.
3. Authenticate as the user and create a group via `POST /api/v1/groups`.
4. Attempt to update the group via `PUT /api/v1/groups/:group_id`.
5. Attempt to delete the group via `DELETE /api/v1/groups/:group_id`.

## Expected Behavior
- `PUT /api/v1/groups/:group_id` returns `200 OK` and updates the group.
- `DELETE /api/v1/groups/:group_id` returns `204 No Content` and deletes the group.

## Actual Behavior
Both endpoints return `403 Forbidden` with body `{"error":"forbidden"}`.

## Root Cause
`internal/api/handlers/group.go` `CreateGroup` builds the `models.Group` struct without setting `CreatorID` and `OwnerID`. The `UpdateGroup` and `DeleteGroup` handlers check `group.OwnerID != authCtx.Account.AccountID`, but because `OwnerID` is empty, the comparison always fails for non-admin callers.

## Environment
- ACS commit: current `main`
- Go version: 1.25
- Database: PostgreSQL (also reproducible with SQLite)

## Fix
- Updated `internal/api/handlers/group.go` `CreateGroup` to populate `CreatorID` and `OwnerID` with the authenticated account's `account_id`.
- Added assertions in `internal/api/handlers/group_test.go` `TestCreateGroupAutoJoinsManagerAgent` to verify `CreatorID` and `OwnerID` are persisted.
- Ran `go test ./internal/api/handlers/... ./internal/services/... ./cmd/cli/...` — all pass.
- Ran `make build` — server, CLI, and natsctl build successfully.
