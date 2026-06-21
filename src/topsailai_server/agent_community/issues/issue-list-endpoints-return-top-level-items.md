---
status: fixed
priority: high
component: api
affected_endpoints:
  - GET /api/v1/accounts
  - GET /api/v1/accounts/:account_id/api-keys
  - GET /api/v1/audit-logs
  - GET /api/v1/groups
  - GET /api/v1/groups/:group_id/members
  - GET /api/v1/groups/:group_id/messages
related_docs:
  - docs/API.md
---

# List endpoints return top-level `items` instead of documented `.data.items`

## Summary

The API documentation (`docs/API.md`) states that all list endpoints return list data wrapped under a top-level `data` object:

```json
{
  "data": {
    "items": [...],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

However, the server currently returns the list envelope directly at the top level:

```json
{
  "items": [...],
  "total": 1,
  "offset": 0,
  "limit": 1000
}
```

This breaks clients built against the documented contract, including the CLI terminal and any external integrations.

## Reference

`docs/API.md` â€” Response Format section and every list endpoint example.

## Affected Endpoints

- `GET /api/v1/accounts`
- `GET /api/v1/accounts/:account_id/api-keys`
- `GET /api/v1/audit-logs`
- `GET /api/v1/groups`
- `GET /api/v1/groups/:group_id/members`
- `GET /api/v1/groups/:group_id/messages`

## Reproduction Steps

1. Start the ACS server with a valid database and NATS.
2. Create at least one resource for any list endpoint (e.g., create a group as admin).
3. Call the list endpoint:

```bash
curl -s -X GET http://localhost:7370/api/v1/groups \
  -H "Authorization: Bearer {admin_api_key}"
```

4. Observe the response shape.

## Expected Behavior

```json
{
  "data": {
    "items": [...],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

## Actual Behavior (Before Fix)

```json
{
  "items": [...],
  "total": 1,
  "offset": 0,
  "limit": 1000
}
```

## Fix

- Updated `internal/api/handlers/response.go`:
  - `writeListResponse` now wraps the list envelope under `data` and includes `trace_id`.
- Updated all list handlers to use `writeListResponse`:
  - `internal/api/handlers/account.go` — `ListAccounts`
  - `internal/api/handlers/api_key.go` — `ListAPIKeys`
  - `internal/api/handlers/audit_log.go` — `ListAuditLogs`
  - `internal/api/handlers/group.go` — `ListGroups`
  - `internal/api/handlers/group_member.go` — `ListGroupMembers`
  - `internal/api/handlers/message.go` — `ListMessages`
- Updated all corresponding handler tests to assert the wrapped `data.items` shape.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/... -v
go test ./... -v
make build
```

All tests pass and the project builds successfully.

## Environment

- ACS version: current `main`
- Database: PostgreSQL
- NATS: JetStream enabled
- Tested via: go test, make build
