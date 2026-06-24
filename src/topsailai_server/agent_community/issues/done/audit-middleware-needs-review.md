---
status: done
severity: low
component: api
resolved_at: 2026-06-24
---

# Audit log middleware may log health and discovery endpoints

## Summary
`internal/api/router.go` applies `AuditLogger` middleware to the `/api/v1` group only, so public health/discovery endpoints are not audited. This is correct. However, the `AuditLogger` middleware itself is not reviewed here; if it logs all requests regardless of success/failure or skips unauthenticated requests inconsistently, audit logs could be noisy or incomplete.

## Affected file
- `internal/api/middleware/audit.go` (not reviewed in detail)

## Expected behavior
Audit logs should record security-relevant lifecycle actions for protected endpoints, not every read request.

## Actual behavior
Unknown; middleware file was not read during this review.

## Suggested follow-up
Review `internal/api/middleware/audit.go` to confirm it only writes audit records for state-changing actions (create/update/delete/password/session/api_key) and includes client IP and acting account/api key IDs.

## References
- `README.md` "Audit Logs"
- `internal/api/router.go`

## Resolution

Reviewed and updated the audit middleware implementation.

### Findings

1. `AuditLogger` is registered only on `/api/v1` routes, after authentication, so health/discovery endpoints remain unaudited as intended.
2. The middleware only audits state-changing HTTP methods: `POST`, `PUT`, `PATCH`, `DELETE`. `GET`, `HEAD`, `OPTIONS` are skipped.
3. Duplicate audit calls were removed from business services and handlers so the middleware is the single source of truth for HTTP-triggered lifecycle actions.
4. The middleware captures the response body to extract generated resource IDs for create endpoints (account, api_key, group, group_member, group_message).
5. `AuditLogService.Log` allows empty `ResourceID` for `create_*` actions and records `"unknown"` when the ID cannot be determined.
6. The login endpoint (`POST /api/v1/accounts/login`) is placed inside the protected `/api/v1` group so it is audited, while still allowing unauthenticated requests to reach the handler.
7. The async audit goroutine uses `context.WithoutCancel` with a 5-second timeout so the write is not cancelled when the HTTP request completes.
8. The middleware includes `account_id`, `api_key_id`, `client_ip`, `trace_id`, and a stable action name.

### Files changed

- `/TopsailAI/src/topsailai_server/agent_community/internal/services/bootstrap.go`
- `/TopsailAI/src/topsailai_server/agent_community/cmd/server/main.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/router.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/services/bootstrap_file_test.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/services/bootstrap_test.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/middleware/auth_test.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/router_test.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/services/account_service.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/services/api_key_service.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/handlers/group.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/middleware/audit.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/services/audit_log_service.go`
- `/TopsailAI/src/topsailai_server/agent_community/internal/api/middleware/audit_test.go`

### Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community && go build ./...
cd /TopsailAI/src/topsailai_server/agent_community && go test ./...
```

Both commands pass.
