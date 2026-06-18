# Issue: CLI prompt does not reflect session-key account on startup

## Status
open

## Description
When the CLI is started with `--session-key <key>`, the initial prompt shows the
default CLI user (`acs@CLI User:`) instead of the account associated with the
session key. The prompt is only updated after the user manually runs `/account:me`.

## Reproduction
```bash
/tmp/acs-cli --session-key <valid-session-key>
```

## Expected
The CLI should resolve the current account during startup (e.g., by calling
`/api/v1/accounts/me`) and display the correct prompt immediately:
```
acs@Live Test User[user]:
```

## Actual
The prompt shows:
```
acs@CLI User:
```
until `/account:me` is executed.

## Affected file
- `cmd/cli/main.go` — startup account resolution.

## Impact
Minor UX issue. Authentication works correctly; only the prompt is misleading.

## Suggested Fix
After initializing the API client with a session key, call `client.GetMe()` and
update `state.account` / `state.authMethod` before entering the read-eval-print
loop. Reuse the existing prompt update logic.
