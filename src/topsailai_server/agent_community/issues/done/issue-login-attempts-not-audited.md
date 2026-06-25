---
maintainer: AI
status: fixed
related_files:
  - internal/api/handlers/account.go
  - internal/api/router.go
  - internal/api/handlers/account_test.go
  - internal/services/account_service.go
---
# Issue: Login attempts not audited

## Problem
The audit middleware only records actions for authenticated requests. The public login endpoint (`POST /api/v1/accounts/login`) is unauthenticated, so failed and successful login attempts were never written to the `audit_logs` table.

This caused `tests/integration/test_audit_logs_api.py::test_login_attempts_write_audit_log` to fail because only zero/one login-related audit log existed after a failed login followed by a successful login.

## Fix
1. Added `auditSvc` to `AccountHandler` so the login handler can write audit logs directly.
2. Updated `NewAccountHandler` signature and all call sites (`router.go`, `account_test.go`).
3. Added `GetAccountByLoginName` to `AccountService` for resolving the account on failed logins.
4. In `Login`, explicitly write `login_failed` audit logs for:
   - Account not found
   - Password not set
   - Account inactive
   - Invalid password
5. In `Login`, explicitly write a `login_success` audit log after credentials are validated and a session is created.

## Verification
- `go build ./...` succeeds.
- `tests/integration/test_audit_logs_api.py` passes (24/24).
