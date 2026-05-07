---
maintainer: AI
programming_language: python
---

# Feature: API Key Authentication with QoS and Permission Control

## Overview

This feature introduces API key-based authentication to protect all API endpoints, with two additional capabilities:

1. **QoS Control**: Rate limiting on the `ReceiveMessage` endpoint to control message sending frequency per API key.
2. **Permission Control**: API keys are bound to specific sessions. Regular API keys can only operate on their bound sessions, while admin API keys can operate on all sessions. Only admins can create and manage API keys.

## Database Schema

### Table: api_key

Stores API key metadata.

columns:
    - api_key_id, VARCHAR(32), primary key, generated UUID with "ak_" prefix
    - api_key, VARCHAR(64), unique, the actual key value (shown only once on creation)
    - name, VARCHAR(255), human-readable name for the key
    - role, VARCHAR(16), 'admin' or 'user', default 'user'
    - rate_limit, INT, max messages per minute for this key, 0 means unlimited, default 60
    - is_active, BOOLEAN, default True
    - create_time, DATETIME, default local time
    - update_time, DATETIME, auto-updated on modification

indexes:
    - ix_api_key_api_key, on api_key column (for fast lookup)
    - ix_api_key_role, on role column

### Table: api_key_session

Junction table binding API keys to sessions (many-to-many).

columns:
    - api_key_id, VARCHAR(32), FK to api_key.api_key_id, part of primary key
    - session_id, VARCHAR(32), FK to session.session_id, part of primary key
    - create_time, DATETIME, default local time

primary_keys: (api_key_id, session_id)

indexes:
    - ix_api_key_session_session_id, on session_id column

### Table: rate_limit_log

Tracks API key usage for QoS enforcement.

columns:
    - id, INTEGER, primary key, auto-increment
    - api_key_id, VARCHAR(32), FK to api_key.api_key_id
    - session_id, VARCHAR(32), the session being accessed
    - action, VARCHAR(32), e.g., 'receive_message'
    - create_time, DATETIME, default local time

indexes:
    - ix_rate_limit_log_api_key_id, on api_key_id column
    - ix_rate_limit_log_create_time, on create_time column

## Permission Model

### Roles

- **admin**: Full access to all sessions. Can create, list, delete API keys. Can bind/unbind sessions to any API key. Admin keys do not require session bindings.
- **user**: Can only access sessions explicitly bound to their API key. Cannot manage API keys. A user key with no bound sessions cannot access any session endpoints.

### Permission Matrix

| Endpoint | Admin | User (bound session) | User (unbound session) |
|----------|-------|---------------------|----------------------|
| GET /api/v1/session/{session_id} | Allowed | Allowed | 403 Forbidden |
| GET /api/v1/session | Allowed (all) | Allowed (bound only) | N/A |
| DELETE /api/v1/session | Allowed (all) | 403 Forbidden | 403 Forbidden |
| POST /api/v1/session/process | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| POST /api/v1/message | Allowed (all) | Allowed (bound only) + rate limit | 403 Forbidden |
| GET /api/v1/message | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| POST /api/v1/task | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| GET /api/v1/task | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| POST /api/v1/apikey | Allowed | 403 Forbidden | 403 Forbidden |
| GET /api/v1/apikey | Allowed | 403 Forbidden | 403 Forbidden |
| DELETE /api/v1/apikey/{id} | Allowed | 403 Forbidden | 403 Forbidden |
| POST /api/v1/apikey/{id}/sessions | Allowed | 403 Forbidden | 403 Forbidden |
| DELETE /api/v1/apikey/{id}/sessions | Allowed | 403 Forbidden | 403 Forbidden |

### Session Binding Rules

- When creating a user API key, admin can optionally provide a list of `session_ids` to bind.
- Admin API keys do not require session bindings; they implicitly have access to all sessions.
- A user API key with no bound sessions cannot access any session endpoints (returns 403).
- Session binding is checked at the API layer before calling storage methods.
- For `ListSessions` with user-role keys, results are filtered to only include bound sessions.

## QoS Model

### Rate Limiting

- Rate limiting applies only to the `ReceiveMessage` endpoint (POST /api/v1/message).
- Each API key has a `rate_limit` field (messages per minute).
- Before processing a `ReceiveMessage` request, the system counts entries in `rate_limit_log` for this `api_key_id` with `action='receive_message'` in the last 60 seconds.
- If count >= rate_limit and rate_limit > 0, return 429 Too Many Requests.
- If rate_limit == 0, no limit is enforced (admin keys typically use this).
- After a successful `ReceiveMessage`, a record is inserted into `rate_limit_log`.

### Rate Limit Log Cleanup

- The `rate_limit_log` table is cleaned periodically to prevent unbounded growth.
- A cron job deletes records older than 1 hour.
- The `clean_rate_limit_logs(before: datetime)` method on the storage class handles the deletion.

## API Specification

### Authentication

All endpoints (except health check) require an API key via the `X-API-Key` header.

```
X-API-Key: <api_key_value>
```

If the header is missing or invalid, return:
```json
{
  "code": 401,
  "data": null,
  "message": "Missing API key"
}
```

### api/v1/apikey

#### CreateApiKey

Create a new API key. Admin only.

```
POST /api/v1/apikey
```

parameters:
- name: str, required, human-readable name
- role: str, 'admin' or 'user', default 'user'
- rate_limit: int, messages per minute, default 0 (unlimited for admin)
- session_ids: list[str], optional, sessions to bind (only for user role)

response:
```json
{
  "code": 0,
  "data": {
    "api_key_id": "ak_...",
    "api_key": "actual-key-value-shown-only-once",
    "name": "My Key",
    "role": "user",
    "rate_limit": 60,
    "is_active": true,
    "create_time": "...",
    "update_time": "..."
  },
  "message": "API key created successfully"
}
```

errors:
- 403: Non-admin attempting to create key
- 400: Invalid role or rate_limit value

#### ListApiKeys

List all API keys (with actual key value exposed for admin visibility). Admin only.

```
GET /api/v1/apikey
```

response:
```json
{
  "code": 0,
  "data": {
    "api_keys": [
      {
        "api_key_id": "ak_...",
        "api_key": "...",
        "name": "My Key",
        "role": "user",
        "rate_limit": 60,
        "is_active": true,
        "create_time": "...",
        "update_time": "..."
      }
    ],
    "total": 1
  },
  "message": "OK"
}
```

errors:
- 403: Non-admin attempting to list keys

#### DeleteApiKey

Delete an API key and its related bindings and rate limit logs. Admin only.

```
DELETE /api/v1/apikey/{api_key_id}
```

response:
```json
{
  "code": 0,
  "data": null,
  "message": "API key deleted successfully"
}
```

errors:
- 403: Non-admin attempting to delete key
- 404: API key not found
- 400: Cannot delete the last admin API key

#### BindSessions

Bind sessions to an existing user API key. Admin only.

```
POST /api/v1/apikey/{api_key_id}/sessions
```

parameters:
- session_ids: list[str], required

response:
```json
{
  "code": 0,
  "data": {
    "bound_sessions": ["session-1", "session-2"]
  },
  "message": "Sessions bound successfully"
}
```

errors:
- 403: Non-admin
- 404: API key not found
- 400: Cannot bind sessions to admin API key

#### UnbindSessions

Unbind sessions from a user API key. Admin only.

```
DELETE /api/v1/apikey/{api_key_id}/sessions
```

parameters:
- session_ids: list[str], required

response:
```json
{
  "code": 0,
  "data": {
    "unbound_sessions": ["session-1"]
  },
  "message": "Sessions unbound successfully"
}
```

errors:
- 403: Non-admin
- 404: API key not found

### Existing Endpoints - Behavior Changes

All existing endpoints now require `X-API-Key` header authentication and permission checks.

#### ReceiveMessage - QoS Enforcement

Before processing, check rate limit. If exceeded:
```json
{
  "code": 429,
  "data": null,
  "message": "Rate limit exceeded: 60 messages per minute"
}
```

#### Session Endpoints - Permission Check

For user-role keys, verify the requested session_id is in the bound sessions list. If not:
```json
{
  "code": 403,
  "data": null,
  "message": "Access denied to session: {session_id}"
}
```

For `ListSessions` with user-role keys, filter results to only include bound sessions.

## Implementation Notes

### Code Structure

```
storage/
  api_key_manager/
    __init__.py       # exports ApiKeyData, ApiKeySessionData, RateLimitLogData, ApiKeySQLAlchemy
    base.py           # Data classes: ApiKeyData, ApiKeySessionData, RateLimitLogData, ApiKeyStorageBase
    sql.py            # SQLAlchemy models and operations for api_key tables
api/
  middleware/
    __init__.py       # exports get_current_api_key, require_admin, check_session_permission, check_rate_limit
    auth.py           # FastAPI dependencies for authentication and authorization
  routes/
    api_key.py        # API key management routes
```

### Key Implementation Details

1. **API Key Generation**: Uses `secrets.token_hex(32)` to generate secure random 64-character hex keys. The raw key is returned only on creation; subsequent listings also show the key value (admin-only endpoint).

2. **Authentication Flow**:
   - FastAPI dependency `get_current_api_key` extracts `X-API-Key` header
   - Looks up key in `api_key` table via `get_api_key_by_value()`, verifies `is_active=True`
   - Returns `ApiKeyData` or raises 401 HTTPException
   - For admin-only endpoints, additional `require_admin` dependency checks `role == 'admin'`

3. **Permission Check Flow**:
   - For endpoints with `session_id` in path/query params, `check_session_permission` dependency verifies:
     - If key role is 'admin': always allow
     - If key role is 'user': check `api_key_session` table for binding via `is_session_bound()`
   - For endpoints with `session_id` in request body, `verify_session_permission()` helper is called explicitly
   - For `ListSessions`: filter query by bound session IDs for user keys

4. **QoS Flow**:
   - In `ReceiveMessage` route, before creating the message:
     - `check_rate_limit` dependency checks rate limit for path/query session_id
     - `verify_rate_limit()` helper checks and logs for body-based session_id
     - Query `rate_limit_log` for count in last 60 seconds for this `api_key_id`
     - If count >= rate_limit > 0: return 429
     - After successful check: insert `rate_limit_log` record

5. **Migration**:
   - Update `storage/migration.py` to handle new tables: `api_key`, `api_key_session`, `rate_limit_log`
   - Ensure indexes are created for performance

6. **Default Admin Key**:
   - On first startup (when no admin API keys exist), automatically create a default admin key
   - Uses `TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY` env var if set, otherwise generates random key via `secrets.token_hex(32)`
   - Logs the default admin key value at INFO level so it can be captured
   - Logs a warning to save the key securely

7. **Rate Limit Log Cleanup**:
   - A cron job deletes `rate_limit_log` records older than 1 hour
   - Uses `clean_rate_limit_logs(before=datetime.now() - timedelta(hours=1))`
   - This prevents the table from growing unbounded

8. **Backward Compatibility**:
   - Since this is a new feature requiring auth, there is no backward compatibility concern
   - All clients must provide `X-API-Key` header

### Testing Considerations

1. **Unit Tests**:
   - Test API key CRUD operations
   - Test permission checks (admin vs user, bound vs unbound sessions)
   - Test rate limiting (exact limit, limit exceeded, unlimited admin)
   - Test authentication (missing key, invalid key, inactive key)

2. **Integration Tests**:
   - End-to-end flow: create key -> send message -> verify rate limit -> verify permission
   - Test that existing endpoints reject requests without API key
   - Test default admin key creation on first startup

### Environment Variables

Add to `env_template`:

```
# Optional: Pre-configured default admin API key
# If not set, a random admin key is generated on first startup
# This key has full admin privileges (all sessions, API key management)
# TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY=
```

### Suggestions for Developer

1. Implement storage layer first (`api_key_manager/base.py` and `sql.py`) with full CRUD and query methods.
2. Implement auth dependencies (`api/middleware/auth.py`) - this is the foundation.
3. Implement API key management routes (`api/routes/api_key.py`) - admin-only endpoints.
4. Update existing routes to inject auth dependencies:
   - Add `get_current_api_key` dependency to all protected endpoints
   - Add `check_session_permission` to session/message/task endpoints
   - Add rate limit check to `ReceiveMessage`
5. Update `api/app.py` to register the new router and wire auth dependencies.
6. Update `storage/migration.py` for new tables.
7. Add rate limit log cleanup to croner jobs.
8. Write unit tests for each layer.
9. Update `env_template` with new optional variable.
10. Update client (`topsailai_agent_client.py`) to support `X-API-Key` header.
11. Update `main.py` to initialize default admin key on startup.
