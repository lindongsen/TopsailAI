---
issue_id: issue-remove-cli-member-flags
status: done
labels:
  - cli
  - cleanup
  - refactor
related_files:
  - cmd/cli/main.go
  - cmd/cli/commands.go
  - cmd/cli/chat.go
  - docs/Environment_Variables.md
---

# Remove unused `--member-id` and `--member-name` CLI flags

## Background

The ACS CLI previously exposed `--member-id` and `--member-name` startup flags, and read `ACS_CLI_MEMBER_ID` / `ACS_CLI_MEMBER_NAME` environment variables. These values were used to identify the local user when sending messages to a group.

## Reason for removal

1. The server derives `sender_id` and `sender_type` from the authenticated account or session. The CLI must not supply them (`cmd/cli/api.go` `SendMessage`).
2. The CLI already authenticates via `--api-key` or `--session-key`, and the authenticated account is the correct member identity.
3. `resolveMember` in `cmd/cli/commands.go` now checks group membership using the authenticated `userID` only.
4. `ORIGIN_CLI.md` does not mention these flags; it describes `/group:enter` and interactive commands.

## Changes

### `cmd/cli/main.go`

- Removed `--member-id` and `--member-name` flag definitions.
- Removed `state.memberID` and `state.memberName` initialization.
- Simplified startup banner to show authenticated `userID` / `userName` / `accountRole`.

### `cmd/cli/commands.go`

- Removed `CLIState.memberID` and `CLIState.memberName` fields.
- Simplified `resolveMember` to verify group membership by `state.userID` and removed the fallback to member flags.
- Removed unused `sanitizeMemberName` helper.

### `cmd/cli/chat.go`

- Removed `ChatMode.memberID` field and constructor parameter.
- `EnterChat` now takes `groupID, userID, userName`.
- Local message echo uses `userID` instead of `memberID`.

### `docs/Environment_Variables.md`

- Removed `ACS_CLI_MEMBER_ID` and `ACS_CLI_MEMBER_NAME` from the CLI Configuration table.
- Removed the same variables from the example environment file.

## Verification

- `go build -o bin/acs-cli ./cmd/cli` succeeds.
- `./bin/acs-cli -h` no longer lists `--member-id` or `--member-name`.

## Notes

No tests were modified per task instructions.
