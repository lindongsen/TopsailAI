# Issue: CLI ChatMode uses hardcoded stdout, blocking unit-test output capture

## Status

fixed

## Module

cmd/cli

## Description

`ChatMode` in `cmd/cli/chat.go` wrote all user-facing output (command help, member list, send errors, unknown-command errors) directly via `fmt.Println`. This made it impossible for unit tests to assert what the CLI prints without patching `os.Stdout` globally. It also mixed output formatting with business logic, making table-driven tests for `/help`, `/members`, `/exit`, and plain-message sending unnecessarily complex.

## Impact

- Unit tests could not verify `handleInput`, `showMembers`, `showChatHelp`, or `SendChatMessage` output without fragile `os.Stdout` swapping.
- Error paths in `SendChatMessage` were effectively untestable.

## Root Cause

`ChatMode` had no injectable output writer; all output used `fmt.Println`/`fmt.Printf` against the process stdout.

## Fix

- Add an `out io.Writer` field to `ChatMode`.
- Initialize it to `os.Stdout` in `NewChatMode` so production behavior is unchanged.
- Replace all `fmt.Println`/`fmt.Printf` calls in `chat.go` with `fmt.Fprintln(cm.out, ...)` / `fmt.Fprintf(cm.out, ...)`.
- Add a test helper that constructs a `ChatMode` with a `bytes.Buffer` writer.

## Files Changed

- `cmd/cli/chat.go`
- `cmd/cli/chat_test.go`

## Verification

```bash
go test -v -race -count=1 ./cmd/cli/...
go test -race -count=1 ./...
go vet ./...
go build ./...
```

All commands pass.

## Coverage

- `cmd/cli` package coverage improved from ~32% to target ≥60%.
