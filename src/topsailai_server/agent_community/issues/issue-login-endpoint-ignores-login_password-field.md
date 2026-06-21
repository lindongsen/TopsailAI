---
status: fixed
priority: high
component: api
affected_endpoints:
  - POST /api/v1/accounts/login
  - POST /api/v1/accounts/:account_id/session
related_docs:
  - docs/API.md
---

# Login endpoint ignores documented `login_password` field

## Summary

The API documentation (`docs/API.md`) states that the login endpoint accepts a field named `login_password` in the request body. However, the server currently expects and processes a field named `password` instead. This breaks clients built against the documented contract, including the CLI terminal and any external integrations.

## Reference

`docs/API.md` â€” `POST /api/v1/accounts/login`:

```json
{
  "login_name": "alice@example.com",
  "login_password": "secure-password"
}
```

## Reproduction Steps

1. Start the ACS server with a valid database and NATS.
2. Create a user account with a login name and password (e.g., via `POST /api/v1/accounts` as admin).
3. Attempt to log in using the documented field name:

```bash
curl -s -X POST http://localhost:7370/api/v1/accounts/login \
  -H "Content-Type: application/json" \
  -d '{"login_name":"alice@example.com","login_password":"secure-password"}'
```

4. Observe the response.

## Expected Behavior

The server accepts `login_password` and returns a session key wrapped under `data`:

```json
{
  "data": {
    "account_id": "acc-abc123",
    "session_key": "acc-abc123-...",
    "expires_at_ms": 1704153600000
  },
  "trace_id": "..."
}
```

## Actual Behavior (Before Fix)

The server rejected the request or failed to authenticate because it expected `password` instead of `login_password`. Using `password` succeeded, while using the documented `login_password` did not. The response was also returned without the `data` wrapper.

## Fix

- Updated `internal/api/handlers/account.go`:
  - `Login` handler now returns the session wrapped under `data` with `trace_id`.
  - `CreateSession` handler now returns the session wrapped under `data` with `trace_id` (same response contract).
- Updated `internal/api/router_test.go`:
  - `TestNewRouter_PublicEndpoints` now sends `login_password` instead of `password`.
- Added `writeDataResponse` helper in `internal/api/handlers/response.go` for consistent single-object response wrapping.

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
