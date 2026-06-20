---
status: fixed
module: cmd/cli
related_files:
  - cmd/cli/commands.go
  - cmd/cli/commands_test.go
---

# CLI login panics when no credentials are provided

## Problem

`handleLogin` in `cmd/cli/commands.go` dereferenced `args[0]` without checking whether any inline arguments were supplied. When a user ran `/login` without any credentials, the function panicked with an index-out-of-range error instead of printing a helpful message.

## Root Cause

The non-interactive argument parsing path assumed at least one argument was present:

```go
args := parseInlineArgs(parts[1:])
first := args[0] // panic when args is empty
```

## Fix

Added an explicit length check before accessing `args[0]`. When no credentials are provided, the handler now prints:

```
Cancelled: no credentials provided. Usage: /login --api-key KEY | --session-key KEY | --login-name NAME --login-password PASS
```

and returns without panicking.

## Verification

- `TestHandleLogin_MissingCredentials` now passes.
- `go test -race -count=1 ./cmd/cli/...` passes.
- `go test -race -count=1 ./...` passes.
