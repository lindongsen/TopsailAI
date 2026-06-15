# Issue: CLI Tab Auto-Completion Not Working

## Problem
The ACS CLI Terminal did not support tab auto-completion. When users typed partial commands like `/mes` and pressed Tab, nothing happened.

## Root Cause
The `readline` instances in both normal mode (`main.go`) and chat mode (`chat.go`) were created using `readline.New()` without configuring an `AutoComplete` handler. The `github.com/chzyer/readline` library requires an explicit `PrefixCompleterInterface` to enable tab completion.

## Fix
1. **Created `cmd/cli/completer.go`** — New file providing:
   - `newNormalCompleter()` — `PrefixCompleter` for all normal-mode commands (`/group:*`, `/member:*`, `/message:*`, `/help`, `/exit`, plus aliases `exit`, `quit`, `help`).
   - `newChatCompleter()` — `PrefixCompleter` for chat-mode commands (`/members`, `/help`, `/exit`, plus aliases `exit`, `quit`).
   - `completerFromCommands()` — helper to build a completer from a string slice.
   - `filterCommands()` — helper for filtering commands by prefix (case-insensitive).

2. **Modified `cmd/cli/main.go`** — Changed `readline.New()` to `readline.NewEx(&readline.Config{...})` with `AutoComplete: newNormalCompleter()`.

3. **Modified `cmd/cli/chat.go`** — Changed `readline.New()` to `readline.NewEx(&readline.Config{...})` with `AutoComplete: newChatCompleter()`.

## Tests
- Added `cmd/cli/completer_test.go` with tests for:
  - Normal completer not nil
  - Chat completer not nil
  - `filterCommands` with various prefixes
  - Case-insensitive filtering
  - `completerFromCommands` helper
  - Do() does not panic on partial inputs

All tests pass: `go test ./cmd/cli/...` ✅

## Example Usage
```
acs@Alice: /mes<TAB>
# completes to /message:list

acs@Alice: /group:<TAB>
# shows: /group:list /group:create /group:enter /group:update /group:delete

acs@Alice:group123# /mem<TAB>
# completes to /members
```

## Files Changed
- `cmd/cli/completer.go` (new)
- `cmd/cli/completer_test.go` (new)
- `cmd/cli/main.go`
- `cmd/cli/chat.go`
