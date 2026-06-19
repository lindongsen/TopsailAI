---
status: done
priority: high
component: api/account
---
# Manager cannot create login session for user account

## Symptom
POST /api/v1/accounts/{account_id}/session with a manager-role API key returned `403 access denied` for user accounts.

## Expected
Per API.md, a manager should be able to create login sessions only for accounts with `role=user`.

## Root Cause
In `internal/api/handlers/account.go`, the `CreateSession` handler correctly rejected manager-for-non-user in the first check, but the second generic authorization check (`ac.Account.Role != admin && ac.Account.AccountID != accountID`) then rejected manager-for-any-account-that-is-not-self before the manager/user allowance could take effect.

## Fix
Updated the second authorization check to explicitly allow managers creating sessions for user accounts.

## Files Changed
- `internal/api/handlers/account.go`
- `internal/api/handlers/account_test.go` (removed workaround, now asserts success)

## Verification
- `go test ./internal/api/handlers -run TestAccountHandler_CreateSession -count=1 -v` passes
- `go test ./internal/... -count=1` passes
