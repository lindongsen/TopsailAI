---
maintainer: AI
status: done
related_files:
  - internal/services/account_service.go
  - tests/integration/test_session_expiry_api.py
---

# Issue: Password Change Does Not Invalidate Existing Session

## Description

When an account's `login_password` is changed via `POST /api/v1/accounts/:account_id/password`, the existing `login_session_key` remains valid until its natural expiration. This is a security gap: a password change should invalidate active sessions so that an attacker who obtained the old session key cannot continue to access the account.

## Expected Behavior

Per `docs/cases/TestCase_integration_session_expiry.md` (TC-INT-SESS-012):

1. Create a session via login.
2. Change the password.
3. Use the old session key.
4. Expected: `401 Unauthorized`.

## Actual Behavior

The old session key continues to return `200 OK` for protected endpoints such as `GET /api/v1/accounts/me`.

## Root Cause

`AccountService.ChangePassword` in `internal/services/account_service.go` only updates `LoginPassword`. It does not clear `LoginSessionKey` or `LoginSessionExpiredTime`.

## Fix

Clear `LoginSessionKey` and `LoginSessionExpiredTime` when the password is changed, and update the audit log detail to note that active sessions were invalidated.

## Verification

Run the integration test:

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./tests/integration/manage_test_server.sh -v tests/integration/test_session_expiry_api.py
```

All 12 tests should pass.
