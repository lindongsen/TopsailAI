---
maintainer: AI
status: resolved
related_files:
  - internal/config/config.go
  - cmd/server/main.go
  - internal/discovery/discovery.go
  - docs/Environment_Variables.md
---

# Discovery and Health Endpoint Issues

## Symptoms

Integration tests in `tests/integration/test_health_discovery.py` failed with the following symptoms:

1. `GET /health/leader` and `GET /discovery/services` returned `200` instead of `503` when `ACS_DISCOVERY_ENABLED=false`.
2. The primary server advertised its discovery address as `0.0.0.0` instead of a resolvable local address such as `127.0.0.1`.
3. A second ACS instance could not bind to a different loopback IP (e.g., `127.1.0.2:7370`) because the primary instance bound to `0.0.0.0:7370`, occupying all interfaces.
4. When a second instance was stopped, it remained visible in `/discovery/services`.

## Root Causes

1. **Default bind address was `0.0.0.0`**: `ServerConfig.GetListenAddress()` returned `"0.0.0.0"` when `ACS_HTTP_HOST` was empty. This prevented multiple ACS instances from listening on the same port but different loopback IPs, which is required by the integration tests.
2. **Discovery registration used the bind address directly**: `cmd/server/main.go` passed `cfg.Server.GetListenAddress()` to the discovery provider. When the bind address was `0.0.0.0`, the advertised address was not resolvable.
3. **Disabled-discovery tests hit the wrong instance**: Because the secondary instance could not bind to its intended loopback IP, requests to that IP were handled by the primary instance (which had discovery enabled), so `503` was never returned.
4. **Deregistration was skipped due to a variable name bug**: `cmd/server/main.go` defined `deregisterDiscovery` but the graceful shutdown path referenced an undefined `shutdownDiscovery` variable. The function also had the wrong signature, so even if the name had matched the code would not have compiled.
5. **Missing closing brace**: `cmd/server/main.go` was missing the closing brace for `run()`, causing a syntax error and preventing the server from building.

## Resolution

1. Changed the default HTTP host from `""` (interpreted as `0.0.0.0`) to `"127.0.0.1"` in `internal/config/config.go`.
2. Added `ServerConfig.GetDiscoveryAddress()` that returns a resolvable local address (`127.0.0.1`) when the configured host is empty or `0.0.0.0`.
3. Updated `cmd/server/main.go` to use `GetDiscoveryAddress()` for service discovery registration.
4. Fixed the graceful shutdown sequence in `cmd/server/main.go`:
   - Corrected `shutdownDiscovery` to `deregisterDiscovery`.
   - Called `deregisterDiscovery()` directly (it returns no value) before closing the NATS connection.
   - Added the missing closing brace for `run()`.
5. Updated `docs/Environment_Variables.md` to document the new default value for `ACS_HTTP_HOST`.

## Verification

Run:

```bash
cd /TopsailAI/src/topsailai_server/agent_community && \
bash tests/integration/manage_test_server.sh -v tests/integration/test_health_discovery.py
```

Result:

```
======================== 11 passed, 1 skipped in 14.70s ========================
```

All tests pass except the intentionally skipped readiness-dependency test.
