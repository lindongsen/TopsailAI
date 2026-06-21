---
maintainer: AI
status: fixed
severity: high
related_test: PERM-015
---

# Issue: CLI `/account:password` ignores `account-id` and changes current user's password

## Summary

The CLI command `/account:password account-id=<other-account> new-password=...` reports "Password updated" but actually changes the password of the currently authenticated account, not the target account specified by `account-id`. This causes the password change to silently fail for admins trying to reset another user's password.

## Environment

- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server: `./bin/acs-server` on `ACS_HTTP_PORT=7370`
- CLI: `./bin/acs-cli`
- Database: PostgreSQL `acs` on localhost
- NATS: `nats://localhost:4222`
- Date: 2026-06-21

## Reproduction Steps

1. Start the server and obtain the admin token from `ACS_ACCOUNT_ADMIN_API_KEY.acs`.
2. Create a user account (e.g., `user-a@acs.test`, `account_id=acc-6a26631c6bc54936aa6fb32f35e65bf8`).
3. In the admin CLI pane run:
   ```
   /account:password account-id=acc-6a26631c6bc54936aa6fb32f35e65bf8 new-password=AdminSet456
   ```
   Output: `Password updated`
4. Try to log in as the user with the new password:
   ```bash
   curl -s -X POST -H "Content-Type: application/json" \
     -d '{"login_name":"user-a@acs.test","login_password":"AdminSet456"}' \
     http://127.0.0.1:7370/api/v1/accounts/login
   ```
   Result: `{"error":"invalid credentials"}`
5. Server logs show the password request was actually sent to `/api/v1/accounts/<admin-account-id>/password`, not the target user account.

## Expected Behavior

When `account-id` is provided, the CLI should call `POST /api/v1/accounts/{account-id}/password` so that an admin can change another account's password. The new password should then work for login.

## Actual Behavior

The CLI always calls `POST /api/v1/accounts/me/password` (or the current account's password endpoint), ignoring the `account-id` argument. The command reports success but the target account's password remains unchanged.

## Evidence

- CLI output: `Password updated`
- Subsequent login with new password: `{"error":"invalid credentials"}`
- Server access log shows password change path points to the admin's own account ID, not the supplied `account-id`.
- Direct API call works correctly:
  ```bash
  curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
    -d '{"new_password":"AdminSet456Again"}' \
    http://127.0.0.1:7370/api/v1/accounts/acc-6a26631c6bc54936aa6fb32f35e65bf8/password
  # => {"message":"password changed"}
  ```
  Login with `AdminSet456Again` then succeeds.

## Impact

- Admins cannot reset user passwords through the CLI.
- The CLI gives false-positive feedback, misleading operators into believing the password was changed.
- Blocks completion of manual permission test PERM-015.

## Suggested Fix

Update the CLI's `/account:password` command implementation to:
1. Parse the `account-id` argument when present.
2. Use the parsed `account-id` in the API path (`/api/v1/accounts/{account-id}/password`).
3. Fall back to the current account only when `account-id` is omitted.

## Related Documentation

- `docs/API.md` — `POST /api/v1/accounts/:account_id/password`
- `docs/cases/TestCase_manual_cli_permissions.md` — PERM-015

## Fix Summary

Fixed by `AIMember.km3-programmer` on 2026-06-21.

### Root Cause
`handleAccountPassword` in `cmd/cli/commands.go` read only `params["id"]`, but the CLI command parser maps the documented argument name `account-id` to `params["account-id"]`. When `account-id` was provided, `params["id"]` was empty, so the handler fell back to `state.userID` (the current account).

### Changes
- `cmd/cli/commands.go`:
  - `handleAccountPassword` now reads `account-id` first and falls back to `id` for backward compatibility.
  - Updated inline comment and help text to reference `--account-id`.
- `cmd/cli/commands_test.go`:
  - Renamed `TestHandleAccountPassword` to `TestHandleAccountPasswordSelf` and switched it to use `--account-id`.
  - Added `TestHandleAccountPasswordAdminTargetsOtherAccount` to verify an admin can target a different account (`acc-2`) via `--account-id`.

### Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/... -v   # PASS
go test ./...              # PASS
make build                 # PASS
```

### Result
The CLI now calls `POST /api/v1/accounts/{account-id}/password` when `account-id` is supplied, and falls back to the current account only when it is omitted.
