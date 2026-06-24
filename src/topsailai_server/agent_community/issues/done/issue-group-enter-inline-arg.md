---
issue_id: issue-group-enter-inline-arg
title: /group:enter should support inline group_id argument
status: fixed
component: cmd/cli
---

# /group:enter should support inline group_id argument

## Problem
The `/group:enter` command only worked in interactive mode. Users had to type `/group:enter` and then answer a prompt for the group ID. The CLI requirements in `ORIGIN_CLI.md` state that management commands should support both interactive mode (no arguments) and non-interactive mode (inline arguments).

## Expected Behavior
- `/group:enter` (no argument) continues to prompt interactively for the group ID.
- `/group:enter <group_id>` directly enters the group chat for the provided group ID without prompting.
- An empty or whitespace-only argument should fall back to interactive mode.

## Root Cause
`handleGroupEnter` in `cmd/cli/commands.go` only parsed `--group-id <id>` and `group-id=<id>` formats via `parseInlineArgs`. It did not treat a bare positional argument as the group ID.

## Fix
Updated `handleGroupEnter` in `cmd/cli/commands.go` to fall back to `args[0]` as the group ID when no `--group-id` or `group-id=` value is provided:

```go
params := parseInlineArgs(args)
groupID := params["group-id"]

// Support direct inline argument: /group:enter <group_id>
if groupID == "" && len(args) > 0 {
    groupID = strings.TrimSpace(args[0])
}
```

The existing validation (`GetGroup`) and interactive fallback remain unchanged.

## Files Changed
- `cmd/cli/commands.go`
- `cmd/cli/commands_test.go` (added unit tests for inline argument parsing)

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -count=1 ./cmd/cli/...
go vet ./cmd/cli/...
go build -o /tmp/acs-cli ./cmd/cli
```
All checks passed.
