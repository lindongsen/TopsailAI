---
status: fixed
priority: high
created_by: AIMember.km1-tester
created_at: 2026-06-21T03:05:00Z
fixed_by: AIMember.km3-programmer
fixed_at: 2026-06-21T04:15:00Z
related_docs:
  - docs/cases/TestCase_manual_cli_permissions.md
  - docs/API.md
---

# Issue: CLI `/api-key:create` ignores inline account-id argument and concatenates with prompt default

## Summary

The CLI `/api-key:create` command does not accept a bare positional account ID (e.g. `/api-key:create acc-xxx --name MyKey`). When invoked this way, it falls through to the interactive prompt, which pre-fills the current user's account ID as the default. The typed account ID is then concatenated with the default value, producing an invalid account ID like `acc-admin001acc-xxx` and causing HTTP 404 `owner account not found`.

## Environment

- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server binary: `./bin/acs-server`
- CLI binary: `./bin/acs-cli`
- Server port: `7370`
- Database: PostgreSQL (`acs` database)
- NATS: local server (`nats://localhost:4222`)
- Test plan: `docs/cases/TestCase_manual_cli_permissions.md`
- Step: PERM-004

## Reproduction Steps

1. Start the ACS server and authenticate the CLI as an admin.
2. Create a second account (e.g., `acc-9cf4...`) via `/account:create`.
3. Attempt to create an API key for that account using a positional argument:
   ```
   /api-key:create acc-9cf4... --name TestKey --role user
   ```

## Expected Behavior

The CLI immediately calls `POST /api/v1/accounts/acc-9cf4.../api-keys` with the provided name and role, without prompting.

## Actual Behavior

The CLI enters an interactive prompt:
```
Creating an API key. Press Ctrl+C or Enter without input to cancel.
Account ID [acc-e565...]: acc-9cf4...
```
The resulting account ID sent to the server is `acc-e565...acc-9cf4...`, which returns:
```
HTTP 404: owner account not found
```

## Evidence

- `cmd/cli/commands.go` `handleAPIKeyCreate` only reads `params["account-id"]` and `params["name"]` from `parseInlineArgs`. It does not support a bare positional account ID.
- `parseInlineArgs` does not map bare positional arguments to `account-id`.
- `PromptAPIKeyCreate` uses `PromptStringWithDefault("Account ID", callerID)`, which displays the current user's ID as the default and concatenates input under tmux/readline in some cases.
- Other commands such as `/account:get` and `/group:enter` already support bare positional arguments using `args[0]`.

## Impact

- Admins cannot create API keys for other accounts via inline CLI commands.
- `TestCase_manual_cli_permissions.md` step PERM-004 is blocked unless the CLI is restarted and the command is run interactively.
- The concatenated account ID is confusing and produces a misleading 404 error.

## Root Cause (Preliminary)

`handleAPIKeyCreate` lacks the bare-positional-argument fallback that other commands use. Additionally, the interactive prompt default may be concatenated with user input when the readline buffer is not fully cleared.

## Suggested Fix

1. In `cmd/cli/commands.go`, update `handleAPIKeyCreate` to resolve the account ID from, in order:
   - `params["account-id"]` (e.g. `--account-id acc-xxx` or `account-id=acc-xxx`)
   - First bare positional argument (e.g. `/api-key:create acc-xxx --name MyKey`)
   - Interactive prompt fallback (only when no inline value is provided)
2. Add unit tests for inline argument parsing of `/api-key:create`.
3. Consider also supporting `key-id` positional argument for `/api-key:delete` for consistency.

## Related Code

- `cmd/cli/commands.go` (`handleAPIKeyCreate`, `handleAPIKeyDelete`)
- `cmd/cli/interactive.go` (`PromptAPIKeyCreate`, `PromptStringWithDefault`)
- `cmd/cli/commands_test.go`

## See Also

- `docs/cases/TestCase_manual_cli_permissions.md` > PERM-004
- `docs/API.md` > API Key Endpoints > Create API Key
- `issues/issue-cli-account-get-inline-arg-ignored.md` (similar fix pattern)

## Fix

### Root Cause
`handleAPIKeyCreate` in `cmd/cli/commands.go` only checked `params["account-id"]` from `parseInlineArgs`. It ignored bare positional arguments, so commands like `/api-key:create acc-xxx --name MyKey` fell through to the interactive prompt. The prompt default (current user's account ID) was then concatenated with typed input, producing an invalid account ID.

### Changes Made

1. **`cmd/cli/commands.go`** — Updated `handleAPIKeyCreate` to resolve the account ID from, in order:
   - `params["account-id"]` (e.g. `--account-id acc-xxx` or `account-id=acc-xxx`)
   - First bare positional argument (e.g. `/api-key:create acc-xxx --name MyKey`)
   - Interactive prompt fallback (only when no inline value is provided)

2. **`cmd/cli/commands_test.go`** — Added unit tests:
   - `TestHandleAPIKeyCreate_PositionalAccountID` — verifies bare positional account ID
   - `TestHandleAPIKeyCreate_AccountIDEquals` — verifies `account-id=acc-xxx` form

### Test Commands

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/ -run 'TestHandleAPIKeyCreate' -v
```

### Verification

All `/api-key:create` tests pass:
- `TestHandleAPIKeyCreate`
- `TestHandleAPIKeyCreate_PositionalAccountID`
- `TestHandleAPIKeyCreate_AccountIDEquals`
- `TestHandleAPIKeyCreate_UserCannotCreateAdminKey`

### Status

Fixed. Pending reviewer approval and manual re-test of `TestCase_manual_cli_permissions.md` step PERM-004.
