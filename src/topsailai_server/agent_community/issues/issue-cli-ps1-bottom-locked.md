---
status: fixed
created_at: 2026-06-16T20:10:00
related_files:
  - cmd/cli/main.go
  - cmd/cli/chat.go
  - cmd/cli/commands.go
  - cmd/cli/display.go
  - cmd/cli/prompt.go
---

# Issue: CLI PS1 prompt should always stay at the bottom of the terminal

## Problem
In the ACS CLI terminal, when new messages arrived via NATS or HTTP polling, they were printed above the readline prompt, but the prompt itself was not redrawn at the bottom. This caused the prompt to drift upward as more output appeared, making the terminal hard to use during group chat sessions.

## Root Cause
The CLI used direct `fmt.Println`/`fmt.Printf` calls throughout `main.go`, `chat.go`, `commands.go`, and the NATS event handler. These calls wrote to stdout without telling the active `readline` instance to clear and redraw its prompt line. `chat.go` attempted a manual `cm.rl.Refresh()` after `displayEvent`, but this only covered chat-mode events and did not handle normal-mode output or the initial banner.

## Fix
Introduced a centralized prompt manager in `cmd/cli/prompt.go` that knows which readline instance currently owns the prompt (normal vs. chat mode). All terminal output now goes through `promptPrintln`, `promptPrintf`, and `promptPrintLines`, which:

1. Determine the active readline instance via `activeReadline()`.
2. Call `rl.Clean()` to clear the current prompt line.
3. Print the output above the prompt.
4. Call `rl.Refresh()` to redraw the prompt at the bottom.

When no readline instance is active (e.g., before startup), the functions fall back to plain `fmt` output.

### Files changed
- `cmd/cli/prompt.go` (new): state-based prompt manager with `setPromptState`, `activeReadline`, and prompt-aware print helpers.
- `cmd/cli/main.go`: registered the CLI state with the prompt manager, switched banner/info output and the default NATS event handler to prompt-aware helpers.
- `cmd/cli/chat.go`: replaced direct `fmt.Println` calls in `SendChatMessage`, `showMembers`, `showChatHelp`, and `displayEvent` with `promptPrintln`; removed the now-redundant manual `rl.Refresh()` in `displayEvent`.
- `cmd/cli/commands.go`: replaced direct `fmt.Println`/`fmt.Printf` calls in command handlers with prompt-aware helpers.
- `cmd/cli/display.go`: switched `printBanner()` to use `promptPrintLines()`.

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -count=1 ./cmd/cli/...
go vet ./cmd/cli/...
go build -o /tmp/acs-cli ./cmd/cli
```

All tests pass, `go vet` reports no issues, and the CLI binary builds successfully.

## Impact
- Normal prompt `acs@{userName}: ` stays at the bottom when commands print output.
- Chat prompt `acs@{userName}:{groupId}# ` stays at the bottom when messages, member events, or NATS events arrive.
- Existing functionality preserved: interactive commands, group chat mode, exit/quit behavior, `/group:enter [group_id]` inline argument, auto-completion, multi-byte character support, color output, and `--no-color`/`NO_COLOR` support.
