---
status: fixed
related_task: 20260619T200214.topsailai.1781923903.6951082
---

# Issue: Missing Model Helper Functions for Role/Member/Message Classification

## Description

While implementing unit tests for `internal/models`, several classification helpers required by the API documentation and business logic were found to be missing. These helpers are needed to enforce role hierarchy, member type checks, and message sender classification in a consistent way across the codebase.

## Affected Files

- `internal/models/account.go`
- `internal/models/api_key.go`
- `internal/models/group_member.go`
- `internal/models/group_message.go`

## Changes Made

### `internal/models/account.go`

Added:

- `Account.ValidRole() bool` — returns true for `admin`, `manager`, or `user`.
- `Account.RoleRank() int` — returns numeric rank (`admin=3`, `manager=2`, `user=1`, unknown=0).

### `internal/models/api_key.go`

Added:

- `APIKey.RoleAllowedForOwner(ownerRole AccountRole) bool` — returns true when the API key role does not exceed the owner account role.
- Unexported `roleRank` and `apiKeyRoleRank` helpers.

### `internal/models/group_member.go`

Added:

- `GroupMember.IsManagerAgent() bool`
- `GroupMember.IsUser() bool`

### `internal/models/group_message.go`

Added:

- `GroupMessage.IsFromAgent() bool`

## Verification

- `go test -v -race -count=1 ./internal/models/...` passes.
- `go test -race -count=1 ./...` passes.
- `go vet ./...` passes.
- `go build ./...` passes.
- `internal/models` package coverage remains at 100%.
