---
status: done
priority: medium
component: api
---
# API: member_interface accepted as object in request body but documented as JSON string

## Summary
The API documentation describes `member_interface` as a JSON object, while the database schema and ORIGIN.md describe it as a JSON string. The HTTP handler previously only accepted a JSON string, causing requests that sent a JSON object (including the CLI) to fail binding.

## Resolution
Updated `internal/api/handlers/group_member.go` to accept `member_interface` as either a JSON string or a JSON object, normalizing it to a compact JSON string before storage. This preserves backward compatibility with string-based clients while also supporting object-based clients such as the CLI.

## Changes
- Added `MemberInterfaceField` custom type with `json.Unmarshaler`/`json.Marshaler` support.
- `JoinGroupRequest` and `UpdateMemberRequest` now use `MemberInterfaceField`.
- Handler stores `req.MemberInterface.String()` in the model.
- Added unit tests covering object input, string input, and invalid string input for both join and update endpoints.

## Affected Code
- `internal/api/handlers/group_member.go`
- `internal/api/handlers/group_member_test.go`

## Verification
```bash
go test ./internal/api/handlers/ ./cmd/cli/ ./internal/agent/ -count=1
go build ./cmd/...
```
Both commands pass.
