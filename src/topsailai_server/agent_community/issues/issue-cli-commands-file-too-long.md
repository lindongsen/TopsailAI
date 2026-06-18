# Issue: cmd/cli/commands.go exceeds project line limit

## Status
open

## Description
The project guideline states that source files should be kept under 700 lines.
`cmd/cli/commands.go` has grown beyond this limit due to the addition of
account, API key, and authorization command handlers.

## Affected file
- `cmd/cli/commands.go`

## Impact
Reduced readability and maintainability. Increases risk of merge conflicts and
makes navigation harder.

## Suggested Fix
Split `commands.go` into smaller focused files, for example:
- `cmd/cli/account_commands.go` — account CRUD, login, logout, password
- `cmd/cli/apikey_commands.go` — API key CRUD
- `cmd/cli/group_commands.go` — group/member/message commands
- `cmd/cli/commands.go` — dispatcher and shared helpers only

Ensure existing tests continue to pass after the refactor.
