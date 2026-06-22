# Issue: Allow role=user to Query Accounts for Discovery

> **Status**: Fixed
> **Created**: 2026-06-22
> **Related Task**: api_key.role=user 可以查询accounts，这样才有办法知道account信息，从而将 account 加入group

## Problem

Previously, accounts with `role=user` (authenticated via API key) were blocked from listing or querying accounts other than their own. This prevented normal users from discovering other accounts' IDs and names, which is required to add those accounts as members to groups they own.

## Decision

Allow `role=user` to:

1. **List accounts**: Return all non-deleted accounts with the same limited field set used for `manager` (sensitive fields such as `login_password`, `login_session_key`, and API keys are omitted).
2. **Get account by ID**: Return any non-deleted account with the same limited field set.

Other account lifecycle operations remain restricted:

- `user` still cannot create, update, delete, or change passwords of other accounts.
- `user` still cannot create API keys for other accounts.
- `user` still cannot change their own `role` or `status`.

## Changes

### Source Code

- `internal/services/account_service.go`
  - Updated `ListAccounts` user branch to query all accounts where `status != deleted` instead of filtering to `account_id = callerID`.
- `internal/api/handlers/account.go`
  - Removed the early `403 Forbidden` for `role=user` in `ListAccounts`.
  - Updated `canViewAccount` to allow `role=user` to view any non-deleted account.

### Tests

- `internal/services/account_service_test.go`
  - Updated `TestAccountService_ListAccounts_FiltersAndVisibility` to assert users see all non-deleted accounts.
- `internal/api/handlers/account_test.go`
  - Updated `TestAccountHandler_ListAccounts_RoleFiltering`.
  - Updated `TestAccountHandler_GetAccount_AccessControl`.
  - Updated `TestCanViewAccount` to cover user viewing other accounts and deleted accounts.
  - Fixed pre-existing test setup to pass a valid context with client IP to service calls.
- `tests/integration/test_rbac_api.py`
  - Replaced `test_user_cannot_list_all_accounts` with `test_user_can_list_all_accounts`.
  - Replaced `test_user_can_only_access_own_account` with `test_user_can_access_any_non_deleted_account`.
  - Added `test_user_can_list_all_accounts` in `TestAPIKeyRBAC`.
  - Preserved existing `test_manager_cannot_create_api_key` coverage.
- `internal/api/handlers/group_test.go`
  - Updated `NewGroupHandler` call sites to pass the required `AuditLogService` dependency (pre-existing signature change).

### Documentation

- `docs/API.md`
  - Updated the authorization descriptions for `List Accounts` and `Get Account` to reflect that `role=user` can query all non-deleted accounts.
  - Updated the `Authorization Roles` summary.

## Security Considerations

- Sensitive fields (`login_password`, `login_session_key`, `login_session_expired_time`) are excluded from responses via model JSON tags and response DTOs.
- Soft-deleted accounts (`status=deleted`) are hidden from `role=user`.
- This change only expands read access; write and administrative permissions remain unchanged.

## Verification

- Run unit tests:
  ```bash
  go test ./internal/services/... ./internal/api/handlers/...
  ```
- Run integration tests:
  ```bash
  cd tests/integration && pytest test_rbac_api.py -v
  ```
