---
status: open
severity: medium
component: api
---

# Login for inactive account returns wrong HTTP status code

## Summary
`POST /api/v1/accounts/login` returns `401 Unauthorized` when the account exists but `status != active`. The API documentation specifies that this case should return `400 Bad Request`.

## Affected file
- `internal/api/handlers/account.go` (`Login`)

## Expected behavior
Per `docs/API.md`:
- `400 Bad Request` when "Account `status` is not `active`".
- `401 Unauthorized` only for invalid login name or password.

## Actual behavior
The current implementation returns `401 Unauthorized` for all login errors, including inactive accounts.

## Reproduction Steps
1. Create an account with `status=active` and a known password.
2. Use an admin API key to update the account `status` to `inactive`.
3. Attempt to log in with the correct `login_name` and `login_password`:
   ```bash
   curl -X POST http://localhost:7370/api/v1/accounts/login \
        -d '{"login_name":"alice@example.com","login_password":"secure-password"}'
   ```
4. Observe HTTP `401 Unauthorized`.
5. Expected: HTTP `400 Bad Request` with an error message indicating the account is inactive.

## Suggested fix
In `Login`, after verifying the password, check the account status before returning success. If `status != active`, return a `400 Bad Request` error:
```go
if account.Status != models.AccountStatusActive {
    c.JSON(http.StatusBadRequest, gin.H{"error": "account is not active"})
    return
}
```
Make sure the status check happens after password verification to avoid leaking whether an account exists for an invalid login name.

## Verification
- `go test ./internal/api/handlers/...` passes.
- New unit test: login with correct credentials but `status=inactive` returns `400`.
- New unit test: login with wrong password returns `401`.
- New unit test: login with correct credentials and `status=active` returns `200`.

## References
- `docs/API.md` "Login"
- `internal/api/handlers/account.go` `Login`
