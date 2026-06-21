---
maintainer: human
status: open
priority: high
---

# Issue: Manager `/account:list` ignores role filter and returns deleted accounts

## Summary

A caller authenticated with a `manager` role API key can call `GET /api/v1/accounts?role=admin` and receive a 200 response containing accounts whose role is not `admin`, including at least one soft-deleted account (`status=deleted`). This violates the documented permission boundary that managers should only query limited account fields and should not see deleted accounts.

## Environment

- Project: AI-Agent Community Server (ACS)
- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server binary: `/TopsailAI/src/topsailai_server/agent_community/bin/acs-server`
- CLI binary: `/TopsailAI/src/topsailai_server/agent_community/bin/acs-cli`
- Database: PostgreSQL (existing dev instance)
- NATS: running locally
- Test date: 2026-06-21

## Reproduction Steps

1. Start the ACS server with a valid manager API key (or create one via admin).
2. Authenticate the CLI with the manager key:
   ```
   /login api-key=ak-xxx.yyyy
   ```
3. Run the list command with a role filter:
   ```
   /account:list role=admin
   ```
   (Equivalent direct API call: `GET /api/v1/accounts?role=admin` with manager Authorization header.)

## Expected Behavior

- The `role=admin` query parameter is honored.
- Only accounts matching `role=admin` are returned.
- Soft-deleted accounts (`status=deleted`) are excluded from the list.
- The response respects the manager-limited field set documented in `docs/API.md`.

## Actual Behavior

- HTTP 200 is returned.
- `total` is `10`.
- Returned items include accounts with `role=user` and `role=manager`.
- At least one returned account has `status=deleted`.
- No returned account has `role=admin`.

## Logs / Evidence

CLI output (truncated):
```
Total: 10
- acc-53a8554b804d4dd2a9ae5fbe074eac34 ... role=manager status=active
- acc-006af735b5e242daa43db6adb4c578cd ... role=manager status=active
- acc-84df0033098f4175a91709a693279eeb ... role=user    status=active
- acc-... role=user status=deleted
...
```

## Impact

- Information disclosure: managers can enumerate deleted accounts and accounts of other roles.
- Blocks completion of `TestCase_manual_cli_permissions.md` step **PERM-007** and downstream permission tests that rely on correct filtering.

## Related Documentation

- `docs/API.md` — List Accounts endpoint states managers can list accounts with limited fields.
- `docs/cases/TestCase_manual_cli_permissions.md` — PERM-007 expects role filtering to work for manager callers.

## Fix

TBD — pending programmer assignment.
## Fix

### Root Cause

`AccountService.ListAccounts` ignored the `role`, `status`, and `external_id` query parameters and did not enforce caller-visibility rules. The handler applied field masking for managers/users but left the underlying result set unfiltered, so managers received every account including soft-deleted ones.

### Changes

1. **`internal/services/account_service.go`**
   - Introduced `ListAccountsFilter` struct containing `Role`, `Status`, `ExternalID`, `CallerRole`, and `CallerID`.
   - Rewrote `ListAccounts` to apply query filters (`role`, `status`, `external_id`) directly in the database query.
   - Added visibility logic:
     - `admin`: sees all accounts, including deleted ones.
     - `manager`: sees only non-deleted (`status != deleted`) accounts with `role=user`, plus their own account.
     - `user`: sees only their own non-deleted account.
   - Sensitive fields (`login_password`, `login_session_key`) are still omitted by the handler's existing response mapping.

2. **`internal/api/handlers/account.go`**
   - Updated `ListAccounts` to build a `ListAccountsFilter` from query parameters and caller identity.
   - Hardened `canViewAccount` to deny access to deleted accounts for non-admin callers.
   - Added explicit role validation in `CreateAccount` so the server rejects disallowed roles even if the CLI forwards them unchanged.

3. **Tests**
   - `internal/services/account_service_test.go`: added `TestAccountService_ListAccounts_FiltersAndVisibility` covering role/status filters and caller visibility.
   - `internal/api/handlers/account_test.go`: updated `TestAccountHandler_ListAccounts_RoleFiltering` expectations to match the new visibility model.
   - `internal/services/bootstrap_test.go`: updated call sites to use the new `ListAccounts` signature.

### Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make build
go test ./internal/api/handlers/... ./internal/services/... ./cmd/cli/...
```

All affected tests pass and the server/CLI/natsctl binaries build successfully.

### Behavior After Fix

- `GET /api/v1/accounts?role=admin` as manager returns only non-deleted accounts with `role=admin` (or the manager's own account if it matches).
- Soft-deleted accounts are no longer visible to manager or user callers.
- Admin callers retain full visibility, including deleted accounts.
- Query parameters `role`, `status`, and `external_id` are honored for all callers.