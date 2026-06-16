---
maintainer: AI
status: done
---
# Issue: member_name validation

## Description
`member_name` was accepting any string, including spaces and special characters. This could lead to invalid identifiers, broken mention parsing (`@name`), and inconsistent display in CLI and API responses.

## Rule
`member_name` must contain only alphanumeric characters (a-z, A-Z, 0-9), hyphens (`-`), and underscores (`_`).

## Regex Pattern
`^[a-zA-Z0-9_-]+$`

## Source Code Changes
- **File:** `internal/api/handlers/group_member.go`
  - Added package-level `memberNameRegex` using `regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)`
  - In `JoinGroup()`: validates `req.MemberName` after `ShouldBindJSON`; returns `400 Bad Request` with `{"error": "invalid member_name: must contain only alphanumeric characters, hyphens, and underscores"}` if invalid
  - In `UpdateMember()`: validates `req.MemberName` before building the `updates` map; same error response

## Documentation Updates
- `docs/cases/TestCase_api.md`
- `docs/cases/TestCase_integration.md`
- `docs/cases/TestCase_manual_api.md`
- `docs/cases/UserCase_agent_trigger.md`
- `docs/cases/UserCase_group_chat.md`

All invalid `member_name` examples containing spaces were replaced with underscores.

## Verification
- `go build ./...` — compiled successfully with zero errors
- `go test ./...` — all tests passed across all packages

## Notes
- Test code updates are excluded from this issue per project rules.
- The validation follows the existing inline validation pattern used for `member_type` enum checks.
