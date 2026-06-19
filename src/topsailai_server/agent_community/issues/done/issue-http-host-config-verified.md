---
title: HTTP server host binding already supports ACS_HTTP_HOST
status: verified
priority: low
---

# Issue: HTTP server host binding already supports ACS_HTTP_HOST

## Description
During preparation for multi-node cluster manual testing, the tester reported that the ACS server could not bind to a specific loopback IP because there was no `Host` field in `ServerConfig` and no `ACS_HTTP_HOST` env var.

## Investigation
Code review showed that the support already exists:

- `internal/config/config.go`:
  - `ServerConfig.Host` field is defined.
  - `GetListenAddress()` returns `0.0.0.0` when `Host` is empty, otherwise returns `Host`.
  - `ACS_HTTP_HOST` is bound via Viper: `_ = v.BindEnv("server.host", "ACS_HTTP_HOST")`.
  - Default is empty string for backward compatibility.

- `internal/api/server.go`:
  - `NewServer` builds the listen address with `cfg.Server.GetListenAddress()` and `cfg.Server.Port`.

- `docs/Environment_Variables.md`:
  - `ACS_HTTP_HOST` is already documented in the Server Configuration table.

## Verification
- Ran `go test ./internal/config -count=1 -v` — all tests pass.
- Ran `go test ./... -count=1` — all packages pass.

## Conclusion
No code change was required. The multi-node cluster tests can proceed by setting `ACS_HTTP_HOST=127.1.0.1`, `ACS_HTTP_HOST=127.1.0.2`, etc., on separate server instances.

## Action
Move this issue to `done/` and unblock cluster testing.
