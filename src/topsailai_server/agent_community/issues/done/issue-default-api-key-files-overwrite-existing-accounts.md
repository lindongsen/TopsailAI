---
status: fixed
severity: high
created: 2026-06-21
related: docs/Environment_Variables.md, README.md, ORIGIN.md
---

# Issue: Default API key files are overwritten with non-matching tokens when default accounts already exist

## Summary

When ACS starts and the default `admin`/`manager` accounts already exist in the database, the server skips creating new default accounts (correct behavior) but still writes new plaintext API key files (`ACS_ACCOUNT_ADMIN_API_KEY.acs` and `ACS_ACCOUNT_MANAGER_API_KEY.acs`) to the working directory. The newly written tokens do **not** match the existing API key hashes stored in the database, making the files unusable and causing all authentication attempts with them to fail with HTTP 401.

## Environment

- ACS commit/workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Database: PostgreSQL, `acs` database
- NATS: `nats://localhost:4222` with JetStream enabled
- Server binary: `./bin/acs-server`
- CLI binary: `./bin/acs-cli`
- Test command/working directory: `/TopsailAI/src/topsailai_server/agent_community`

## Reproduction Steps

1. Ensure the database contains existing system default accounts and API keys (e.g., from a previous server startup):

```sql
SELECT account_id, role, creator_id FROM accounts WHERE creator_id = 'system';
SELECT api_key_id, role, owner_id FROM api_keys WHERE creator_id = 'system';
```

2. Remove any previous `.acs` key files from the working directory:

```bash
cd /TopsailAI/src/topsailai_server/agent_community
rm -f ACS_ACCOUNT_ADMIN_API_KEY.acs ACS_ACCOUNT_MANAGER_API_KEY.acs
cd cmd/server
rm -f ACS_ACCOUNT_ADMIN_API_KEY.acs ACS_ACCOUNT_MANAGER_API_KEY.acs
```

3. Start the server without setting `ACS_ACCOUNT_ADMIN_API_KEY` or `ACS_ACCOUNT_MANAGER_API_KEY`:

```bash
export ACS_HOME=/tmp/acs-manual-test
export ACS_DATABASE_DRIVER=postgres
export ACS_DATABASE_HOST=localhost
export ACS_DATABASE_PORT=5432
export ACS_DATABASE_USER=acs
export ACS_DATABASE_PASSWORD=acs
export ACS_DATABASE_NAME=acs
export ACS_NATS_SERVERS=nats://localhost:4222
export ACS_DISCOVERY_ENABLED=true
ACS_HTTP_PORT=7370 ./bin/acs-server
```

4. Observe the server logs:

```json
{"message":"admin account already exists, skipping default creation"}
{"message":"manager account already exists, skipping default creation"}
```

5. Read the newly generated key files:

```bash
cat cmd/server/ACS_ACCOUNT_ADMIN_API_KEY.acs
cat cmd/server/ACS_ACCOUNT_MANAGER_API_KEY.acs
```

6. Attempt to authenticate with either token:

```bash
curl -s -H "Authorization: Bearer $(cat cmd/server/ACS_ACCOUNT_ADMIN_API_KEY.acs)" \
  http://127.0.0.1:7370/api/v1/accounts/me | jq .
```

## Expected Behavior

Per `docs/Environment_Variables.md` and `README.md`:

> If `ACS_ACCOUNT_ADMIN_API_KEY` is not set, ACS generates a default admin account and API key, then writes the plaintext key to `ACS_ACCOUNT_ADMIN_API_KEY.acs` in the process working directory.

When the default accounts **already exist**, the server should either:

1. Not overwrite the `.acs` files if it cannot recover the existing plaintext secrets, OR
2. Write files only when it actually creates new default accounts, OR
3. Provide a clear error/warning that the existing keys are in the database and the `.acs` files do not match.

In all cases, the files written to disk should be valid for authentication, or the operator should be explicitly informed that they are not valid.

## Actual Behavior

- The server logs say default accounts already exist and are skipped.
- New `.acs` files are still written to `cmd/server/ACS_ACCOUNT_*.acs`.
- The tokens in those files do not exist in the `api_keys` table.
- Authentication attempts with the files return HTTP 401.
- Server log shows:

```
SELECT * FROM "api_keys" WHERE api_key_id = 'ak-b8b419a819b746c2b4d6f63f6791bd03' ORDER BY ... LIMIT 1
record not found
```

## Evidence

Database state at time of failure:

```text
accounts:
  acc-364208b3cad04aceb35f708bea671cc7 | admin   | system
  acc-bf723e4430874ed3b0a3c19a2bbfe650 | manager | system

api_keys:
  ak-53a8554b804d4dd2a9ae5fbe074eac34 | admin   | acc-364208b3cad04aceb35f708bea671cc7
  ak-006af735b5e242daa43db6adb4c578cd | manager | acc-bf723e4430874ed3b0a3c19a2bbfe650
```

File system state after startup:

```text
File: cmd/server/ACS_ACCOUNT_ADMIN_API_KEY.acs
Modify: 2026-06-21 00:34:17
Content: ak-b8b419a819b746c2b4d6f63f6791bd03.TYy2o7HSgiGEtA5WwT0SR24SuIRrMRu3Ae6RAdus_9A

File: cmd/server/ACS_ACCOUNT_MANAGER_API_KEY.acs
Modify: 2026-06-21 00:34:19
Content: ak-8b50d55853744aab8b74eb0fc9a783f7.9j7CieJAWSFye6PkXiG3ZGWtSJWCDg8MPVz7qJhFNtI
```

The `api_key_id` values in the files (`ak-b8b419a819b746c2b4d6f63f6791bd03`, `ak-8b50d55853744aab8b74eb0fc9a783f7`) do not match the `api_key_id` values in the database (`ak-53a8554b804d4dd2a9ae5fbe074eac34`, `ak-006af735b5e242daa43db6adb4c578cd`).

## Impact

- All manual/automated tests that rely on reading the auto-generated `.acs` files fail at the first authentication step.
- Operators following the README "Getting Started" instructions will receive 401 errors after any restart that preserves the database.
- The generated files are misleading security artifacts (plaintext secrets that do not correspond to any valid credential).

## Suggested Fix

In the bootstrap/default-account creation logic:

1. When default accounts already exist, skip writing `.acs` files entirely, OR
2. Before writing a new `.acs` file, check whether an active API key for the default account already exists and log a warning that the existing key cannot be recovered, OR
3. If the intent is to regenerate keys, delete the old API keys and create new ones atomically, then write the matching plaintext files.

At minimum, the server must not write `.acs` files containing tokens that do not authenticate.

## Workaround

Set `ACS_ACCOUNT_ADMIN_API_KEY` and `ACS_ACCOUNT_MANAGER_API_KEY` to valid existing tokens, or delete the system default accounts/keys from the database before each fresh startup.

## Related Documentation

- `docs/Environment_Variables.md` — "Account & API Key Configuration"
- `README.md` — "Default Accounts"
- `ORIGIN.md` — "Default Accounts (admin/manager role)"


## Fix

### Root Cause

The bootstrap logic in `internal/services/bootstrap.go` already skipped default account creation when an active account with the target role existed. However, the original implementation did not verify whether a plaintext `.acs` token file on disk matched the existing database key. In some code paths the file was still being written with a freshly generated token even though no new API key was created, producing a token that did not exist in the database.

### Changes Made

1. **`internal/services/bootstrap.go`**
   - Added `verifyExistingTokenFile(role, filePath)` helper.
     - If the `.acs` file exists and is non-empty, it parses the token and validates it against the database using the existing `validateConfiguredToken` logic.
     - On success it logs an info message confirming the file matches the active key.
     - On failure (missing file, empty file, parse error, unknown key, wrong role, inactive key) it logs a clear warning and **does not modify the file**.
   - Updated `ensureAdminAccount` and `ensureManagerAccount` to call `verifyExistingTokenFile` when the corresponding default account already exists, instead of writing a new file.
   - Kept the existing behavior for the "account does not exist" path: create the account, create the API key, and write the plaintext token to the `.acs` file.
   - Kept the existing behavior for the "env var is configured" path: validate the configured token and fail fast if it does not match an active key with the expected role.

2. **`internal/services/bootstrap_file_test.go`**
   - Added `TestBootstrapService_Run_ExistingAccountsMissingACSFile` — verifies that no `.acs` files are created when default accounts already exist and no files are present.
   - Added `TestBootstrapService_Run_ExistingAccountsWithValidACSFile` — verifies that a pre-existing valid `.acs` file is left untouched and still matches the database key.
   - Added `TestBootstrapService_Run_ExistingAccountsWithInvalidACSFile` — verifies that a pre-existing invalid `.acs` file is not overwritten with a new mismatched token.

### Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/services/ -run TestBootstrapService -v
```

All bootstrap tests pass, including the new file-verification tests.

### Behavior After Fix

- If default accounts do not exist and no env var is set: new accounts/keys are created and matching `.acs` files are written.
- If default accounts already exist and no env var is set: no new keys are generated, no `.acs` files are written, and any existing `.acs` files are verified (with a warning logged if they do not match).
- If env vars are set: they must match existing active keys with the expected role, otherwise the server exits with a clear configuration error.

### Files Modified

- `internal/services/bootstrap.go`
- `internal/services/bootstrap_file_test.go`
- `issues/issue-default-api-key-files-overwrite-existing-accounts.md` (this file)
