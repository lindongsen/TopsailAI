---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Session Key Expiry

## Overview

Verify login session keys expire after the configured duration and can be renewed.

---

## TC-INT-SESS-001: Session Key Expires After Configured Duration

### Objective

Verify a session key becomes invalid after `ACS_LOGIN_SESSION_EXPIRY_SECONDS`.

### Setup

- Start ACS with `ACS_LOGIN_SESSION_EXPIRY_SECONDS=2`.

### Steps

1. Create a user account.
2. Create a login session via `POST /accounts/{account_id}/session`.
3. Use session key to access `/accounts/me` immediately.
4. Wait 3 seconds.
5. Use the same session key again.

### Expected Output

- Immediate request: 200
- After expiry: 401

### Pass Criteria

- Session key expires as configured.

---

## TC-INT-SESS-002: Login Creates New Session Key

### Objective

Verify password login creates a new session key with expiration.

### Steps

1. Create user account with login_name/password.
2. Send `POST /accounts/login`.

### Expected Output

Status: 200
```json
{
  "data": {
    "account_id": "acc-abc123",
    "session_key": "acc-abc123-550e8400e29b41d4a716446655440000",
    "expires_at_ms": 1704153600000
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Session key returned.
- `expires_at_ms` is in the future.

---

## TC-INT-SESS-003: New Session Replaces Old Session

### Objective

Verify creating a new session invalidates the previous session key.

### Steps

1. Create session for account.
2. Record session key A.
3. Create another session for the same account.
4. Record session key B.
5. Try to use session key A.

### Expected Output

- Session key A: 401
- Session key B: 200

### Pass Criteria

- Only the latest session key is valid.

---

## TC-INT-SESS-004: Expired Session Cannot Access Protected Endpoints

### Objective

Verify expired session key is rejected by all protected endpoints.

### Steps

1. Create session with short expiry.
2. Wait for expiry.
3. Send `GET /accounts/me` with expired key.

### Expected Output

Status: 401

### Pass Criteria

- Expired session rejected.

---

## TC-INT-SESS-005: Manager Can Create Session for User

### Objective

Verify manager can create a session for a user account.

### Steps

1. Authenticate as manager.
2. Create a user account.
3. Send `POST /accounts/{account_id}/session`.

### Expected Output

Status: 200
- Session key returned.

### Pass Criteria

- Manager can create user sessions.

---

## TC-INT-SESS-006: Manager Cannot Create Session for Admin

### Objective

Verify manager cannot create a session for an admin account.

### Steps

1. Authenticate as manager.
2. Attempt `POST /accounts/{admin_account_id}/session`.

### Expected Output

Status: 403

### Pass Criteria

- Manager session creation restricted to users.

---

## TC-INT-SESS-007: User Can Create Own Session

### Objective

Verify user can create a session for their own account.

### Steps

1. Authenticate as user (via API key or existing session).
2. Send `POST /accounts/{own_account_id}/session`.

### Expected Output

Status: 200

### Pass Criteria

- User can renew own session.

---

## TC-INT-SESS-008: User Cannot Create Session for Other Account

### Objective

Verify user cannot create a session for another account.

### Steps

1. Authenticate as user A.
2. Attempt `POST /accounts/{user_B_account_id}/session`.

### Expected Output

Status: 403

### Pass Criteria

- Cross-account session creation forbidden.

---

## TC-INT-SESS-009: Session Key Authenticates Requests

### Objective

Verify `X-Session-Key` header authenticates protected endpoints.

### Steps

1. Create session.
2. Send `GET /accounts/me` with `X-Session-Key` header.

### Expected Output

Status: 200
- Response contains correct account.

### Pass Criteria

- Session key authentication works.

---

## TC-INT-SESS-010: Session Expiry Reflected in expires_at_ms

### Objective

Verify `expires_at_ms` matches configured expiry.

### Steps

1. Start ACS with `ACS_LOGIN_SESSION_EXPIRY_SECONDS=3600`.
2. Create session.
3. Compare `expires_at_ms` to current time + 3600 seconds.

### Expected Output

- `expires_at_ms` ≈ `now_ms + 3,600,000`.

### Pass Criteria

- Expiry timestamp accurate.

---

## TC-INT-SESS-011: Login with Inactive Account Fails

### Objective

Verify login fails for accounts with `status != active`.

### Steps

1. Soft-delete a user account.
2. Attempt login with the account's credentials.

### Expected Output

Status: 400

### Pass Criteria

- Inactive/deleted accounts cannot log in.

---

## TC-INT-SESS-012: Password Change Invalidates Existing Session

### Objective

Verify changing password invalidates the current session key.

### Steps

1. Create session via login.
2. Change password.
3. Use old session key.

### Expected Output

Status: 401

### Pass Criteria

- Password change invalidates session.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_session_expiry.py -v
```

## Notes

- Short expiry tests require `ACS_LOGIN_SESSION_EXPIRY_SECONDS` to be set very low.
- Some tests may need server restart with different env vars; consider separate test processes.
- Exact error messages may vary; verify against actual API responses.
