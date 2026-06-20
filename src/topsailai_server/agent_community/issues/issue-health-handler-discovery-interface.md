# Issue: Health handler depends on concrete discovery type, blocking unit tests

## Status

fixed

## Description

`internal/api/handlers/health.go` declared `HealthHandler.discovery` and `NewHealthHandler` using the concrete type `*discovery.Discovery`. This made it impossible to unit-test the `/readyz`, `/health`, `/discovery/services`, and `/health/leader` endpoints without a live NATS server.

## Impact

- Health handler endpoints had no unit-test coverage.
- Any test would need a running NATS server and a real service-discovery registration, which is slow and flaky.

## Fix

Introduced a small package-local `discoveryProvider` interface in `internal/api/handlers/health.go`:

```go
type discoveryProvider interface {
	Discover() ([]discovery.ServiceInfo, error)
	IsLeader() (bool, error)
	LeaderInfo() (*discovery.ServiceInfo, error)
	SelfInfo() discovery.ServiceInfo
}
```

Changed `HealthHandler.discovery` and `NewHealthHandler` to use `discoveryProvider` instead of `*discovery.Discovery`. The concrete `*discovery.Discovery` already satisfies this interface, so callers are unaffected.

Added comprehensive unit tests in `internal/api/handlers/health_test.go` covering:

- `GET /healthz` liveness response.
- `GET /readyz` readiness with healthy DB, unhealthy DB, and nil DB.
- `GET /health` health check with healthy DB, unhealthy DB, and nil DB.
- `GET /discovery/services` with success, error, and nil discovery cases.
- `GET /health/leader` with success, `IsLeader` error, `LeaderInfo` error, and nil discovery cases.

Tests use an in-memory SQLite database for the healthy case and a closed SQLite connection for the unhealthy case. Discovery is mocked via the new interface.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -race ./internal/api/handlers/...
go build ./...
```

All tests pass and the project builds successfully.

## Related Docs

- `docs/API.md` — Health, readiness, discovery, and leader endpoint specifications.
- `docs/Environment_Variables.md` — Service discovery configuration.
