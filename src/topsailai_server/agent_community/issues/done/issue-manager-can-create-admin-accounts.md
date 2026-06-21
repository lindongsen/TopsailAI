---
status: fixed
priority: high
created_by: AIMember.km1-tester
fixed_by: AIMember.km3-programmer
created_at: 2026-06-21T02:00:00Z
fixed_at: 2026-06-21T02:30:00Z
related_docs:
  - docs/API.md
  - docs/cases/TestCase_manual_cli_permissions.md
  - README.md
---

# Issue: Manager account can create admin accounts

## Summary
A `manager` role account was able to create a new account with `role=admin` via the CLI `/account:create` command. This violated the documented role hierarchy and permission model, which states that a manager can only create accounts with `role=user`.

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
   account_name: ManagerCreatedAdmin
   account_description: created by manager
   role: admin
   login_name: manager-admin-001@example.com
   login_password: TestPass123!
   external_id: ext-manager-admin-001
   email: manager-admin-001@example.com
   auth_provider: local
   avatar_url: https://example.com/avatar.png
   ```
5. Observe the response.

## Expected Behavior
The server should reject the request with HTTP `403 Forbidden` and an error such as:
```
manager can only create accounts with role=user
```
No account should be created.

## Actual Behavior (Before Fix)
The CLI returned a successful account creation response with `role=admin`, including a generated `account_id`, `creator_id` set to the manager account, and HTTP 200/201.

## Evidence
- CLI output showed a new account with `role: admin` and `creator_id: <manager_account_id>`.
- The manager API key was confirmed active with `role=manager` before the test.

## Impact
- **Security:** A manager could escalate privileges by creating admin accounts, bypassing the role hierarchy (`admin > manager > user`).
- **Compliance:** Violated documented API behavior in `docs/API.md` and `README.md`.
- **Testing:** Blocked completion of `TestCase_manual_cli_permissions.md` and all downstream manual test plans until fixed.

## Fix

### Root Cause
The `CreateAccount` handler in `internal/api/handlers/account.go` did not enforce the manager-only-creates-user constraint before calling the account service. The service layer also lacked a role-based caller check, so a manager could request any role and the account would be created.

### Changes Made
1. **`internal/services/account_service.go`**
   - Added `ErrRoleNotAllowed` to distinguish manager-role violations from invalid roles.
   - Added `CallerRole` to `CreateAccountRequest`.
   - Enforced the rule in `CreateAccount`: if `CallerRole == manager` and requested role is not `user`, return `ErrRoleNotAllowed`.

2. **`internal/api/handlers/account.go`**
   - Added an explicit active-account check at the start of `CreateAccount`.
   - Passed `CallerRole` to the service request.
   - Mapped `services.ErrRoleNotAllowed` to HTTP `403 Forbidden` with the message `manager can only create accounts with role=user`.
   - Mapped `services.ErrInvalidRole` to HTTP `400 Bad Request` with the message `invalid account role`.

3. **`internal/api/handlers/account_test.go`**
   - Added `TestAccountHandler_CreateAccount_Unauthenticated` to verify unauthenticated requests are rejected with `401 Unauthorized`.
   - Updated `TestAccountHandler_CreateAccount_ServiceError` to expect `400 Bad Request` for invalid role strings.

4. **`internal/services/account_service_test.go`**
   - Added `TestAccountService_CreateAccount_ManagerUserOnly` to verify service-level enforcement directly.

### Verification
Run the following commands:
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/ -run TestAccountHandler_CreateAccount -v
All tests pass.

## Related Code
- `internal/api/handlers/account.go` (`CreateAccount`)
- `internal/services/account_service.go` (`CreateAccount`)
- `internal/api/handlers/account_test.go`
- `internal/services/account_service_test.go`

## See Also
- `docs/API.md` > Account Endpoints > Create Account
- `README.md` > Account/Api_keys Roles
- `ORIGIN.md` > Account/Api_keys Roles
