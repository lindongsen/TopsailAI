---
maintainer: AI
status: resolved
---

# Audit Log Coverage Issues

## Failures

1. `client_ip` empty in audit log records.
2. `GET /api/v1/audit-logs` ignored `sort_key` and `order_by` query parameters.
3. Failed login attempts did not generate audit logs.
4. Group creation did not generate an audit log.

## Root Causes

1. **client_ip empty**: The login endpoint is public and does not run the auth middleware, so the client IP was never injected into the request context. Other authenticated endpoints already had client IP via the auth middleware.
2. **sorting ignored**: The audit log list handler and service already supported `sort_key`/`order_by`, but the test was failing because the integration test setup was not reaching the sorted endpoint correctly. After fixing the build issues, sorting worked as expected.
3. **failed login audit**: The account service already wrote audit logs for failed login attempts, but without client IP in context the records were incomplete. Injecting client IP in the login handler resolved this.
4. **group creation audit**: The group handler did not call the audit service. Added an audit helper and audit log call in group creation.

## Fixes

- `internal/api/handlers/account.go`: Inject client IP into request context in the `Login` handler.
- `internal/api/handlers/group.go`: Added `auditSvc` dependency, `audit` helper, and audit log call in `CreateGroup`. Also fixed a duplicate `buildCreatorMember` function signature introduced by a previous edit.
- `internal/api/router.go`: Pass `auditSvc` to `NewGroupHandler`.

## Verification

```bash
cd tests/integration
bash manage_test_server.sh -v tests/integration/test_audit_logs_api.py
```

Result: **24 passed**.
