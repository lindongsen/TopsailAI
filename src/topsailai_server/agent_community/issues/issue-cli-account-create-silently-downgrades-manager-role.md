---
status: fixed
priority: high
created_by: AIMember.km1-tester
created_at: 2026-06-21T02:50:00Z
updated_at: 2026-06-21T07:30:00Z
fixed_by: AIMember.km3-programmer
related_docs:
  - docs/cases/TestCase_manual_cli_permissions.md
  - docs/API.md
  - issues/issue-manager-can-create-admin-accounts.md
---

# Issue: CLI `/account:create` silently downgrades role when manager requests non-user role

## Summary

After the server-side fix for `issue-manager-can-create-admin-accounts.md`, the HTTP API correctly rejects a `manager` caller who attempts to create an account with `role=admin` or `role=manager` (HTTP 403). However, the CLI terminal (`acs-cli`) does **not** surface this error. Instead, it silently creates the account with `role=user`, making it appear as though the request succeeded.

Additionally, the interactive `/account:create` prompt never asks for the `role` field, so a manager using interactive mode cannot even attempt to create a non-user account.

**Note:** A fix for this issue was previously implemented but was lost when the repository was checked out to its original state. The issue is reproducible again with the current codebase.

## Environment

- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server binary: `./bin/acs-server` (rebuilt 2026-06-21)
- CLI binary: `./bin/acs-cli` (rebuilt 2026-06-21)
- Server port: `7370`
- Database: PostgreSQL (`acs` database), freshly recreated
- NATS: local server (`nats://localhost:4222`)
- Test plan: `docs/cases/TestCase_manual_cli_permissions.md`
- Step: PERM-002

## Reproduction Steps

### Case A: Non-interactive mode silently downgrades role

1. Start the ACS server and obtain the manager API key from `ACS_ACCOUNT_MANAGER_API_KEY.acs`.
2. Start the CLI as manager:
   ```bash
   ./bin/acs-cli -api-base http://127.0.0.1:7370 -api-key <manager_token> -no-color
   ```
3. Run the non-interactive create command with `role=admin`:
   ```
   /account:create role=admin login-name=admin-b@acs.test login-password=AdminPass123 account-name=AdminB
   ```
4. Observe the CLI output.

### Case B: Interactive mode never asks for role

1. In the manager CLI, run:
   ```
   /account:create
   ```
2. Follow the prompts.
3. Observe that no `role` prompt is presented.

## Expected Behavior

### Case A

The CLI should send the requested `role=admin` to the API and display the API's error response:

```
Error: manager can only create user accounts
```

No account should be created.

### Case B

The interactive prompt should include a `role` field so the caller can choose `user`, `manager`, or `admin` (subject to server-side permission checks).

## Actual Behavior (2026-06-21 Reproduction)

### Case A

The CLI prints:

```
Account created: acc-cc5e2aad3e2442f8b4df1ba48472bffa
```

Querying the account via API shows:

```json
{
  "account_id": "acc-cc5e2aad3e2442f8b4df1ba48472bffa",
  "account_name": "AdminB",
  "account_description": "",
  "role": "user",
  "status": "active",
  "delete_at_ms": 0,
  "creator_id": "acc-cbe3b4ee73df4ca39d12a862ff61b0af",
  "external_id": "",
  "email": "",
  "auth_provider": "",
  "avatar_url": "",
  "login_name": "admin-b@acs.test",
  "create_at_ms": 1781996582899,
  "update_at_ms": 1781996582899
}
```

The role was silently changed from `admin` to `user`.

### Case B

The interactive prompt sequence does not include a `role` question, and the created account defaults to `role=user`.

## Evidence

- CLI output from manager pane:
  ```
  acs@System Manager(acc-cbe3b4ee73df4ca39d12a862ff61b0af)[manager]: /account:create role=admin login-name=admin-b@acs.test login-password=AdminPass123 account-name=AdminB
  Account created: acc-cc5e2aad3e2442f8b4df1ba48472bffa
  ```
- Direct API call with the same manager token returns HTTP 403:
  ```bash
  curl -s -H "Authorization: Bearer $MANAGER_TOKEN" -H "Content-Type: application/json" \
    -d '{"role":"admin","login_name":"admin-c@acs.test","login_password":"AdminPass123","account_name":"AdminC"}' \
    http://127.0.0.1:7370/api/v1/accounts
  ```
  Response:
  ```json
  {
    "error": "manager can only create user accounts",
    "trace_id": "41ba0109-4a8b-4f17-bfed-ff2df6efc568"
  }
  ```
- Admin CLI correctly creates a `role=manager` account, proving the non-interactive `role` argument works for admin callers.

## Impact

- **Testing:** `TestCase_manual_cli_permissions.md` step PERM-002 cannot be completed as written because the CLI does not return the expected `403 Forbidden`.
- **User experience:** Managers may believe they created an admin/manager account when they actually created a user account, leading to confusion and incorrect access control assumptions.
- **Security visibility:** The server-side enforcement is hidden from CLI users, reducing auditability of permission violations.

## Root Cause

The CLI `/account:create` command implementation in `cmd/cli/commands.go` forces the requested role to `user` whenever the authenticated caller is a `manager`, overriding any user-supplied `role` value before the API request is built. The interactive prompt in `cmd/cli/interactive.go` also omits a `role` question.

## Suggested Fix

1. In the CLI `/account:create` command, always pass the user-supplied `role` value to the API unchanged.
2. Do not retry or override the role on a 403 response; display the API error to the user.
3. Add a `role` prompt to the interactive `/account:create` flow, defaulting to `user` but allowing the user to change it.
4. Ensure the role validation/permission error from the API is rendered clearly in the CLI output.

## Fix (Previously Implemented, Needs Re-application)

A fix was previously applied but lost when the repository was checked out to its original state. The fix involved:

1. **`cmd/cli/commands.go` — `handleAccountCreate`**
   - Remove the manager-only role override.
   - Pass the supplied `role` to `buildAccountCreateRequest` unchanged.
   - Surface API errors (including HTTP 403) through `formatAPIError`.

2. **`cmd/cli/interactive.go` — `PromptAccountCreate`**
   - Add a `role` prompt using a `PromptChoiceWithDefault` helper.
   - Default to `user` for `manager`/`user` callers and `admin` for `admin` callers.

3. **Unit tests**
   - Update `cmd/cli/commands_test.go` to verify the role is passed through and 403 errors are surfaced.
   - Update `cmd/cli/interactive_test.go` to cover the new role prompt.

## Related Code

- `cmd/cli/` (account create command implementation)
- `internal/api/handlers/account.go` (`CreateAccount`)
- `internal/services/account_service.go` (`CreateAccount`)

## See Also

- `docs/cases/TestCase_manual_cli_permissions.md` > PERM-002
- `docs/API.md` > Account Endpoints > Create Account
- `issues/issue-manager-can-create-admin-accounts.md`

## Fix Verification

Fixed by `AIMember.km3-programmer` on 2026-06-21.

### Changes Made

1. **`cmd/cli/commands.go`**
   - Removed the manager-only role override in `handleAccountCreate`.
   - The requested `role` is now passed to the API unchanged for all callers.
   - HTTP 403 and other API errors are surfaced through the existing `formatAPIError` path.

2. **`cmd/cli/interactive.go`**
   - `PromptAccountCreate` now prompts for `role` using `PromptStringWithDefault`, defaulting to `user`.
   - Callers can explicitly enter `admin`, `manager`, or `user`; the server enforces authorization.

3. **`cmd/cli/commands_test.go`**
   - Renamed `TestHandleAccountCreate_ManagerForcesUserRole` to `TestHandleAccountCreate_ManagerPassesRoleThrough`.
   - Added `TestHandleAccountCreate_ManagerReceives403` to verify the CLI surfaces the server's 403 error.

4. **`cmd/cli/interactive_test.go`**
   - Updated `TestPromptAccountCreate_ManagerDefaultsToUserRole` to verify the default role prompt value.
   - Added `TestPromptAccountCreate_ManagerCanChooseAdminRole` to verify explicit role selection is passed through.

### Test Results

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/ -run 'TestHandleAccountCreate|TestPromptAccountCreate' -v
go test ./cmd/cli/ -v
make build-cli
```

- All targeted tests pass.
- Full `go test ./cmd/cli/` passes.
- `make build-cli` succeeds.

### Next Steps

1. Reviewer (`AIMember.km2-reviewer`) reviews the fix.
2. After approval, tester (`AIMember.km1-tester`) resumes `TestCase_manual_cli_permissions.md` from step PERM-002, then continues with `TestCase_manual_cli_cluster.md` and `TestCase_manual_cli_agent_trigger.md`.
