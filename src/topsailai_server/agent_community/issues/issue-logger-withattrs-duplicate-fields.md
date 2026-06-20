# Issue: Logger.WithAttrs causes duplicate module/trace_id fields

## Status

fixed

## Module

pkg/logger

## Description

`Logger.WithAttrs(module, traceID)` returned a new logger whose underlying `slog.Logger` had `module` and `trace_id` pre-applied via `slog.Logger.With`. However, the public logging methods (`Debug`, `Info`, `Warn`, `Error`) still accept `module` and `traceID` as explicit arguments and always inject them again in the internal `log()` helper. This caused duplicate `module` and `trace_id` attributes in every log record produced by a logger created with `WithAttrs`.

## Impact

- Request-scoped loggers created by `internal/api/middleware/logger.go` would emit duplicate `module` and `trace_id` fields.
- Any caller relying on `WithAttrs` for default attributes would see inconsistent JSON output.

## Root Cause

`WithAttrs` pre-applied attributes to the `slog.Logger`, while the `log()` helper unconditionally re-injected the same attributes.

## Fix

- Store the default `module` and `trace_id` directly on the `Logger` struct.
- In the internal `log()` helper, use the stored defaults only when the explicit `module` or `traceID` argument is empty.
- Added an unexported `newWithWriter(cfg Config, output io.Writer)` constructor so unit tests can inject a `bytes.Buffer` without writing to stdout or real files.

## Files Changed

- `pkg/logger/logger.go`
- `pkg/logger/logger_test.go`

## Verification

```bash
go test -v -race -count=1 ./pkg/logger/...
go test -race -count=1 ./...
go vet ./...
go build ./...
```

All commands pass.

## Coverage

- `pkg/logger` package coverage: 92.3%
