# Issue: Audit middleware logs "no such table: audit_logs" in unit tests

## Status

Open, low priority.

## Description

When running `internal/api/router_test.go`, specifically `TestNewRouter_ProtectedEndpointsRequireAuth`, the audit middleware is wired but the in-memory SQLite database used by the test has not run migrations for the `audit_logs` table. The middleware attempts to insert audit records and logs an error such as:

```
no such table: audit_logs
```

The error is non-fatal: the audit helper logs the failure and continues, so HTTP responses and test assertions are unaffected.

## Impact

- Test output contains warnings that may be mistaken for real failures.
- Could mask genuine audit-logging issues in CI logs.

## Root Cause

`setupRouterTestDependencies` creates a router with `middleware.AuditLogger(auditSvc)`, but some test paths intentionally use an unmigrated DB to verify 401 behavior. The audit middleware does not check table existence before inserting.

## Proposed Fix

Option A (preferred): In `internal/api/middleware/audit.go`, check whether the `audit_logs` table exists (or whether the DB is nil/unmigrated) before attempting to insert. Skip audit logging gracefully when the table is unavailable.

Option B: Ensure all router test setups run `AutoMigrate` for `models.AuditLog` before the router is created. This is already done in `setupRouterTestDB`, but some helper paths may bypass it; unify setup.

## Acceptance Criteria

- [ ] `go test -race -count=1 ./internal/api/...` passes without `no such table: audit_logs` warnings.
- [ ] No regression in audit log behavior for production (migrated) databases.
- [ ] Audit failures remain non-fatal to HTTP responses.

## References

- `internal/api/middleware/audit.go`
- `internal/api/router_test.go`
- `internal/services/audit_log_service.go`
