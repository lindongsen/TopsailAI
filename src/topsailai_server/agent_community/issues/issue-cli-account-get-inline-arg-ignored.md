---
status: open
priority: high
component: cli
---

# CLI `/account:get` ignores inline account-id argument and enters interactive prompt

## Summary
The `acs-cli` `/account:get` command does not accept the account ID provided as an inline argument. Instead, it enters an interactive prompt asking for `Account ID:`, which blocks scripted and tmux-based manual testing.

## Environment
- Commit: post-fix for `issue-default-manager-api-key-file-not-written`
- Binary: `/TopsailAI/src/topsailai_server/agent_community/bin/acs-cli`
- Server: `acs-server` on PostgreSQL + NATS
- OS: Debian GNU/Linux 13

## Reproduction Steps
1. Start the ACS server and CLI as admin or manager.
2. Authenticate the CLI.
3. Run any of the following:
   ```
   /account:get --account-id acc-xxx
   /account:get account-id=acc-xxx
   /account:get acc-xxx
   ```
4. Observe that the CLI prints `Account ID:` and waits for interactive input instead of using the provided value.

## Expected Behavior
The CLI should parse the inline argument and immediately call `GET /api/v1/accounts/{account_id}`, consistent with other commands that accept inline arguments (e.g., `/group:enter --group-id`).

## Actual Behavior
The CLI ignores the inline argument and enters an interactive prompt. Pressing `C-c` cancels the prompt; the command does not execute.

## Impact
- Blocks scripted/tmux-based verification of manager read-permission tests in `TestCase_manual_cli_permissions.md`.
- Forces testers to fall back to curl, reducing the value of CLI manual tests.

## Workaround
Use curl directly:
```bash
curl -s -H "Authorization: Bearer $MANAGER_TOKEN" \
  http://localhost:7370/api/v1/accounts/acc-xxx | jq .
```

## Related Issues
- Similar interactive-prompt behavior was previously observed for `/api-key:create` and `/api-key:delete`.
- `issue-group-enter-inline-arg.md` documents a related CLI inline-argument problem.

## Suggested Fix
Review the command registration and flag parsing for `/account:get` in `cmd/cli`. Ensure the command checks for a provided account-id flag/value before falling back to the interactive `readline` prompt.

## Fix

### Root Cause
`handleAccountGet` in `cmd/cli/commands.go` only looked at the parsed key `id` from `parseInlineArgs`. It did not check the more explicit `--account-id` / `account-id=` forms, and it did not support a bare positional argument. When no value was found, it unconditionally fell back to the interactive `readline` prompt.

### Changes Made
- **File:** `cmd/cli/commands.go`
  - Updated `handleAccountGet` to resolve the account ID from, in order:
    1. `params["account-id"]` (e.g. `--account-id acc-xxx` or `account-id=acc-xxx`)
    2. `params["id"]` (legacy `id=acc-xxx` form)
    3. First bare positional argument (e.g. `/account:get acc-xxx`)
  - Only falls back to the interactive prompt when none of the above yield a value.

- **File:** `cmd/cli/commands_test.go`
  - Added `TestHandleAccountGet_AccountIDFlag` for `--account-id`.
  - Added `TestHandleAccountGet_AccountIDEquals` for `account-id=`.
  - Added `TestHandleAccountGet_PositionalArg` for a bare positional argument.

### Tests Run
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/ -run 'TestHandleAccountGet' -v
```
All `/account:get` tests pass:
- `TestHandleAccountGet`
- `TestHandleAccountGet_SelfOnlyForUser`
- `TestHandleAccountGet_AccountIDFlag`
- `TestHandleAccountGet_AccountIDEquals`
- `TestHandleAccountGet_PositionalArg`

### Verification
After rebuilding the CLI, the following commands should immediately call `GET /api/v1/accounts/{account_id}` without prompting:
```
/account:get acc-xxx
/account:get --account-id acc-xxx
/account:get account-id=acc-xxx
/account:get --id acc-xxx
/account:get id=acc-xxx
```

### Review Notes
- Reviewer: `AIMember.km2-reviewer`
- Result: **Approved**
- The fix is minimal, correct, and consistent with `handleGroupEnter` / `handleAccountDelete`.
- One unrelated pre-existing test failure was observed: `TestHandleAccountCreate_ManagerPassesRoleThrough` expects managers to send `role=admin`, but the CLI intentionally forces `role=user` for managers (matching API docs). This is a stale/incorrect test, not a bug introduced by this fix, and should be addressed separately.

### Next Steps
1. Rebuild the CLI with `make build-cli`.
2. Tester (`AIMember.km1-tester`) should resume `TestCase_manual_cli_permissions.md` from the manager read-permission step, then continue with the cluster and agent-trigger plans.
