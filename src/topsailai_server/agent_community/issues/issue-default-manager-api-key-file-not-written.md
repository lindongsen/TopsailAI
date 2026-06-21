---
maintainer: human
status: open
labels:
  - bug
  - bootstrap
  - manager-account
  - cli-testing
---

# Default manager API key file is not written during bootstrap

## Summary

When ACS starts without `ACS_ACCOUNT_MANAGER_API_KEY` set and creates a default `manager` account, the server logs that it created the account and wrote the plaintext token to `ACS_ACCOUNT_MANAGER_API_KEY.acs`, but the file is never created in the process working directory. This prevents CLI/API authentication as the default manager and blocks manager-role permission tests.

## Environment

- Project: AI-Agent Community Server (ACS)
- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Build: `make build` (acs-server, acs-cli, natsctl)
- Database: PostgreSQL (`acs` database)
- NATS: local server with JetStream enabled
- OS: Debian GNU/Linux 13
- Go version: 1.25

## Reproduction Steps

1. Clean the database (drop/recreate `acs` database or truncate `accounts`, `api_keys`, `groups`, `group_member`, `group_messages`, `audit_logs`).
2. Remove any existing `.acs` files from the process working directory:
   ```bash
   rm -f ACS_ACCOUNT_ADMIN_API_KEY.acs ACS_ACCOUNT_MANAGER_API_KEY.acs
   ```
3. Ensure `ACS_ACCOUNT_ADMIN_API_KEY` and `ACS_ACCOUNT_MANAGER_API_KEY` are **not** set in the environment.
4. Start the server from the project root:
   ```bash
   cd /TopsailAI/src/topsailai_server/agent_community
   ./bin/acs-server
   ```
5. Observe the server logs:
   - `created default admin account ... file: ACS_ACCOUNT_ADMIN_API_KEY.acs`
   - `created default manager account ... file: ACS_ACCOUNT_MANAGER_API_KEY.acs`
6. Check the working directory:
   ```bash
   ls -la ACS_ACCOUNT_*.acs
   ```

## Expected Behavior

Both files should exist and contain valid plaintext tokens matching the records in the `api_keys` table:

- `ACS_ACCOUNT_ADMIN_API_KEY.acs`
- `ACS_ACCOUNT_MANAGER_API_KEY.acs`

## Actual Behavior

Only `ACS_ACCOUNT_ADMIN_API_KEY.acs` is created. `ACS_ACCOUNT_MANAGER_API_KEY.acs` is missing even though the log claims it was written.

Example server log excerpt:

```
INFO    bootstrap/default_accounts.go:...   created default admin account   {"account_id": "acc-...", "api_key_id": "ak-...", "file": "ACS_ACCOUNT_ADMIN_API_KEY.acs"}
INFO    bootstrap/default_accounts.go:...   created default manager account {"account_id": "acc-...", "api_key_id": "ak-...", "file": "ACS_ACCOUNT_MANAGER_API_KEY.acs"}
```

After startup:

```bash
$ ls -la ACS_ACCOUNT_*.acs
-rw------- 1 user user 79 Jun 21 01:55 ACS_ACCOUNT_ADMIN_API_KEY.acs
```

`ACS_ACCOUNT_MANAGER_API_KEY.acs` is absent.

## Impact

- Cannot authenticate as the default manager via CLI or API.
- Blocks all manager-role permission tests in `TestCase_manual_cli_permissions.md` (e.g., PERM-002, PERM-005, PERM-007).
- Blocks any workflow that relies on the auto-generated manager token file.

## Workaround

None known for the auto-generated manager token. The only workaround is to manually create a manager API key using an admin token, but this defeats the purpose of the default manager account bootstrap.

## Suggested Fix

Inspect the default account bootstrap logic (likely under `internal/bootstrap/` or `internal/services/account_service.go`). Compare the admin and manager file-write paths. The manager path likely:

- Fails silently when writing the file, or
- Does not call the file-write function at all, or
- Uses an incorrect filename/path variable.

Ensure the manager plaintext token is written to the working directory with the same permissions and error handling as the admin token.

## Related Files

- `internal/bootstrap/default_accounts.go` (likely location)
- `internal/services/account_service.go`
- `internal/models/api_key.go`
- `docs/Environment_Variables.md`
- `docs/cases/TestCase_manual_cli_permissions.md`

## Verification After Fix

1. Clean the database and remove `.acs` files.
2. Start the server.
3. Verify both `ACS_ACCOUNT_ADMIN_API_KEY.acs` and `ACS_ACCOUNT_MANAGER_API_KEY.acs` exist.
4. Use each token to call `GET /api/v1/accounts/me` and confirm HTTP 200 with the correct role.
5. Resume `TestCase_manual_cli_permissions.md` from PERM-002.

## Fix

**Status:** Fixed in current source snapshot.

### Root Cause

The default-account bootstrap logic in `internal/services/bootstrap.go` had separate `ensureAdminAccount` and `ensureManagerAccount` implementations. The manager path was not actually invoking the file-write helper after creating the default manager API key, even though the success log message claimed the file was written. The admin path and manager path had diverged, so the manager token was generated and stored in the database but never persisted to the `.acs` file.

### Changes Made

- Refactored `ensureAdminAccount` and `ensureManagerAccount` into a single shared helper `ensureDefaultAccount(ctx, role, envVarName, fileName)` so admin and manager bootstrap behave identically.
- Updated `writeTokenFile` to return the absolute path of the written file and to verify that the file is readable after writing.
- Added explicit success logging that includes the absolute file path for both admin and manager token files.
- Updated `internal/services/bootstrap_test.go`:
  - Renamed/replaced the old admin-only file-creation test with `TestBootstrapService_ensureDefaultAccount_AdminNoKeyCreatesFile` and added `TestBootstrapService_ensureDefaultAccount_ManagerNoKeyCreatesFile`.
  - Updated `writeTokenFile` tests to match the new `(string, error)` signature.

### Files Modified

- `internal/services/bootstrap.go`
- `internal/services/bootstrap_test.go`

### Tests

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/services/ -run TestBootstrapService -v
go test ./internal/services/ ./internal/api/handlers/ ./cmd/cli/ -count=1
```

All tests pass.

### Verification After Fix

1. Clean the database and remove `.acs` files.
2. Start the server without `ACS_ACCOUNT_ADMIN_API_KEY` and `ACS_ACCOUNT_MANAGER_API_KEY` set.
3. Verify both `ACS_ACCOUNT_ADMIN_API_KEY.acs` and `ACS_ACCOUNT_MANAGER_API_KEY.acs` exist in the working directory.
4. Use each token to call `GET /api/v1/accounts/me` and confirm HTTP 200 with the correct role.
5. Resume `TestCase_manual_cli_permissions.md` from PERM-002.
