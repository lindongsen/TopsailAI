---
status: fixed
priority: high
component: discovery / health API
---

# Issue: nil pointer panic on `/health/leader` and `/discovery/services` when `ACS_DISCOVERY_ENABLED=false`

## Summary
When the ACS server is started with `ACS_DISCOVERY_ENABLED=false`, requests to `/health/leader` and `/discovery/services` panic with a nil pointer dereference instead of returning the documented `503 Service Unavailable` response.

## Environment
- ACS commit/branch: latest after default API key file regeneration fix
- Go version: 1.25
- OS: Linux ai-dev (Debian GNU/Linux 13)
- Configuration:
  - `ACS_HTTP_PORT=7370` (and 7371)
  - `ACS_NATS_SERVERS=nats://127.0.0.1:4222`
  - `ACS_DISCOVERY_ENABLED=false`

## Reproduction Steps
1. Start PostgreSQL and NATS (JetStream enabled).
2. Start ACS server with discovery disabled:
   ```bash
   ACS_HTTP_PORT=7370 ACS_NATS_SERVERS=nats://127.0.0.1:4222 ACS_DISCOVERY_ENABLED=false ./bin/acs-server
   ```
3. Wait for server to finish startup.
4. Call either endpoint:
   ```bash
   curl http://127.0.0.1:7370/health/leader
   curl http://127.0.0.1:7370/discovery/services
   ```

## Expected Behavior
Per `docs/API.md`:
- `GET /health/leader` should return `503 Service Unavailable` with a message indicating service discovery is disabled.
- `GET /discovery/services` should return `503 Service Unavailable` with a message indicating service discovery is disabled.

## Actual Behavior
Both endpoints return HTTP 500 with body:
```json
{"error":"internal server error","trace_id":"..."}
```
Server logs show a panic:
```
runtime error: invalid memory address or nil pointer dereference
/TopsailAI/src/topsailai_server/agent_community/internal/discovery/discovery.go:146
        (*Discovery).Discover: if d.kv == nil {
```

## Stack Trace
```
internal/discovery/discovery.go:146  (*Discovery).Discover
internal/discovery/discovery.go:179  (*Discovery).IsLeader
internal/api/handlers/health.go:209  (*HealthHandler).LeaderStatus

internal/discovery/discovery.go:146  (*Discovery).Discover
internal/api/handlers/health.go:180  (*HealthHandler).DiscoveryServices
```

## Impact
- Cluster test plan `TestCase_manual_cli_cluster.md` step CLUSTER-010 (discovery-disabled mode) fails.
- Operators cannot safely query leader/discovery status on nodes where discovery is disabled.

## Root Cause
`cmd/server/main.go` declared a `*discovery.Discovery` pointer and left it `nil` when `ACS_DISCOVERY_ENABLED=false`, then passed that `nil` pointer into `api.NewRouter`. The health handlers called `h.discovery.Enabled()` on the nil receiver, which panicked before the disabled-discovery branch could return 503.

## Fix
1. Exported the `DiscoveryProvider` interface in `internal/api/router.go` so `cmd/server/main.go` can refer to it.
2. In `cmd/server/main.go`, when `cfg.Discovery.Enabled` is false, assign `handlers.NewDisabledDiscovery()` (a non-nil, disabled provider) instead of leaving the pointer nil.
3. Added defensive nil checks in `internal/api/handlers/health.go` `DiscoveryServices()` and `LeaderStatus()` so that even a literal `nil` discovery provider returns HTTP 503 safely.
4. Updated `internal/api/router_test.go` `fakeDiscovery` to implement the new `Enabled() bool` method and corrected the login request field name from `password` to `login_password`.

## Verification
- `go test ./...` passes.
- `make build` succeeds.
- Existing handler tests `TestHealthHandler_DiscoveryServices_Disabled`, `TestHealthHandler_DiscoveryServices_Nil`, `TestHealthHandler_LeaderStatus_Disabled`, and `TestHealthHandler_LeaderStatus_NilDiscovery` all pass.

## Related Files
- `internal/discovery/discovery.go`
- `internal/api/handlers/health.go`
- `internal/api/router.go`
- `cmd/server/main.go`
- `internal/api/router_test.go`
- `docs/API.md`
- `docs/cases/TestCase_manual_cli_cluster.md`
