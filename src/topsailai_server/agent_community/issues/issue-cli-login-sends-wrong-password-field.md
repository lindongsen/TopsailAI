---
status: fixed
priority: high
created_by: AIMember.km1-tester
created_at: 2026-06-21T03:00:00Z
fixed_by: AIMember.km3-programmer
fixed_at: 2026-06-21T04:15:00Z
related_docs:
  - docs/cases/TestCase_manual_cli_permissions.md
  - docs/API.md
---

# Issue: CLI login sends `password` instead of documented `login_password`

## Summary

The CLI `/login --login-name NAME --login-password PASS` command cannot authenticate because the API client sends the JSON field `password`, while the ACS server login endpoint expects `login_password` (as documented in `docs/API.md`). The server responds with HTTP 400 and a validation error.

## Environment

- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server binary: `./bin/acs-server`
- CLI binary: `./bin/acs-cli`
- Server port: `7370`
- Database: PostgreSQL (`acs` database)
- NATS: local server (`nats://localhost:4222`)
- Test plan: `docs/cases/TestCase_manual_cli_permissions.md`
- Step: PERM-015

## Reproduction Steps

1. Start the ACS server and obtain a valid login name + password (e.g., create a user account via admin CLI).
2. Start the CLI:
   ```bash
   ./bin/acs-cli -api-base http://127.0.0.1:7370 -no-color
   ```
3. Run:
   ```
   /login --login-name alice@example.com --login-password Password123!
   ```

## Expected Behavior

The CLI sends:
```json
{
  "login_name": "alice@example.com",
  "login_password": "Password123!"
}
```
The server validates the credentials and returns a session key.

## Actual Behavior

The CLI sends:
```json
{
  "login_name": "alice@example.com",
  "password": "Password123!"
}
```
The server responds:
```
HTTP 400: Key: 'LoginRequest.Password' Error:Field validation for 'Password' failed on the 'required' tag
```

## Evidence

- `docs/API.md` specifies the login request body as:
  ```json
  {
    "login_name": "alice@example.com",
    "login_password": "secure-password"
  }
  ```
- `cmd/cli/api.go` function `Login` builds the payload with `"password"`:
  ```go
  payload := map[string]interface{}{
      "login_name":     loginName,
      "password": loginPassword,
  }
  ```
- Direct curl with `login_password` succeeds:
  ```bash
  curl -s -X POST -H "Content-Type: application/json" \
    -d '{"login_name":"alice@example.com","login_password":"Password123!"}' \
    http://127.0.0.1:7370/api/v1/accounts/login
  ```

## Impact

- Password-based login is completely broken in the CLI.
- `TestCase_manual_cli_permissions.md` step PERM-015 cannot be completed via CLI.
- Users must use API keys or session keys as a workaround.

## Root Cause (Preliminary)

The `Login` method in `cmd/cli/api.go` uses the wrong JSON field name `password` instead of `login_password`.

## Suggested Fix

1. Change `cmd/cli/api.go` `Login()` to send `"login_password"` instead of `"password"`.
2. Update `cmd/cli/commands_test.go` `TestHandleLogin_LoginNamePassword` to assert `body["login_password"]` instead of `body["password"]`.

## Related Code

- `cmd/cli/api.go` (`Login`)
- `cmd/cli/commands_test.go` (`TestHandleLogin_LoginNamePassword`)
- `internal/api/handlers/account.go` (login handler, if server-side field name needs confirmation)

## See Also

- `docs/cases/TestCase_manual_cli_permissions.md` > PERM-015
- `docs/API.md` > Account Endpoints > Login
- `issues/issue-cli-login-missing-credentials-panic.md` (related but different issue)

## Fix

### Root Cause
The `Login` method in `cmd/cli/api.go` built the JSON payload with field name `"password"`, while the ACS server login endpoint and `docs/API.md` expect the field name `"login_password"`. This mismatch caused the server to reject every password-based login attempt with HTTP 400.

### Changes Made

1. **`cmd/cli/api.go`** — Changed the `Login` payload field from `"password"` to `"login_password"`:
   ```go
   payload := map[string]interface{}{
       "login_name":     loginName,
       "login_password": loginPassword,
   }
   ```

2. **`cmd/cli/api_test.go`** — Updated `TestAPIClientLogin` to assert `payload["login_password"]` instead of `payload["password"]`.

3. **`cmd/cli/commands_test.go`** — Updated `TestHandleLogin_LoginNamePassword` to assert `body["login_password"]` instead of `body["password"]`.

### Test Commands

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/ -run 'TestAPIClientLogin|TestHandleLogin' -v
```

### Verification

All login-related tests pass:
- `TestAPIClientLogin`
- `TestHandleLogin_APIKey`
- `TestHandleLogin_SessionKey`
- `TestHandleLogin_LoginNamePassword`
- `TestHandleLogin_MissingCredentials`

### Status

Fixed. Pending reviewer approval and manual re-test of `TestCase_manual_cli_permissions.md` step PERM-015.
