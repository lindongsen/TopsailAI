---
maintainer: AI
status: open
related_files:
  - tests/integration/test_rbac_api.py
  - internal/api/handlers/account.go
  - internal/services/account_service.go
---

# RBAC Enforcement Gaps in Account and Session Endpoints

## Summary
Integration tests in `tests/integration/test_rbac_api.py` revealed several role-based access control gaps and response-format mismatches in the ACS account/session endpoints.

## Issues

### 1. Test code assumes wrapped JSON responses
- **Root cause**: `test_rbac_api.py` uses `response.json()["data"]` for all endpoints, but many ACS handlers return flat JSON objects (e.g., `GET /api/v1/accounts/:id`, group CRUD, message CRUD).
- **Impact**: 20 tests fail with `KeyError: 'data'` before any RBAC assertion runs.
- **Resolution**: Add a helper that returns the payload whether the response is wrapped (`{data, error, trace_id}`) or flat, and update tests to use it.

### 2. User can list all accounts
- **Root cause**: `ListAccounts` filters by role for non-admin callers but does not reject `user` role requests.
- **Expected**: `GET /api/v1/accounts` by a `user` role should return `403 Forbidden`.
- **Actual**: Returns `200 OK` with a filtered list.
- **Resolution**: Reject `user` role at the handler level; allow `admin` and `manager` only.

### 3. Manager can delete accounts
- **Root cause**: `DeleteAccount` allows the account owner to delete their own account, which permits a manager to delete their own account. The test expects only admins can delete any account.
- **Expected**: `DELETE /api/v1/accounts/:id` by `manager` should return `403 Forbidden`.
- **Actual**: Returns `200 OK`.
- **Resolution**: Restrict account deletion to `admin` role only.

### 4. Manager can create session for admin account
- **Root cause**: `CreateSession` role checks appear correct in code, but tests observe `200 OK`. Likely the same underlying issue as other manager checks or response-format confusion.
- **Expected**: `POST /api/v1/accounts/:id/session` by `manager` for an admin account should return `403 Forbidden`.
- **Actual**: Returns `200 OK`.
- **Resolution**: Harden the role checks in `CreateSession` and ensure manager is only allowed to create sessions for `user` accounts.

### 5. User cannot create own session
- **Root cause**: `CreateSession` logic rejects non-admin/non-owner callers before allowing the owner case.
- **Expected**: `POST /api/v1/accounts/:id/session` by a `user` for their own account should return `200 OK`.
- **Actual**: Returns `403 Forbidden`.
- **Resolution**: Reorder checks so that a user creating a session for their own account is allowed.

### 6. User updating own role/status returns 500
- **Root cause**: `UpdateAccount` passes disallowed role/status changes to the service, which returns a generic error mapped to `500 Internal Server Error`.
- **Expected**: `PUT /api/v1/accounts/:id` by a `user` attempting to change `role` or `status` should return `403 Forbidden`.
- **Actual**: Returns `500 Internal Server Error`.
- **Resolution**: Add handler-level validation for non-admin users: reject updates to `role` or `status` with `403`.

## Affected Files
- `tests/integration/test_rbac_api.py`
- `internal/api/handlers/account.go`
- `internal/services/account_service.go` (if service-level changes are needed)
