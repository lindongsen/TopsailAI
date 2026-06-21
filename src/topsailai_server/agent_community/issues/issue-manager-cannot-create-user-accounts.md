---
status: fixed
priority: high
created_by: AIMember.km1-tester
fixed_by: AIMember.km3-programmer
created_at: 2026-06-21T02:00:00Z
fixed_at: 2026-06-21T03:00:00Z
related_docs:
  - docs/API.md
  - docs/cases/TestCase_manual_cli_permissions.md
  - README.md
---

# Issue: Manager account cannot create user accounts

## Summary
A `manager` role account was unable to create a new account with `role=user` via `POST /api/v1/accounts`. The API documentation states that managers can create accounts with `role=user` only, but the server rejected the request.

## Environment
- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server binary: `./bin/acs-server`
- CLI binary: `./bin/acs-cli`
- Server port: `7370`
- Database: PostgreSQL (existing `acs` database)
- NATS: local server
- Test plan: `docs/cases/TestCase_manual_cli_permissions.md`
- Step: PERM-002

## Reproduction Steps
1. Start the ACS server without `ACS_ACCOUNT_ADMIN_API_KEY` or `ACS_ACCOUNT_MANAGER_API_KEY` set, so default admin/manager accounts are created.
2. Read the generated `.acs` files to obtain the manager API key token.
3. Start the CLI with the manager token:
   ```
   ./bin/acs-cli -api-base http://localhost:7370 -api-key <manager_token>
   ```
4. In the CLI, run:
   ```
   /account:create
   account_name: ManagerCreatedUser
   account_description: created by manager
   role: user
   login_name: manager-user-001@example.com
   login_password: TestPass123!
   external_id: ext-manager-user-001
   email: manager-user-001@example.com
   auth_provider: local
   avatar_url: https://example.com/avatar.png
   ```
5. Observe the response.

## Expected Behavior
The server should accept the request and create a new account with `role=user`.

## Actual Behavior (Before Fix)
The server rejected the request with HTTP `403 Forbidden`.

## Root Cause
The `CreateAccount` handler in `internal/api/handlers/account.go` did not pass the caller's role to the account service, and the service layer did not enforce the manager-only-creates-user rule. A prior fix for `issue-manager-can-create-admin-accounts.md` added the role check but only rejected manager creating admin/manager; it did not allow manager creating user because the caller role was not being propagated from the handler.

## Fix

### Changes Made
1. **`internal/api/handlers/account.go`**
   - Added an explicit active-account check at the start of `CreateAccount`.
   - Passed `CallerRole` to the service request.
   - Mapped `services.ErrRoleNotAllowed` to HTTP `403 Forbidden`.

2. **`internal/services/account_service.go`**
   - Added `CallerRole` to `CreateAccountRequest`.
   - Enforced the rule: if `CallerRole == manager` and requested role is not `user`, return `ErrRoleNotAllowed`.

3. **Tests**
   - `internal/api/handlers/account_test.go`: `TestAccountHandler_CreateAccount_ManagerUserOnly` verifies manager can create user and is forbidden from creating admin/manager.
   - `internal/services/account_service_test.go`: `TestAccountService_CreateAccount_ManagerUserOnly` verifies service-level enforcement.

### Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/ -run TestAccountHandler_CreateAccount -v   # PASS
go test ./internal/services/ -run TestAccountService_CreateAccount_ManagerUserOnly -v   # PASS
go test ./...   # PASS
make build      # PASS
```

## Related Code
- `internal/api/handlers/account.go` (`CreateAccount`)
- `internal/services/account_service.go` (`CreateAccount`)
- `internal/api/handlers/account_test.go`
- `internal/services/account_service_test.go`

## See Also
- `docs/API.md` > Account Endpoints > Create Account
- `README.md` > Account/Api_keys Roles
- `ORIGIN.md` > Account/Api_keys Roles
- `issues/issue-manager-can-create-admin-accounts.md`
