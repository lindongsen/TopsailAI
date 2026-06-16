# Issue: CLI `exit`/`quit` in group chat exits process instead of leaving chat mode

## Description
After entering a group chat via `/group:enter`, typing `exit`, `quit`, or `/exit` currently exits the entire CLI process. The expected behavior is to leave the group chat and return to the normal prompt `acs@{userName}: `.

## Expected Behavior
- When inside a group chat (`/group:enter`), `exit`, `quit`, and `/exit` should leave chat mode and return to the normal prompt.
- When NOT inside a group chat, `exit`, `quit`, and `/exit` should still terminate the process as before.

## Root Cause
`cmd/cli/chat.go` already handles `/exit`, `exit`, and `quit` inside chat mode by calling `cm.LeaveChat()`, which closes the chat readline and returns from `EnterChat()`.

`cmd/cli/commands.go` `handleGroupEnter` correctly closes the main readline, enters chat mode, and recreates `state.rl` with a normal prompt after `EnterChat` returns.

However, `cmd/cli/main.go` reads input from the local `rl` variable in the main loop, not from `state.rl`. After `handleGroupEnter` returns, `state.rl` points to a new readline instance, but the loop continues reading from the original closed `rl`, which immediately returns EOF and causes the process to exit.

## Fix
1. `cmd/cli/main.go`
   - Changed the main loop to read from `state.rl.Readline()` instead of the local `rl.Readline()`.
   - This ensures that after `handleGroupEnter` replaces `state.rl`, the main loop uses the new readline instance.

2. `cmd/cli/commands.go`
   - Updated `handleGroupEnter` to recreate `state.rl` using `readline.NewEx` with `newNormalCompleter()`, preserving command auto-completion in the normal prompt.

## Files Modified
- `cmd/cli/main.go`
- `cmd/cli/commands.go`

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -count=1 ./cmd/cli/...
go build ./cmd/cli
```

All tests pass and the CLI binary builds successfully.

## Status
- Fixed
