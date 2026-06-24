---
maintainer: human
related_cases:
  - CLI-CLUSTER-008
  - CLI-CLUSTER-010
---

# Issue: Restarted ACS Node Does Not Rejoin Cluster Discovery

## Summary
After a non-leader ACS node is gracefully stopped and restarted with the same configuration (same HTTP host/port, same NATS server, `ACS_DISCOVERY_ENABLED=true`), it does not reappear in the `/discovery/services` response on the surviving nodes. The restarted node only sees itself as the sole registered service and reports itself as leader.

## Environment
- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Binary: `./bin/acs-server` (rebuilt from latest approved changes)
- NATS: `nats://localhost:4222` with JetStream enabled
- Database: PostgreSQL (`acs`)
- Nodes:
  - node1: `127.0.0.1:7370` (pid 2441129)
  - node2: `127.0.0.1:7371` (pid 2441131)
  - node3: `127.0.0.1:7372` (restarted, pid 2451636)

## Steps to Reproduce
1. Start a 3-node cluster on `127.0.0.1:7370/7371/7372` sharing the same NATS and PostgreSQL.
2. Verify `/discovery/services` on all nodes returns 3 services and leader is consistent.
3. Gracefully stop node3 (e.g., `Ctrl-C` in its tmux pane).
4. Wait for surviving nodes to show only 2 services.
5. Restart node3 with the same command/env.
6. Query `/discovery/services` on node1/node2 and on node3.

## Expected Result
- node1/node2 `/discovery/services` returns 3 services including the restarted node3.
- node3 `/discovery/services` returns 3 services and agrees on the leader.

## Actual Result
- node1 (`7370`) and node2 (`7371`) each report only 2 services; node3 is missing.
- node3 (`7372`) reports only 1 service (itself) and reports `is_leader=true`.
- node3 logs show no `discovery`/`register`/`heartbeat` debug messages after restart.

## Evidence

### node1 /discovery/services
```json
{
  "services": [
    {"id":"0637ec18-2881-4d04-b59d-694ed30521f9","name":"acs","address":"127.0.0.1","port":7371,"version":"1.0.0","started_at_ms":1782273746501},
    {"id":"996e20cf-fcdd-4bef-9544-0c2e8ead6fe3","name":"acs","address":"127.0.0.1","port":7370,"version":"1.0.0","started_at_ms":1782273746471}
  ],
  "count": 2
}
```

### node3 /discovery/services
```json
{
  "services": [
    {"id":"5fae2961-3cbf-4f0a-8049-db2c40729336","name":"acs","address":"127.0.0.1","port":7372,"version":"1.0.0","started_at_ms":1782274810017}
  ],
  "count": 1
}
```

### node3 process environment
```
ACS_DATABASE_DRIVER=postgres
ACS_DATABASE_HOST=localhost
ACS_DATABASE_NAME=acs
ACS_DATABASE_PASSWORD=acs
ACS_DATABASE_PORT=5432
ACS_DATABASE_USER=acs
ACS_DISCOVERY_ENABLED=true
ACS_HTTP_HOST=127.0.0.1
ACS_HTTP_PORT=7372
ACS_LOG_LEVEL=debug
ACS_NATS_SERVERS=nats://localhost:4222
```

### Root Cause Investigation
Inspecting the running processes revealed that node1 and node2 were started with:
```
ACS_DISCOVERY_BUCKET_NAME=acs_cluster_discovery
```
while node3 was restarted without this variable, causing it to fall back to the default bucket `acs_service_discovery`. The two buckets contained disjoint registrations:
- `acs_cluster_discovery`: 2 entries (node1, node2)
- `acs_service_discovery`: 1 entry (node3)

This is a configuration/test-setup mismatch, not a NATS connection failure. The discovery package was correctly registering node3, but into a different KV bucket than the rest of the cluster.

In addition, the original implementation generated a random UUID per process for the service ID. On restart this produced a second, stale registration entry that lingered until TTL expiry, making rejoin behavior less deterministic.

## Fix Applied
1. **Deterministic service ID**: `internal/discovery/discovery.go` now derives the service registration key from a SHA-256 hash of `serviceName|address:port`. A restarted node on the same address overwrites its previous registration instead of creating a parallel UUID entry.
2. **Operational logging**: Added `INFO`/`DEBUG` logs for discovery initialization, registration, deregistration, and heartbeat events, including the bucket name and service ID. This makes bucket-name mismatches visible in server logs.
3. **Restart rejoin test**: Added `TestDiscovery_RestartRejoin` to verify that a deregistered node rejoins the same bucket and replaces any stale registration.

## Files Changed
- `internal/discovery/discovery.go`
- `internal/discovery/discovery_test.go`

## Verification
- `go test ./internal/discovery/...` passes.
- `make build-server` succeeds.

## How to Re-run the Blocked Test
1. Stop all ACS nodes and ensure a single NATS server is running.
2. Start every node with the **same** discovery bucket name, e.g.:
   ```bash
   export ACS_DISCOVERY_BUCKET_NAME=acs_service_discovery
   export ACS_DISCOVERY_ENABLED=true
   export ACS_NATS_SERVERS=nats://localhost:4222
   # start node1/node2/node3
   ```
3. Verify `/discovery/services` returns 3 services on all nodes.
4. Stop node3, wait for TTL expiry or for surviving nodes to show 2 services, then restart node3 with the same environment.
5. Verify all nodes again report 3 services and agree on the leader.

## Impact
- Cluster membership becomes inconsistent if nodes use different `ACS_DISCOVERY_BUCKET_NAME` values.
- Leader election and distributed-lock based tasks (default account creation, auto-trigger) may run on multiple nodes or fail to run on the correct node.
- Blocks completion of Phase 7 cluster manual test cases, specifically node-restart resilience and leader-restart lock tests.

## Related Files
- `internal/discovery/discovery.go`
- `internal/discovery/discovery_test.go`
- `internal/config/config.go`
- `cmd/server/main.go`

## Notes
- User directive: NO NEED SOFT-DELETE for `groups` and `group_member`. This issue is unrelated to soft-delete.
- This issue was discovered while executing `CLI-CLUSTER-008` and blocks `CLI-CLUSTER-010`.
- The code change does not alter soft-delete behavior for any database table.

## Resolution

- **Status:** resolved
- **Source files changed:**
  - `internal/discovery/discovery.go`
  - `internal/discovery/discovery_test.go`
- **Key fix:**
  - Service registration key is now deterministic: `SHA-256(serviceName|address:port)`.
  - `Register()` uses `kv.Put()` so a restarted node on the same address overwrites any stale registration instead of creating a parallel UUID entry.
  - Added `TestDiscovery_RestartRejoin` to verify restart rejoin behavior.
- **Test verification:**
  - `go test ./internal/discovery/...` passes.
  - Full suite `go test ./...` passes.
