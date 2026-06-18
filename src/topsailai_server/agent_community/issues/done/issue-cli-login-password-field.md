# Issue: CLI login sends wrong password field

## Description
The CLI `/login` command sends `login_password` in the JSON body, but the server
handler `internal/api/handlers/account.go` expects the field to be named `password`
(see `LoginRequest.Password` with `json:"password"`).

This causes every password login from the CLI to fail with HTTP 400:
```
Key: 'LoginRequest.Password' Error:Field validation for 'Password' failed on the 'required' tag
```

## Affected file
- `cmd/cli/api.go` — `Login()` method payload uses `login_password`.

## Fix
Change the payload key from `login_password` to `password` in `cmd/cli/api.go`.

## Verification
After the fix, `/login` with valid credentials should return a session key and
the prompt should switch to session-key authentication.
