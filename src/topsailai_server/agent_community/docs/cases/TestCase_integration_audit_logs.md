---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Audit Logs

## Overview

Verify audit log endpoints and the lifecycle events they record for security-relevant actions.

---

## TC-INT-AUDIT-001: List Audit Logs

### Objective

Verify `GET /api/v1/audit-logs` returns paginated audit log entries for admin callers.

### Steps

1. Authenticate as admin.
2. Perform an action that generates an audit log (e.g., create account).
3. Send `GET /api/v1/audit-logs`.

### Input

```bash
curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  "${ACS_API_BASE}/api/v1/audit-logs?limit=10&offset=0" | jq .
```

### Expected Output

Status: 200
```json
{
  "data": {
    "items": [
      {
        "audit_log_id": "al-001",
        "account_id": "acc-abc123",
        "api_key_id": "ak-xyz789",
        "action": "account.create",
        "resource_type": "account",
        "resource_id": "acc-def456",
        "resource_name": "Bob Jones",
        "detail": "created by admin",
        "client_ip": "192.168.1.1",
        "create_at_ms": 1704067200000
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 10
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 200.
- `items` is an array of audit log records.
- Each record contains `audit_log_id`, `account_id`, `action`, `resource_type`, `resource_id`, `create_at_ms`.
- Pagination fields `total`, `offset`, `limit` are present.

---

## TC-INT-AUDIT-002: Get Audit Log by ID

### Objective

Verify `GET /api/v1/audit-logs/:audit_log_id` returns a single audit log entry.

### Steps

1. Create an account to generate an audit log.
2. List audit logs to obtain an `audit_log_id`.
3. Send `GET /api/v1/audit-logs/{audit_log_id}`.

### Input

```bash
curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  "${ACS_API_BASE}/api/v1/audit-logs/${AUDIT_LOG_ID}" | jq .
```

### Expected Output

Status: 200
```json
{
  "data": {
    "audit_log_id": "al-001",
    "account_id": "acc-abc123",
    "api_key_id": "ak-xyz789",
    "action": "account.create",
    "resource_type": "account",
    "resource_id": "acc-def456",
    "resource_name": "Bob Jones",
    "detail": "created by admin",
    "client_ip": "192.168.1.1",
    "create_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 200.
- Returned record matches the requested `audit_log_id`.
- All expected fields are present.

---

## TC-INT-AUDIT-003: Get Non-Existent Audit Log

### Objective

Verify requesting an unknown audit log ID returns 404.

### Steps

1. Send `GET /api/v1/audit-logs/al-does-not-exist`.

### Expected Output

Status: 404
```json
{
  "error": "audit log not found",
  "trace_id": "..."
}
```

### Pass Criteria

- Returns 404.
- Error message indicates audit log not found.

---

## TC-INT-AUDIT-004: Filter Audit Logs by Action

### Objective

Verify `action` query parameter filters audit logs.

### Steps

1. Generate audit logs for `account.create` and `api_key.create`.
2. Query `GET /api/v1/audit-logs?action=account.create`.

### Expected Output

Status: 200
- Only audit logs with `action=account.create` are returned.
- No `api_key.create` entries appear.

### Pass Criteria

- Filter is applied correctly.
- `total` reflects filtered count.

---

## TC-INT-AUDIT-005: Filter Audit Logs by Resource Type and ID

### Objective

Verify `resource_type` and `resource_id` query parameters filter audit logs.

### Steps

1. Create an account and note its `account_id`.
2. Query `GET /api/v1/audit-logs?resource_type=account&resource_id={account_id}`.

### Expected Output

Status: 200
- Only audit logs for that account are returned.

### Pass Criteria

- Filter combination works correctly.
- Returned records reference the specified resource.

---

## TC-INT-AUDIT-006: Filter Audit Logs by Account ID

### Objective

Verify `account_id` query parameter filters audit logs by the acting account.

### Steps

1. Perform actions with different accounts.
2. Query `GET /api/v1/audit-logs?account_id={admin_account_id}`.

### Expected Output

Status: 200
- Only audit logs where `account_id` matches the admin account are returned.

### Pass Criteria

- Filter works correctly.
- Other accounts' actions are excluded.

---

## TC-INT-AUDIT-007: Filter Audit Logs by API Key ID

### Objective

Verify `api_key_id` query parameter filters audit logs.

### Steps

1. Perform actions using a specific API key.
2. Query `GET /api/v1/audit-logs?api_key_id={api_key_id}`.

### Expected Output

Status: 200
- Only audit logs where `api_key_id` matches are returned.

### Pass Criteria

- Filter works correctly.

---

## TC-INT-AUDIT-008: Audit Log Pagination

### Objective

Verify pagination works on the audit log list endpoint.

### Steps

1. Generate multiple audit log entries.
2. Query with `offset=0&limit=2`.
3. Query with `offset=2&limit=2`.

### Expected Output

- First page returns first 2 entries.
- Second page returns next 2 entries.
- No overlap between pages.

### Pass Criteria

- Pagination parameters are respected.
- `total` is consistent across pages.

---

## TC-INT-AUDIT-009: Audit Log Time Range Filter

### Objective

Verify `create_at_ms` time range filter works for audit logs.

### Steps

1. Record current time before and after generating audit logs.
2. Query `GET /api/v1/audit-logs?create_at_ms={start}-{end}`.

### Expected Output

Status: 200
- Only audit logs within the time range are returned.

### Pass Criteria

- Time range filter is applied correctly.

---

## TC-INT-AUDIT-010: Non-Admin Cannot Access Audit Logs

### Objective

Verify only admin role can list or get audit logs.

### Steps

1. Authenticate as user or manager.
2. Send `GET /api/v1/audit-logs`.

### Expected Output

Status: 403
```json
{
  "error": "forbidden",
  "trace_id": "..."
}
```

### Pass Criteria

- User and manager roles receive 403.
- Admin role receives 200.

---

## TC-INT-AUDIT-011: Account Creation Writes Audit Log

### Objective

Verify creating an account generates an `account.create` audit log.

### Steps

1. Authenticate as admin.
2. Create a user account.
3. Query audit logs for `action=account.create&resource_id={account_id}`.

### Expected Output

Status: 200
- At least one audit log entry exists.
- `action` is `account.create`.
- `resource_id` matches the new account.

### Pass Criteria

- Audit log is created.
- Acting `account_id` and `api_key_id` are recorded.

---

## TC-INT-AUDIT-012: API Key Creation Writes Audit Log

### Objective

Verify creating an API key generates an `api_key.create` audit log.

### Steps

1. Create an API key for an account.
2. Query audit logs for `action=api_key.create&resource_id={api_key_id}`.

### Expected Output

Status: 200
- At least one audit log entry exists.
- `action` is `api_key.create`.
- `resource_id` matches the new API key.

### Pass Criteria

- Audit log is created.

---

## TC-INT-AUDIT-013: Login Attempts Write Audit Log

### Objective

Verify successful and failed login attempts generate audit logs.

### Steps

1. Attempt login with correct credentials.
2. Attempt login with incorrect credentials.
3. Query audit logs for `action=account.login` or similar.

### Expected Output

Status: 200
- Audit log entries exist for both attempts.
- Failed attempt is distinguishable from successful attempt (via detail or action suffix).

### Pass Criteria

- Both login attempts are audited.

---

## TC-INT-AUDIT-014: Password Change Writes Audit Log

### Objective

Verify changing a password generates an audit log.

### Steps

1. Change an account password.
2. Query audit logs for the account.

### Expected Output

Status: 200
- Audit log entry exists for password change.

### Pass Criteria

- Password change is audited.

---

## TC-INT-AUDIT-015: Account Deletion Writes Audit Log

### Objective

Verify soft-deleting an account generates an audit log.

### Steps

1. Soft-delete an account as admin.
2. Query audit logs for `action=account.delete&resource_id={account_id}`.

### Expected Output

Status: 200
- Audit log entry exists.
- `action` is `account.delete`.

### Pass Criteria

- Deletion is audited.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_audit_logs.py -v
```

## Notes

- Audit log action names may vary by implementation; verify exact names against server logs or API responses.
- Some actions may be asynchronous; allow a short delay before querying audit logs.
- Non-admin access tests require a user or manager API key/session.
