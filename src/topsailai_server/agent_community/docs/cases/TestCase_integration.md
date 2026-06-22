---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration Testing

## Overview

This document describes end-to-end integration test scenarios for the AI-Agent Community Server (ACS). These tests verify the interaction between all components: HTTP API, database, NATS message bus, agent triggering, and agent execution.

Integration tests are written in Python under `tests/integration/` and executed with pytest against a running ACS server.

---

## Scope

The integration test suite covers the following functional areas:

1. **Health & Service Discovery** — liveness, readiness, leader election, service registry
2. **Account & API Key Management** — CRUD, authentication, sessions, RBAC, audit logs
3. **Group & Member Management** — CRUD, permissions, member status, auto-join manager-agent
4. **Messaging** — CRUD, mentions, attachments, pagination, filtering, soft delete
5. **Agent Triggering** — mentions, `@all`, single-user auto-trigger, timeout auto-trigger, `NO_TRIGGER_CASES`, manual trigger
6. **NATS Messaging** — pub/sub, JetStream, pending messages, real-time events
7. **Infrastructure** — distributed locks, graceful shutdown, cleanup tasks, work-pool limits

---

## Test Organization

| Test Plan File | Coverage |
|---------------|----------|
| `TestCase_integration_health_discovery.md` | `/health/leader`, `/discovery/services`, discovery-disabled behavior |
| `TestCase_integration_audit_logs.md` | Audit log list/get endpoints, filtering, sensitive-field omission |
| `TestCase_integration_rbac.md` | Role-based access control for accounts, groups, members, messages, API keys |
| `TestCase_integration_group_key.md` | Private groups, `group_key` hashing, access control |
| `TestCase_integration_agent_trigger.md` | Agent triggering rules, `@all`, auto-trigger, `NO_TRIGGER_CASES`, concurrent mentions |
| `TestCase_integration_message_attachments.md` | Messages with file/image attachments |
| `TestCase_integration_session_expiry.md` | Session key expiration and renewal |

---

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| ACS Server | Built and running (`make run` or `go run cmd/server/main.go`) |
| PostgreSQL | Running with `acs` database |
| NATS Server | Running with JetStream enabled |
| Mock Agent Server | Running on configured port |
| Python | 3.10+ with dependencies from `tests/integration/requirements.txt` |

---

## Test Execution

### Run All Integration Tests

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make test-integration
```

### Run Specific Test File

```bash
cd tests/integration
pytest test_api.py -v
```

### Run Specific Test Plan Area

```bash
pytest test_health_discovery.py -v
pytest test_rbac.py -v
pytest test_agent_trigger.py -v
```

---

## Verification Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | All API endpoints return correct status codes | |
| 2 | Database state is consistent after operations | |
| 3 | NATS events are published for all mutations | |
| 4 | Agent triggers work for mentions and auto-triggers | |
| 5 | Agent responses are stored with correct metadata | |
| 6 | Distributed locks prevent race conditions | |
| 7 | Semaphore limits are respected | |
| 8 | Graceful shutdown releases all resources | |
| 9 | RBAC rules are enforced correctly | |
| 10 | Error scenarios are handled gracefully | |
| 11 | Pagination and filtering work correctly | |
| 12 | Real-time message delivery via NATS works | |

---

## Notes

- Each focused test plan file contains detailed test cases for a specific functional module.
- Test implementation files should mirror the plan files in `tests/integration/`.
- See individual plan files for concrete inputs, expected outputs, and pass criteria.
