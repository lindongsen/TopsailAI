# CLI Interactive Prompt Input Misalignment

## Problem
During live testing of `/account:create`, the interactive prompt flow exhibited input misalignment: the value entered at the `Login password` prompt leaked into the next `Email` prompt. The captured pane output showed:

```
Login password: password123
Email: password123
```

This caused the account creation request to set `email` to the password value instead of the intended email address.

## Root Cause
The `cmd/cli/interactive.go` `readlineLineReader` wrapper reused the same `chzyer/readline` instance between the main command loop and interactive parameter prompts. The readline internal buffer was not reliably cleared between consecutive `Readline()` calls, so stale input from the previous prompt could be returned by the next prompt.

## Fix
- Updated `readlineLineReader.Readline()` and `ReadlineWithDefault()` to call `r.rl.Clean()` both before and after each read, ensuring a fresh buffer for every prompt.
- Added a regression test `TestPromptAccountCreate_PasswordDoesNotLeakIntoEmail` in `cmd/cli/interactive_test.go` that verifies the password value does not leak into the email field.

## Files Changed
- `cmd/cli/interactive.go`
- `cmd/cli/interactive_test.go`

## Verification
- `go test ./cmd/cli` passes.
- `go build -o /tmp/acs-cli ./cmd/cli` succeeds.
