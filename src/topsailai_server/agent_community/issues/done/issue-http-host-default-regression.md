---
title: HTTP host default regressed to 127.0.0.1 instead of empty (0.0.0.0)
status: fixed
priority: medium
---

# Issue: HTTP host default regressed to 127.0.0.1

## Description
`internal/config/config.go` had `server.host` defaulting to `"127.0.0.1"` and `GetListenAddress()` returning `"127.0.0.1"` when `Host` was empty. This contradicted:
- `docs/Environment_Variables.md`: `ACS_HTTP_HOST` default is empty (all interfaces).
- `internal/config/config_test.go`: `TestLoad_ServerDefaults` expects `cfg.Server.Host == ""` and `TestServerConfig_GetListenAddress` expects `"0.0.0.0"` for empty host.
- `internal/api/server_test.go`: `TestNewServer_AddrAndTimeouts` expects `"0.0.0.0:7370"`.

As a result, `go test ./...` failed on `internal/config` and `internal/api`.

## Root Cause
A previous change set the viper default for `server.host` to `"127.0.0.1"` and changed `GetListenAddress()` to return `"127.0.0.1"` for empty host, likely to make local development bind to loopback by default. This broke the documented contract and existing unit tests.

## Fix
- `internal/config/config.go`:
  - Changed `v.SetDefault("server.host", "127.0.0.1")` to `v.SetDefault("server.host", "")`.
  - Changed `GetListenAddress()` to return `"0.0.0.0"` when `Host` is empty.
  - Updated the function comment to reflect the all-interfaces default.

## Verification
- `go test ./internal/config ./internal/api` passes.
- `go test ./...` passes.
- Full integration test suite still passes (221 passed, 2 skipped).

## Files Changed
- `internal/config/config.go`

## Related
- `issues/done/issue-http-host-config-verified.md` (previous verification; this issue documents the regression and fix).
