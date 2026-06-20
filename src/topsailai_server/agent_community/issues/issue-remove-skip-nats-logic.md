---
status: fixed
related_files:
  - cmd/server/main.go
  - cmd/server/main_test.go
  - internal/config/config.go
  - internal/api/handlers/message.go
  - internal/api/handlers/group_member.go
  - internal/nats/consumer.go
  - docs/Environment_Variables.md
---

# Remove `ACS_SKIP_NATS` / `SkipNATS` Logic

## Problem

The project had introduced `ACS_SKIP_NATS` as an environment-variable replacement for the `testOverrides.skipNATS` test-only code path. A review found that skipping NATS is not functionally safe for ACS:

- Automatic agent triggering was silently skipped.
- Manual agent triggering (`POST /api/v1/groups/:group_id/messages/:message_id/trigger`) panicked due to a nil publisher.
- Agent execution via the AgentWorkPool was disabled because no NATS consumer was running.
- Auto-trigger idle-timeout scanning was not started.
- Group/member/message pub/sub events were not published.
- Service discovery and distributed locks were disabled.

NATS is a required dependency for ACS (pending message queue, AgentWorkPool distribution, auto-trigger locks, service discovery, group events). Allowing it to be skipped created a degraded, misleading mode that could not execute agents.

## Fix

1. Removed the `ACS_SKIP_NATS` environment variable and the `NATSConfig.SkipNATS` configuration field.
2. Removed all `SkipNATS` branches from `cmd/server/main.go`; NATS is now always initialized.
3. Removed nil-publisher guards that had been added to accommodate skip-NATS mode in:
   - `internal/api/handlers/message.go`
   - `internal/api/handlers/group_member.go`
   - `internal/nats/consumer.go`
4. Restored the "Reload message" logic in `internal/api/handlers/message.go` (`UpdateMessage` and `DeleteMessage`) that was accidentally removed while cleaning up skip-NATS guards.
5. Removed `TestRunServer_GracefulShutdown_NoNATS` from `cmd/server/main_test.go`, which depended on `ACS_SKIP_NATS=true`.
6. Removed `ACS_SKIP_NATS` documentation from `docs/Environment_Variables.md` and the example environment file.

## Impact

- The server now requires a reachable NATS server on startup.
- All agent-triggering paths are consistent and no longer contain skip-NATS special cases.
- Test environments that need to exercise server startup must provide NATS (e.g., an embedded NATS server) instead of bypassing the dependency.

## Verification

- `go build ./cmd/server` passes.
- `go test ./cmd/server` passes.
- `go test ./internal/...` passes.
- `go vet ./cmd/server ./internal/...` passes.
- Full-workspace grep for `skip_nats`, `SkipNATS`, `ACS_SKIP_NATS`, and `testOverrides` returns only this issue file.
