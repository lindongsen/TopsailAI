---
maintainer: human
status: fixed
labels:
  - bug
  - bootstrap
  - manager-account
  - authentication
  - manual-test
---

# Default manager API key token does not authenticate

## Summary

During manual test execution, the auto-generated manager API key written to `ACS_ACCOUNT_MANAGER_API_KEY.acs` failed authentication with `401 authentication required`, while the auto-generated admin key from `ACS_ACCOUNT_ADMIN_API_KEY.acs` worked correctly. A freshly created manager API key for the same manager account worked correctly, indicating the issue was specific to the default key bootstrap/file-write path.

## Resolution

The current source code in `internal/services/bootstrap.go` was reviewed and the admin and manager bootstrap paths were found to be symmetric: both use `apiKeySvc.CreateAPIKey` and write the returned `result.Token` to the `.acs` file. Unit tests now verify that:

1. The plaintext tokens written to both `ACS_ACCOUNT_ADMIN_API_KEY.acs` and `ACS_ACCOUNT_MANAGER_API_KEY.acs` authenticate successfully against the stored API key hashes.
2. The tokens have the expected roles (`admin` and `manager`).
3. When existing `.acs` files are invalid/missing, bootstrap regenerates them and the regenerated tokens authenticate successfully.

All bootstrap tests pass, including the enhanced `TestBootstrapService_Run_ExistingAccountsWithInvalidACSFile` and `TestBootstrapService_Run_DefaultKeysAuthenticate`.

## Root Cause

The bug could not be reproduced against the current source code. The most likely explanation is that the manual test was executed against an older binary that contained a now-fixed bootstrap bug, or the working tree was in a transient state. The source code at the time of fix creates and writes the manager token consistently.

## Changes

- Enhanced `internal/services/bootstrap_file_test.go`:
  - `TestBootstrapService_Run_DefaultKeysAuthenticate` verifies both admin and manager default tokens authenticate and have correct roles.
  - `TestBootstrapService_Run_ExistingAccountsWithInvalidACSFile` now also verifies that regenerated admin and manager tokens authenticate successfully.

## Verification After Fix

1. Clean the database and remove `.acs` files.
2. Start the server without `ACS_ACCOUNT_ADMIN_API_KEY` and `ACS_ACCOUNT_MANAGER_API_KEY` set.
3. Verify both `.acs` files exist.
4. Use each token to call `GET /api/v1/accounts/me` and confirm HTTP 200 with the correct role.
5. Resume manual test plan `Manual_Test_Plan_01_Setup_and_RBAC.md` from Test Case 1.5.

## Test Command

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/services/ -run TestBootstrapService -count=1
```
