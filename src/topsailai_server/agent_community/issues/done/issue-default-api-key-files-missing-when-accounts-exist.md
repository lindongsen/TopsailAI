---
maintainer: AI
status: fixed
related_files:
  - internal/services/bootstrap.go
  - internal/services/bootstrap_test.go
  - internal/services/bootstrap_file_test.go
---

# Issue: Default API key `.acs` files are not written when default accounts already exist

## Summary
When the ACS server starts and default `admin`/`manager` accounts already exist in the database, the bootstrap logic skipped both account creation **and** writing the plaintext `.acs` key files. If those files were missing, operators could not authenticate with the default accounts.

## Root Cause
`ensureDefaultAccount` returned early when it detected an existing account, so `ensureTokenFile` was never invoked. The plaintext secret is not stored in the database, so a missing file could not be recovered without creating a new API key.

## Fix
Updated `internal/services/bootstrap.go`:
- `ensureDefaultAccount` now always calls `ensureTokenFile` for the resolved default account, regardless of whether the account was just created or already existed.
- `ensureTokenFile` validates the existing `.acs` file (if any) against the database. If the file is missing or invalid, it deletes stale system-generated API keys for the account, creates a fresh API key, and writes the new plaintext token to the `.acs` file.
- Clear logging is emitted when regenerating files.

Because the plaintext secret is not retained in the database, the implementation cannot "regenerate from the existing key"; instead it rotates the default system key and writes the new token. This is safe because the `.acs` file is the intended source of truth for default local access.

## Tests
- Fixed compilation errors in `internal/services/bootstrap_test.go` (updated `ListAccounts` signature, `writeTokenFile` return values, and removed tests for non-existent helper methods).
- Rewrote `internal/services/bootstrap_file_test.go` to cover:
  - Existing account, missing `.acs` file -> file regenerated.
  - Existing account, valid `.acs` file -> file preserved and key count unchanged.
  - Existing account, invalid `.acs` file -> file regenerated and stale system keys rotated.

## Verification
- `go test ./...` -> PASS
- `make build` -> OK

## Remaining Work
Manual testing can now resume. `km1-tester` should rebuild the server, restart the test environment, and continue from `TestCase_manual_cli_permissions.md` (or from the step that was blocked).
