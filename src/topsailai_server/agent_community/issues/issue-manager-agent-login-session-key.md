# Issue: Pass sender login session key to manager-agent via ACS_LOGIN_SESSION_KEY

## Description
When a `manager-agent` is triggered, ACS must obtain the original message sender's `accounts.login_session_key`, creating a new session if none exists or if it has expired, and pass the plaintext key to the agent as the environment variable `ACS_LOGIN_SESSION_KEY`.

## Background
The requirement comes from the ACS design: manager-agents coordinate transactions within a group and may need to act on behalf of the user who sent the triggering message. Providing a valid login session key allows the manager-agent to invoke user-scoped APIs when necessary.

## Changes Made

### Source Files
1. **`internal/services/account_service.go`**
   - Added `EnsureLoginSession(ctx, accountID) (string, int64, error)`.
   - Looks up the account, verifies it is active, and creates a fresh login session key.
   - Because `accounts.login_session_key` stores only a bcrypt hash, the plaintext key is not recoverable; a new session is generated whenever this helper is called.

2. **`internal/agent/interface.go`**
   - Extended `BuildChatEnv` signature with `loginSessionKey string`.
   - Injects `ACS_LOGIN_SESSION_KEY` into the agent environment when the parameter is non-empty.

3. **`internal/nats/consumer.go`**
   - Added a minimal `AccountService` interface to avoid import cycles.
   - Added `accountService` field to `Consumer` and updated `NewConsumer` constructor.
   - In `processAgentTarget`, when the target agent is a `manager-agent`, calls `EnsureLoginSession` for `pendingMsg.SenderID` and passes the result to `BuildChatEnv`.
   - Logs a warning and continues with an empty key if session creation fails.

4. **`cmd/server/main.go`**
   - Passes `accountSvc` to `nats.NewConsumer`.

### Test Files
- **`internal/services/account_service_test.go`**: Added `TestAccountService_EnsureLoginSession` covering success, non-existent account, and inactive account cases.
- **`internal/agent/interface_test.go`**: Updated existing `TestBuildChatEnv` and added `TestBuildChatEnvWithLoginSessionKey`.
- **`internal/nats/consumer_test.go`**, **`consumer_noack_test.go`**, **`consumer_duplicate_test.go`**: Updated all `NewConsumer` call sites to pass the new `AccountService` argument.

### Documentation
- **`docs/API.md`**: Added "Runtime Environment Variables" section documenting `ACS_LOGIN_SESSION_KEY`.
- **`docs/Environment_Variables.md`**: Added `ACS_LOGIN_SESSION_KEY` to the agent chat environment variables table.

## Design Caveat
Because `accounts.login_session_key` is stored as a bcrypt hash, an existing valid plaintext key cannot be recovered. Therefore, every manager-agent trigger generates a fresh session key and rotates the sender's stored session. This behavior is acceptable for the current use case but should be revisited if session continuity becomes a requirement.

## Verification
- `go test ./internal/services/...` passes.
- `go test ./internal/agent/...` passes.
- `go test ./internal/nats/...` passes.
- `go test ./...` passes.
- `go build ./...` passes.

## Related
- `docs/API.md`
- `docs/Environment_Variables.md`
- `internal/services/account_service.go`
- `internal/agent/interface.go`
- `internal/nats/consumer.go`


## Verification

### Unit & Regression Tests
- `go test ./internal/services/...` — PASS
- `go test ./internal/agent/...` — PASS
- `go test ./internal/nats/...` — PASS
- `go test ./...` — PASS
- `go build ./...` — PASS

### Manual End-to-End Test
- **Status:** PASS
- **Date:** 2026-06-19
- **Tester:** km1-tester
- **Setup:** SQLite database, mock manager-agent chat/health scripts, HTTP port 7470.
- **Scenario:**
  1. Created a user account.
  2. Created a login session for the user.
  3. Created a group (manager-agent auto-joined).
  4. Sent a user message, which auto-triggered the manager-agent.
- **Result:**
  - The mock manager-agent script received `ACS_LOGIN_SESSION_KEY` in its environment.
  - The value was a freshly generated, valid login session key for the sender account.
  - `GET /api/v1/accounts/me` authenticated with the injected key returned the sender account.
- **Conclusion:** Feature works as designed. The issue is resolved and verified.

### Issue Status
**Resolved / Verified**
