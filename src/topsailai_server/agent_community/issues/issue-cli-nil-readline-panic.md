---
status: fixed
module: cmd/cli
---

# CLI nil readline panic

## Problem

When a CLI command handler (e.g., `handleLogin`) was invoked without inline
arguments and the `CLIState.rl` field was `nil` (non-interactive contexts such
as unit tests or piped input), it created an `InteractivePrompt` via
`NewInteractivePrompt(nil)`. The prompt wrapper `readlineLineReader` stored a
nil `*readline.Instance` and dereferenced it on the first `Clean()` call,
causing a segmentation violation:

```
panic: runtime error: invalid memory address or nil pointer dereference
```

## Root Cause

`NewInteractivePrompt` unconditionally constructed `&readlineLineReader{rl: rl}`
without checking for `nil`. The `readlineLineReader.Clean()` method called
`r.rl.Clean()` directly.

## Fix

Updated `NewInteractivePrompt` in `cmd/cli/interactive.go` to return a prompt
backed by a `nilLineReader` when `rl == nil`. `nilLineReader` no-ops for
`SetPrompt`/`Clean` and returns `ErrCancelled` for all read operations, so
command handlers fail gracefully with a cancellation message instead of
panicking.

## Files Changed

- `cmd/cli/interactive.go`
- `cmd/cli/commands_test.go` (added regression tests)

## Verification

```bash
go test -race -count=1 ./cmd/cli/...
```

All tests pass.
