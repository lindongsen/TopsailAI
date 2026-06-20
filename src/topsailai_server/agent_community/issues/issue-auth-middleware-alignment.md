---
status: fixed
related_files:
  - internal/api/middleware/auth.go
  - internal/api/middleware/auth_test.go
  - internal/services/account_service.go
---
# Issue: Auth middleware authentication priority and methods did not match docs

## Problem

While adding unit tests for `internal/api/middleware/auth.go` (Assignment #9), the following discrepancies between the implementation and project documentation were found:

1. **Missing login name/password authentication in middleware.**
   - `docs/API.md` and `README.md` list "Login Name / Password" as an authentication method and state the priority `login_name_password > login_session_key > api_key`.
   - The middleware only supported API key (`Authorization: Bearer`) and session key (`X-Session-Key`) headers.

2. **Wrong authentication priority.**
   - The middleware checked API key before session key, which contradicts the documented priority `session key > API key`.

3. **Client IP not stored in request context.**
   - Audit logging and request logging rely on `c.ClientIP()`, but the value was not placed in the request context for downstream middleware/helpers to retrieve consistently.

## Root Cause

- The middleware was implemented with only two authentication branches (API key, then session key).
- No helper existed to validate login credentials without creating a new session.
- No `clientIPContextKey` was defined or populated.

## Fix

1. Added `ValidateLoginPassword` to `internal/services/account_service.go`.
   - Validates `login_name` + `login_password` using the existing bcrypt hash.
   - Does **not** create a new session, making it suitable for middleware authentication.

2. Updated `internal/api/middleware/auth.go`.
   - Added login name/password branch using headers `X-Login-Name` and `X-Login-Password`.
   - Reordered priority to: login name/password → session key → API key.
   - Added `clientIPContextKey` and populated it with `c.ClientIP()` after successful authentication.

3. Added/updated unit tests in `internal/api/middleware/auth_test.go`.
   - `TestAuthentication_LoginPassword_Success`
   - `TestAuthentication_LoginPassword_Invalid`
   - `TestAuthentication_Priority_LoginOverSession`
   - `TestAuthentication_Priority_SessionOverAPIKey`
   - `TestAuthentication_SessionKey_Expired`
   - `TestAuthentication_ClientIP`
   - `TestRequireRole_ManagerDeniedAdmin`
   - `TestRequireRole_UserDeniedManager`

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community && go test -race ./internal/api/middleware/...
```

Result: `ok`

## Impact

- Middleware behavior now aligns with documented authentication methods and priority.
- Downstream audit/logging can retrieve `clientIP` from context via `GetClientIP(c)`.
- No breaking changes to existing API key or session key authentication.
