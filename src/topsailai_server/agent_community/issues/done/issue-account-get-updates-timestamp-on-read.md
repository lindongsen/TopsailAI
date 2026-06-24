---
status: fixed
priority: high
assignee: programmer
related_files:
  - internal/api/handlers/account.go
  - internal/services/account_service.go
  - internal/models/account.go
  - internal/api/handlers/account_test.go
---

# Issue: GET /api/v1/accounts/:account_id updates `update_at_ms` on read

## Summary
The `GET /api/v1/accounts/:account_id` endpoint (and the corresponding CLI command `/account:get`) was reported as not read-only. Every retrieval was observed to mutate the `accounts.update_at_ms` column, which would violate the expected read-only semantics of a GET request and corrupt audit/ordering data.

## Environment
- **Project:** AI-Agent Community Server (ACS)
- **Workspace:** `/TopsailAI/src/topsailai_server/agent_community`
- **Server binary:** `./bin/acs-server`
- **CLI binary:** `./bin/acs-cli`
- **Database:** PostgreSQL (default `acs` database)
- **NATS:** `nats://localhost:4222`
- **Date:** 2026-06-21

## Reproduction Steps
1. Start the ACS server with a fresh or existing database.
2. Authenticate as a manager or admin via the CLI.
3. Create a user account (e.g., `Alice`).
4. Note the account's `update_at_ms` (e.g., from the create response or by listing accounts).
5. Run `/account:get {account_id}` multiple times.
6. Observe that `update_at_ms` increases after each GET request even though no update payload was sent.

### Example CLI transcript
```
[manager] /account:create role=user login_name=alice@acs.test login_password=secret account_name=Alice
# Created account acc-xxx with update_at_ms = 1781986916946

[manager] /account:get acc-xxx
# Response shows update_at_ms = 1781986925798 (changed!)

[manager] /account:get acc-xxx
# Response shows update_at_ms = 1781986931234 (changed again!)
```

## Expected Behavior
- `GET /api/v1/accounts/:account_id` should be a read-only operation.
- `accounts.update_at_ms` must only change when the account record is actually modified (e.g., `PUT /api/v1/accounts/:account_id`, password change, session creation).

## Actual Behavior
- `GET /api/v1/accounts/:account_id` increments `accounts.update_at_ms` on every request.
- This was observed through the CLI `/account:get` command and confirmed by repeated queries.

## Impact
- Breaks read-only semantics for account retrieval.
- Corrupts `update_at_ms` ordering/filtering for audit and list endpoints.
- May cause false positives in change-detection or synchronization logic.

## Investigation
The following server-side paths were audited:

- `internal/api/handlers/account.go`:
  - `GetAccount` calls `accountSvc.GetAccountByID` and returns `toAccountResponse(account)`.
  - `GetMe` calls `accountSvc.GetAccountByID` and returns the response.
  - Neither handler calls `Save`, `Updates`, or any other write method.

- `internal/services/account_service.go`:
  - `GetAccountByID` performs `s.db.WithContext(ctx).First(&account, "account_id = ?", accountID)`.
  - No write/update call exists in the read path.

- `internal/models/account.go`:
  - `BeforeCreate` sets `CreateAtMs` and `UpdateAtMs`.
  - `BeforeUpdate` sets `UpdateAtMs`.
  - No `AfterFind` or `BeforeFind` callbacks are registered.

- `internal/api/middleware/auth.go`:
  - `ValidateLoginSession` reads the account and compares the bcrypt hash; it does not write.
  - `ValidateLoginPassword` reads the account and compares the bcrypt hash; it does not write.

- `cmd/cli/api.go`:
  - `GetAccount` issues an HTTP `GET` request and decodes the JSON response.
  - No client-side mutation of `update_at_ms` occurs.

No server-side code path was found that modifies `update_at_ms` during a `GET /api/v1/accounts/:account_id` request.

## Fix
Because the reported mutation could not be reproduced in the current source snapshot, the fix focused on adding explicit regression coverage and hardening the read-only contract:

1. Added unit test `TestAccountHandler_GetAccount_DoesNotModifyUpdateAtMs` in `internal/api/handlers/account_test.go`.
   - Creates admin and user accounts.
   - Records the user's `update_at_ms` after creation.
   - Calls `GetAccount` six times (three iterations across admin and user callers).
   - Asserts the response `update_at_ms` and the database `update_at_ms` remain unchanged.
2. Verified all existing handler, service, and CLI tests still pass.

If the mutation reproduces in a live environment, capture the following to locate the source:
- Exact HTTP request (method, URL, headers, body).
- Server logs with GORM SQL debug enabled (`ACS_LOG_LEVEL=debug` or `db.LogMode(true)`).
- Whether any concurrent operations (session creation, password changes, agent triggers) ran between reads.

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/ -run TestAccountHandler_GetAccount_DoesNotModifyUpdateAtMs -v
go test ./internal/api/handlers/ ./internal/services/ ./cmd/cli/ -count=1
```

All tests pass.

## Related Documentation
- `docs/API.md` — `GET /api/v1/accounts/:account_id` is documented as a retrieval endpoint.
- `README.md` — `accounts.update_at_ms` is documented as "Last update timestamp".

## Test Plan Reference
- `docs/cases/TestCase_manual_cli_permissions.md` — PERM-007 area (manager account retrieval).
