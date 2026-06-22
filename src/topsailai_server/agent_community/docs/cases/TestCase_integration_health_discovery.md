---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Health & Service Discovery

## Overview

Verify health endpoints beyond basic liveness/readiness, and service discovery endpoints that expose Service-Leader status and registered instances.

---

## TC-INT-HD-001: Service Leader Endpoint (Leader)

### Objective

Verify `GET /health/leader` returns the current leader status and service ID when discovery is enabled.

### Steps

1. Ensure `ACS_DISCOVERY_ENABLED=true` (default).
2. Start ACS server and wait for registration.
3. Send `GET /health/leader` with any valid authentication or as unauthenticated (public endpoint).

### Input

```bash
curl -s "${ACS_API_BASE}/health/leader" | jq .
```

### Expected Output

Status: 200
```json
{
  "data": {
    "is_leader": true,
    "service_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 200.
- `data.is_leader` is a boolean.
- `data.service_id` is a valid UUID matching the instance.

---

## TC-INT-HD-002: Service Leader Endpoint (Non-Leader)

### Objective

In a multi-node setup, verify non-leader instances return `is_leader: false`.

### Steps

1. Start two ACS instances against the same NATS/PostgreSQL.
2. Identify leader via smallest `service_id`.
3. Query `/health/leader` on the non-leader instance.

### Expected Output

Status: 200
```json
{
  "data": {
    "is_leader": false,
    "service_id": "660e8400-e29b-41d4-a716-446655440001"
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Non-leader returns `is_leader: false`.
- Leader and non-leader service IDs differ.

---

## TC-INT-HD-003: Service Leader Endpoint When Discovery Disabled

### Objective

Verify `/health/leader` returns 503 when service discovery is disabled.

### Steps

1. Start ACS with `ACS_DISCOVERY_ENABLED=false`.
2. Send `GET /health/leader`.

### Expected Output

Status: 503
```json
{
  "error": "service discovery is disabled",
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 503.
- Error message clearly indicates discovery is disabled.

---

## TC-INT-HD-004: List Registered Services

### Objective

Verify `GET /discovery/services` lists all registered service instances and identifies the leader.

### Steps

1. Start one or more ACS instances with discovery enabled.
2. Authenticate with admin API key.
3. Send `GET /discovery/services`.

### Input

```bash
curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  "${ACS_API_BASE}/discovery/services" | jq .
```

### Expected Output

Status: 200
```json
{
  "data": {
    "items": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "acs",
        "address": "http://10.0.0.1:7370",
        "registered_at_ms": 1704067200000,
        "last_heartbeat_ms": 1704067230000
      }
    ],
    "leader_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 200.
- `items` contains at least one service record.
- Each record has `id`, `name`, `address`, `registered_at_ms`, `last_heartbeat_ms`.
- `leader_id` matches the smallest `id` in `items`.

---

## TC-INT-HD-005: List Registered Services When Discovery Disabled

### Objective

Verify `/discovery/services` returns 503 when discovery is disabled.

### Steps

1. Start ACS with `ACS_DISCOVERY_ENABLED=false`.
2. Send `GET /discovery/services` with admin token.

### Expected Output

Status: 503
```json
{
  "error": "service discovery is disabled",
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 503.
- Error message clearly indicates discovery is disabled.

---

## TC-INT-HD-006: Service Registration Heartbeat

### Objective

Verify registered services update their heartbeat periodically.

### Steps

1. Start ACS with discovery enabled.
2. Query `/discovery/services` and record `last_heartbeat_ms`.
3. Wait for `ACS_DISCOVERY_HEARTBEAT` interval (default 30s).
4. Query again.

### Expected Output

- `last_heartbeat_ms` is greater than the previous value.

### Pass Criteria

- Heartbeat advances between checks.
- Service remains registered.

---

## TC-INT-HD-007: Service Deregistration on Shutdown

### Objective

Verify a service instance deregisters itself on graceful shutdown.

### Steps

1. Start two ACS instances.
2. Verify both appear in `/discovery/services`.
3. Gracefully stop one instance (SIGTERM).
4. Query `/discovery/services` on the remaining instance.

### Expected Output

- Stopped instance is no longer in `items`.
- `leader_id` may change if the stopped instance was leader.

### Pass Criteria

- Deregistered instance disappears within TTL window.
- Remaining instance list is consistent.

---

## TC-INT-HD-008: Readiness Probe Dependency Failure

### Objective

Verify `/readyz` returns 503 when a dependency (database or NATS) is unreachable.

### Steps

1. Start ACS with all dependencies healthy.
2. Verify `/readyz` returns 200.
3. Stop PostgreSQL or NATS.
4. Query `/readyz`.

### Expected Output

Status: 503
```json
{
  "status": "not ready",
  "timestamp": "2024-01-01T00:00:00Z",
  "checks": {
    "database": "unreachable"
  }
}
```

### Pass Criteria

- Returns 503 when a dependency is down.
- `checks` indicates which dependency failed.
- Returns 200 after dependency recovers.

---

## TC-INT-HD-009: Comprehensive Health Includes All Components

### Objective

Verify `GET /health` includes database and NATS checks.

### Steps

1. Start ACS with all dependencies healthy.
2. Send `GET /health`.

### Expected Output

Status: 200
```json
{
  "status": "healthy",
  "version": "v0.1.0",
  "timestamp": "2024-01-01T00:00:00Z",
  "checks": {
    "database": "ok",
    "nats": "ok"
  }
}
```

### Pass Criteria

- Returns 200.
- `checks` contains `database` and `nats` with status `ok`.
- `version` and `timestamp` are present.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_health_discovery.py -v
```

## Notes

- Multi-node tests require starting multiple ACS instances on different HTTP ports/hosts.
- Discovery-disabled tests require a separate server process or environment override.
- Heartbeat test may need adjusted wait time based on `ACS_DISCOVERY_HEARTBEAT`.
