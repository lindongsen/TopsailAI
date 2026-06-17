---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Feature: Accounts, API Keys, and Audit Logs

## Status

Done.

## Description

Implement the full lifecycle management for `accounts`, `api_keys`, and `audit_logs` as specified in `ORIGIN.md`, `docs/API.md`, and `docs/Environment_Variables.md`. This includes account CRUD, multiple authentication methods (API key, session key, login name/password), API key management with role constraints, and comprehensive audit logging for all lifecycle actions.

## Scope

- Accounts
- API Keys
- Audit Logs

## Implementation Summary

### Models

- `internal/models/account.go` — Account model with fields: `account_id`, `account_name`, `account_description`, `role`, `status`, `delete_at_ms`, `creator_id`, `external_id`, `email`, `auth_provider`, `avatar_url`, `login_name`, `login_password`, `login_session_key`, `login_session_expired_time`, `create_at_ms`, `update_at_ms`.
- `internal/models/api_key.go` — APIKey model with fields: `api_key_id`, `api_key_name`, `api_key_hash`, `role`, `status`, `creator_id`, `owner_id`, `create_at_ms`, `update_at_ms`.
- `internal/models/audit_log.go` — AuditLog model with fields: `audit_log_id`, `account_id`, `api_key_id`, `action`, `resource_type`, `resource_id`, `resource_name`, `detail`, `client_ip`, `create_at_ms`.

### Migrations

- `internal/db/migrations/000002_add_accounts_api_keys_audit_logs.up.sql`
- `internal/db/migrations/000002_add_accounts_api_keys_audit_logs.down.sql`
- Updated `internal/db/db.go` to include new models in `AutoMigrate`.

### Configuration

- Updated `internal/config/config.go` with:
  - `ACS_ACCOUNT_ADMIN_API_KEY`
  - `ACS_ACCOUNT_MANAGER_API_KEY`
  - `ACS_API_KEY_MAX_PER_ACCOUNT`
  - `ACS_LOGIN_SESSION_EXPIRY_SECONDS`
  - `ACS_BCRYPT_COST`

### Services

- `internal/services/account_service.go` — Password/session hashing (bcrypt), CRUD, soft delete, cascade API key deletion.
- `internal/services/api_key_service.go` — Token generation (`{api_key_id}.{secret}`), hash, verify, per-owner limit, role constraint.
- `internal/services/audit_log_service.go` — Write audit records.

### Middleware

- `internal/api/middleware/auth.go` — Authenticate via `Authorization: Bearer` token or `X-Session-Key`, inject account context.
- `internal/api/middleware/audit.go` — Log lifecycle actions to `audit_logs`.

### Handlers

- `internal/api/handlers/account.go` — Account CRUD, login, session creation, password change.
- `internal/api/handlers/api_key.go` — Create/list/delete API keys.
- `internal/api/handlers/audit_log.go` — List/get audit logs.

### Router

- Updated `internal/api/router.go` to wire new routes and apply authentication middleware to existing group/message endpoints.

### Startup Bootstrap

- Updated `cmd/server/main.go` to perform service-leader guarded default `admin` and `manager` account creation, validate environment-provided keys, and log account counts on startup.

### Tests

- Unit tests for services and middleware.
- Handler unit tests.
- Python integration tests under `tests/integration/`.

### Documentation

- Updated `docs/API.md` with account, API key, and audit log endpoints.
- Updated `docs/Environment_Variables.md` with new environment variables.
- Updated `.task/Code_Improvement_Proposal.md` and `.task/Test_Execution_Checklist.md`.

## Files Created/Modified

- `internal/models/account.go`
- `internal/models/api_key.go`
- `internal/models/audit_log.go`
- `internal/db/migrations/000002_add_accounts_api_keys_audit_logs.up.sql`
- `internal/db/migrations/000002_add_accounts_api_keys_audit_logs.down.sql`
- `internal/db/db.go`
- `internal/config/config.go`
- `internal/services/account_service.go`
- `internal/services/api_key_service.go`
- `internal/services/audit_log_service.go`
- `internal/services/api_key_service_test.go`
- `internal/api/middleware/auth.go`
- `internal/api/middleware/audit.go`
- `internal/api/handlers/account.go`
- `internal/api/handlers/api_key.go`
- `internal/api/handlers/audit_log.go`
- `internal/api/router.go`
- `cmd/server/main.go`
- `docs/API.md`
- `docs/Environment_Variables.md`
- `.task/Code_Improvement_Proposal.md`
- `.task/Test_Execution_Checklist.md`

## Verification

- [x] `go build ./...` passes.
- [x] `go test ./...` passes.
- [x] `go vet ./...` passes.
- [x] Final review approved by `km2-reviewer`.

## Review Notes

Final review approved by `km2-reviewer`. Three critical issues were identified during review and fixed:

1. **Admin can create API keys for manager accounts** — Removed service-level rejection for manager owners; handler still rejects manager-self-creation.
2. **Audit middleware path patterns** — Corrected path matching to use `/api-keys/` and `/audit-logs/` to match the router.
3. **Environment variable binding** — Added explicit `BindEnv` calls for `ACS_API_KEY_MAX_PER_ACCOUNT`, `ACS_LOGIN_SESSION_EXPIRY_SECONDS`, and `ACS_BCRYPT_COST`.

## Known Limitations

- Integration tests require a running ACS server plus external dependencies (PostgreSQL, NATS) and were not executed in this cycle.
- Audit middleware spawns a goroutine using the request context, which carries cancellation risk if the request completes before the audit write finishes.
