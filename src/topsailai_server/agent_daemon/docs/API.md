---
maintainer: AI
programming_language: python
workspace: /TopsailAI/src/topsailai_server/agent_daemon
---

# Agent Daemon API Documentation

## Overview

The Agent Daemon API provides RESTful endpoints for managing sessions, messages, tasks, and API keys. All endpoints (except health check) support optional API key-based authentication with role-based permission control and QoS rate limiting.

**Base URL:** `http://{host}:{port}` (default: `http://127.0.0.1:7373`)

**Unified Response Format:**

```json
{
  "code": 0,
  "data": null,
  "message": "OK"
}
```

- `code` (int): `0` indicates success; non-zero indicates an error.
- `data` (any): Response payload on success; `null` on error.
- `message` (str): Human-readable status or error description.

---

## Authentication

When `TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED=true`, all protected endpoints require authentication via one of the following methods.

### Method 1: X-API-Key Header

The `X-API-Key` header is the primary authentication method and takes precedence over the `Authorization` header:

```
X-API-Key: <api_key_value>
```

### Method 2: Authorization Bearer Token

As an alternative, you can provide the API key via the `Authorization` header using the Bearer scheme:

```
Authorization: Bearer <api_key_value>
```

The Bearer scheme is case-insensitive (`Bearer`, `bearer`, and `BEARER` are all accepted).

### Authentication Precedence

If both headers are present, `X-API-Key` takes precedence. The `Authorization` header is only evaluated when `X-API-Key` is absent.

### Authentication Errors

**Missing API Key (401):**
```json
{
  "code": 401,
  "data": null,
  "message": "Missing API key"
}
```

**Invalid or Inactive API Key (401):**
```json
{
  "code": 401,
  "data": null,
  "message": "Invalid or inactive API key"
}
```

**Admin Access Required (403):**
```json
{
  "code": 403,
  "data": null,
  "message": "Admin access required"
}
```

**Session Access Denied (403):**
```json
{
  "code": 403,
  "data": null,
  "message": "Access denied to session: {session_id}"
}
```

### Default Admin Key

On first startup when no admin API keys exist, a default admin key is automatically created:
- Uses `TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY` env var if set.
- Otherwise, a random 64-character hex key is generated via `secrets.token_hex(32)`.
- The key value is logged at INFO level on startup.

---

## Permission Model

### Roles

- **admin**: Full access to all sessions. Can create, list, delete API keys and manage session bindings. Admin keys do not require session bindings.
- **user**: Can only access sessions explicitly bound to their API key. Cannot manage API keys. A user key with no bound sessions cannot access any session endpoints.

### Permission Matrix

| Endpoint | Method | Admin | User (bound session) | User (unbound session) |
|----------|--------|-------|---------------------|----------------------|
| `/health` | GET | Allowed | Allowed | Allowed |
| `/api/v1/session/{session_id}` | GET | Allowed | Allowed | 403 Forbidden |
| `/api/v1/session` | GET | Allowed (all) | Allowed (bound only) | N/A |
| `/api/v1/session` | DELETE | Allowed (all) | 403 Forbidden | 403 Forbidden |
| `/api/v1/session/process` | POST | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| `/api/v1/message` | POST | Allowed (all) | Allowed (bound only) + rate limit | 403 Forbidden |
| `/api/v1/message` | GET | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| `/api/v1/task` | POST | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| `/api/v1/task` | GET | Allowed (all) | Allowed (bound only) | 403 Forbidden |
| `/api/v1/apikey` | POST | Allowed | 403 Forbidden | 403 Forbidden |
| `/api/v1/apikey` | GET | Allowed (all keys) | Allowed (own key only) | N/A |
| `/api/v1/apikey/{id}` | DELETE | Allowed | 403 Forbidden | 403 Forbidden |
| `/api/v1/apikey/{id}/sessions` | POST | Allowed | 403 Forbidden | 403 Forbidden |
| `/api/v1/apikey/{id}/sessions` | DELETE | Allowed | 403 Forbidden | 403 Forbidden |
| `/api/v1/apikey/{id}/environs` | POST | Allowed | 403 Forbidden | 403 Forbidden |
| `/api/v1/apikey/{id}/environs` | GET | Allowed | 403 Forbidden | 403 Forbidden |
| `/api/v1/apikey/{id}/environs/{key}` | DELETE | Allowed | 403 Forbidden | 403 Forbidden |

---

## QoS / Rate Limiting

Rate limiting applies only to the `POST /api/v1/message` (ReceiveMessage) endpoint.

- Each API key has a `rate_limit` field (messages per minute).
- `rate_limit = 0` means unlimited (typical for admin keys).
- Before processing a `ReceiveMessage` request, the system counts entries in `rate_limit_log` for this `api_key_id` with `action='receive_message'` in the last 60 seconds.
- If `count >= rate_limit` and `rate_limit > 0`, the request is rejected.

**Rate Limit Exceeded (429):**
```json
{
  "code": 429,
  "data": null,
  "message": "Rate limit exceeded: 60 messages per minute"
}
```

Rate limit logs are cleaned periodically (records older than 1 hour are deleted) to prevent unbounded table growth.

---

## Endpoints

### Health Check

#### GET /health

Check the health status of the API server and database connection.

**Authentication:** None required.

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "status": "healthy",
    "database": "healthy",
    "timestamp": "2026-05-20T17:12:18"
  },
  "message": "OK"
}
```

---

### Session

Base path: `/api/v1/session`

#### GET /api/v1/session/{session_id}

Get a session by ID, including its current processing status (idle/processing).

**Authentication:** Required. User keys must have the session bound.

**Path Parameters:**
- `session_id` (str, required): The session identifier.

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "session_id": "sess_001",
    "session_name": "sess_001",
    "task": null,
    "create_time": "2026-05-20T10:00:00",
    "update_time": "2026-05-20T10:00:00",
    "processed_msg_id": "msg_003",
    "status": "idle"
  },
  "message": "OK"
}
```

**Errors:**
- `404`: Session not found.

---

#### GET /api/v1/session

List sessions with optional filtering and pagination.

**Authentication:** Required. For user keys, only bound sessions are returned.

**Query Parameters:**
- `session_ids` (str, optional): Comma-separated list of session IDs to filter.
- `start_time` (str, optional): Start time filter (ISO format).
- `end_time` (str, optional): End time filter (ISO format).
- `offset` (int, optional): Pagination offset. Default: `0`.
- `limit` (int, optional): Maximum number of results. Default: `1000`.
- `sort_key` (str, optional): Field to sort by. Default: `create_time`.
- `order_by` (str, optional): Sort order (`asc` or `desc`). Default: `desc`.

**Response (200):**
```json
{
  "code": 0,
  "data": [
    {
      "session_id": "sess_001",
      "session_name": "sess_001",
      "task": null,
      "create_time": "2026-05-20T10:00:00",
      "update_time": "2026-05-20T10:00:00",
      "processed_msg_id": "msg_003"
    }
  ],
  "message": "OK"
}
```

---

#### DELETE /api/v1/session

Delete sessions and all their related messages.

**Authentication:** Required. Admin only.

**Query Parameters:**
- `session_ids` (str, required): Comma-separated list of session IDs to delete.

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "deleted_count": 2
  },
  "message": "Deleted 2 session(s)"
}
```

---

#### POST /api/v1/session/process

Manually trigger processing for a session. Checks if `processed_msg_id` is the latest message; if not, starts the processor for unprocessed messages.

**Authentication:** Required. User keys must have the session bound.

**Request Body:**
```json
{
  "session_id": "sess_001"
}
```

**Response (200) - Processing started:**
```json
{
  "code": 0,
  "data": {
    "processed_msg_id": "msg_003",
    "processing_msg_id": "msg_005",
    "messages": [
      {
        "msg_id": "msg_004",
        "session_id": "sess_001",
        "message": "Hello",
        "role": "user",
        "create_time": "2026-05-20T10:01:00",
        "update_time": "2026-05-20T10:01:00",
        "task_id": null,
        "task_result": null,
        "processed_msg_id": null
      },
      {
        "msg_id": "msg_005",
        "session_id": "sess_001",
        "message": "How are you?",
        "role": "user",
        "create_time": "2026-05-20T10:02:00",
        "update_time": "2026-05-20T10:02:00",
        "task_id": "task_001",
        "task_result": "Done",
        "processed_msg_id": null
      }
    ],
    "processor_pid": 12345
  },
  "message": "Processor started for unprocessed messages"
}
```

**Response (200) - No processing needed:**
```json
{
  "code": 0,
  "data": {
    "processed_msg_id": "msg_005"
  },
  "message": "No processing needed"
}
```

---

### Message

Base path: `/api/v1/message`

#### POST /api/v1/message

Receive a new message. Saves the message, creates the session if it does not exist, and triggers message processing if there are unprocessed messages.

**Authentication:** Required. User keys must have the session bound. Rate limit enforced.

**Request Body:**
```json
{
  "message": "Hello, agent daemon!",
  "session_id": "sess_001",
  "role": "user",
  "processed_msg_id": null
}
```

**Fields:**
- `message` (str, required): Message content.
- `session_id` (str, required): Target session identifier.
- `role` (str, optional): Message role (`user` or `assistant`). Default: `user`.
- `processed_msg_id` (str, optional): If set, updates the session's `processed_msg_id` to this value.

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "msg_id": "msg_006"
  },
  "message": "Message received"
}
```

**Errors:**
- `400`: Validation error (invalid session_id, message content, or role).
- `429`: Rate limit exceeded.

---

#### GET /api/v1/message

Retrieve messages for a session.

**Authentication:** Required. User keys must have the session bound.

**Query Parameters:**
- `session_id` (str, required): Session identifier.
- `start_time` (str, optional): Start time filter (ISO format).
- `end_time` (str, optional): End time filter (ISO format).
- `offset` (int, optional): Pagination offset. Default: `0`.
- `limit` (int, optional): Maximum number of results. Default: `1000`.
- `sort_key` (str, optional): Field to sort by. Default: `create_time`.
- `order_by` (str, optional): Sort order (`asc` or `desc`). Default: `desc`.
- `processed_msg_id` (str, optional): Filter by `processed_msg_id` field.

**Response (200):**
```json
{
  "code": 0,
  "data": [
    {
      "msg_id": "msg_005",
      "session_id": "sess_001",
      "message": "How are you?",
      "role": "user",
      "create_time": "2026-05-20T10:02:00",
      "update_time": "2026-05-20T10:02:00",
      "task_id": "task_001",
      "task_result": "Done",
      "processed_msg_id": null
    }
  ],
  "message": "OK"
}
```

---

### Task

Base path: `/api/v1/task`

#### POST /api/v1/task

Set task result for a processed message. Updates the message with `task_id` and `task_result`, updates the session's `processed_msg_id`, and checks for more unprocessed messages.

**Authentication:** Required. User keys must have the session bound.

**Request Body:**
```json
{
  "session_id": "sess_001",
  "processed_msg_id": "msg_005",
  "task_id": "task_001",
  "task_result": "Task completed successfully"
}
```

**Fields:**
- `session_id` (str, required): Session identifier.
- `processed_msg_id` (str, required): The message ID that was processed.
- `task_id` (str, required): Task identifier.
- `task_result` (str, required): Task execution result.

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "task_id": "task_001"
  },
  "message": "Task result saved"
}
```

**Errors:**
- `404`: Message not found.

---

#### GET /api/v1/task

Retrieve tasks (messages with `task_id`) for a session.

**Authentication:** Required. User keys must have the session bound.

**Query Parameters:**
- `session_id` (str, required): Session identifier.
- `task_ids` (str, optional): Comma-separated list of task IDs to filter.
- `start_time` (str, optional): Start time filter (ISO format).
- `end_time` (str, optional): End time filter (ISO format).
- `offset` (int, optional): Pagination offset. Default: `0`.
- `limit` (int, optional): Maximum number of results. Default: `1000`.
- `sort_key` (str, optional): Field to sort by. Default: `create_time`.
- `order_by` (str, optional): Sort order (`asc` or `desc`). Default: `desc`.

**Response (200):**
```json
{
  "code": 0,
  "data": [
    {
      "msg_id": "msg_005",
      "session_id": "sess_001",
      "message": "How are you?",
      "task_id": "task_001",
      "task_result": "Task completed successfully",
      "create_time": "2026-05-20T10:02:00",
      "update_time": "2026-05-20T10:02:00"
    }
  ],
  "message": "OK"
}
```

---

### API Key Management

Base path: `/api/v1/apikey`

All API key management endpoints are **admin only**.

#### POST /api/v1/apikey

Create a new API key.

**Authentication:** Required. Admin only.

**Request Body:**
```json
{
  "name": "My App Key",
  "role": "user",
  "rate_limit": 60,
  "session_ids": ["sess_001", "sess_002"]
}
```

**Fields:**
- `name` (str, required): Human-readable name for the key.
- `role` (str, optional): Role (`admin` or `user`). Default: `user`.
- `rate_limit` (int, optional): Max messages per minute. `0` = unlimited. Default: `0` for admin, `60` for user.
- `session_ids` (list[str], optional): Sessions to bind (user role only).

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "api_key_id": "ak_a1b2c3d4",
    "api_key": "a1b2c3d4e5f6...",
    "name": "My App Key",
    "role": "user",
    "rate_limit": 60,
    "is_active": true,
    "create_time": "2026-05-20T17:12:18",
    "update_time": "2026-05-20T17:12:18"
  },
  "message": "API key created successfully"
}
```

**Note:** The `api_key` value is shown only on creation. Store it securely.

**Errors:**
- `400`: Invalid role or negative `rate_limit`.

---

#### GET /api/v1/apikey

List API keys. Admin sees all keys; user sees only their own key.

**Authentication:** Required.

**Query Parameters:**
- `session_id` (str, optional): Filter API keys by bound session ID. Admin can filter by any session; user can only filter by sessions they are bound to.

**Response (200) - Admin:**
```json
{
  "code": 0,
  "data": {
    "api_keys": [
      {
        "api_key_id": "ak_a1b2c3d4",
        "api_key": "a1b2c3d4e5f6...",
        "name": "My App Key",
        "role": "user",
        "rate_limit": 60,
        "is_active": true,
        "create_time": "2026-05-20T17:12:18",
        "update_time": "2026-05-20T17:12:18",
        "sessions": ["sess_001", "sess_002"],
        "environs": [
          {
            "api_key_id": "ak_a1b2c3d4",
            "key": "CUSTOM_VAR",
            "value": "custom_value"
          }
        ]
      }
    ],
    "total": 1
  },
  "message": "OK"
}
```

**Response (200) - User:**
```json
{
  "code": 0,
  "data": {
    "api_keys": [
      {
        "api_key_id": "ak_a1b2c3d4",
        "api_key": "a1b2c3d4e5f6...",
        "name": "My App Key",
        "role": "user",
        "rate_limit": 60,
        "is_active": true,
        "create_time": "2026-05-20T17:12:18",
        "update_time": "2026-05-20T17:12:18",
        "sessions": ["sess_001", "sess_002"],
        "environs": []
      }
    ],
    "total": 1
  },
  "message": "OK"
}
```

**Errors:**
- `403`: User attempting to filter by a session_id they are not bound to.

---

#### DELETE /api/v1/apikey/{api_key_id}

Delete an API key and its related bindings and rate limit logs.

**Authentication:** Required. Admin only.

**Path Parameters:**
- `api_key_id` (str, required): The API key identifier.

**Response (200):**
```json
{
  "code": 0,
  "data": null,
  "message": "API key deleted successfully"
}
```

**Errors:**
- `404`: API key not found.
- `400`: Cannot delete the last admin API key.

---

#### POST /api/v1/apikey/{api_key_id}/sessions

Bind sessions to an existing user API key.

**Authentication:** Required. Admin only.

**Path Parameters:**
- `api_key_id` (str, required): The API key identifier.

**Request Body:**
```json
{
  "session_ids": ["sess_003", "sess_004"]
}
```

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "bound_sessions": ["sess_003", "sess_004"]
  },
  "message": "Sessions bound successfully"
}
```

**Errors:**
- `404`: API key not found.
- `400`: Cannot bind sessions to an admin API key.

---

#### DELETE /api/v1/apikey/{api_key_id}/sessions

Unbind sessions from a user API key.

**Authentication:** Required. Admin only.

**Path Parameters:**
- `api_key_id` (str, required): The API key identifier.

**Request Body:**
```json
{
  "session_ids": ["sess_003"]
}
```

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "unbound_sessions": ["sess_003"]
  },
  "message": "Sessions unbound successfully"
}
```

**Errors:**
- `404`: API key not found.

---

#### POST /api/v1/apikey/{api_key_id}/environs

Set an environment variable for an API key. Creates a new entry if the key does not exist; updates it otherwise.

**Authentication:** Required. Admin only.

**Path Parameters:**
- `api_key_id` (str, required): The API key identifier.

**Request Body:**
```json
{
  "key": "CUSTOM_VAR",
  "value": "custom_value"
}
```

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "api_key_id": "ak_a1b2c3d4",
    "key": "CUSTOM_VAR",
    "value": "custom_value"
  },
  "message": "Environment variable set successfully"
}
```

**Errors:**
- `404`: API key not found.

---

#### GET /api/v1/apikey/{api_key_id}/environs

List all environment variables for an API key.

**Authentication:** Required. Admin only.

**Path Parameters:**
- `api_key_id` (str, required): The API key identifier.

**Response (200):**
```json
{
  "code": 0,
  "data": {
    "environs": [
      {
        "api_key_id": "ak_a1b2c3d4",
        "key": "CUSTOM_VAR",
        "value": "custom_value"
      }
    ],
    "total": 1
  },
  "message": "OK"
}
```

**Errors:**
- `404`: API key not found.

---

#### DELETE /api/v1/apikey/{api_key_id}/environs/{key}

Delete an environment variable for an API key.

**Authentication:** Required. Admin only.

**Path Parameters:**
- `api_key_id` (str, required): The API key identifier.
- `key` (str, required): The environment variable name.

**Response (200):**
```json
{
  "code": 0,
  "data": null,
  "message": "Environment variable deleted successfully"
}
```

**Errors:**
- `404`: API key not found, or environment variable not found.

---

## Data Models

### Session

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | str | Primary key, session identifier |
| `session_name` | str | Human-readable session name |
| `task` | str \| null | Task info, default null |
| `create_time` | datetime | Record creation time |
| `update_time` | datetime | Last update time |
| `processed_msg_id` | str \| null | Most recently processed message ID |

### Message

| Field | Type | Description |
|-------|------|-------------|
| `msg_id` | str | Message identifier (part of composite PK with `session_id`) |
| `session_id` | str | Parent session identifier |
| `message` | str | Message content |
| `role` | str | `user` or `assistant` |
| `create_time` | datetime | Record creation time |
| `update_time` | datetime | Last update time |
| `task_id` | str \| null | Generated task ID, default null |
| `task_result` | str \| null | Task execution result, default null |
| `processed_msg_id` | str \| null | Reference to processed message |

### API Key

| Field | Type | Description |
|-------|------|-------------|
| `api_key_id` | str | Primary key, prefixed with `ak_` |
| `api_key` | str | The actual key value (64-char hex) |
| `name` | str | Human-readable name |
| `role` | str | `admin` or `user` |
| `rate_limit` | int | Max messages per minute, `0` = unlimited |
| `is_active` | bool | Whether the key is active |
| `create_time` | datetime | Record creation time |
| `update_time` | datetime | Last update time |
| `sessions` | list[str] | Bound session IDs (included in list response) |
| `environs` | list[dict] | Environment variables (included in list response) |

| `api_key_id` | str | Parent API key identifier |
| `key` | str | Environment variable name |
| `value` | str | Environment variable value |

---

## Environment Variables

The following environment variables control API behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_AGENT_DAEMON_HOST` | `0.0.0.0` | Server listen IP |
| `TOPSAILAI_AGENT_DAEMON_PORT` | `7373` | Server listen port |
| `TOPSAILAI_AGENT_DAEMON_DB_URL` | `sqlite:///topsailai_agent_daemon.db` | Database URL |
| `TOPSAILAI_AGENT_DAEMON_LOG_LEVEL` | `INFO` | Log level |
| `TOPSAILAI_AGENT_DAEMON_PROCESSOR` | (required) | Message processor script path |
| `TOPSAILAI_AGENT_DAEMON_SUMMARIZER` | (required) | Message summarizer script path |
| `TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER` | (required) | Session state checker script path |
| `TOPSAILAI_AGENT_DAEMON_API_KEY_ENABLED` | `false` | Enable API key authentication |
| `TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY` | (generated) | Pre-configured default admin API key |
| `TOPSAILAI_AGENT_DAEMON_AUTH_STYLE` | `x-api-key` | Client authentication header style: `x-api-key` or `bearer` |
| `TOPSAILAI_AGENT_DAEMON_BASE_URL` | `http://127.0.0.1:7373` | Client base URL |
| `TOPSAILAI_AGENT_DAEMON_API_KEY` | (none) | Client API key |
| `TOPSAILAI_AGENT_DAEMON_UNPROCESSED_MSG_INCLUDED_ROLES` | `user` | Roles included in unprocessed messages |


## Client Authentication

The Python client (`topsailai_agent_client.py`), terminal client (`topsailai_agent_terminal.py`), and Go client (`client_go/topsailai_send_message.go`) support selecting the authentication header style.

### Python Client

Use the `--auth-style` argument to choose the header style:

```bash
# Use X-API-Key header (default)
python topsailai_agent_client.py --auth-style x-api-key --api-key YOUR_KEY session list

# Use Authorization Bearer header
python topsailai_agent_client.py --auth-style bearer --api-key YOUR_KEY session list
```

The default style can also be set via the `TOPSAILAI_AGENT_DAEMON_AUTH_STYLE` environment variable.

### Terminal Client

```bash
# Use X-API-Key header (default)
python topsailai_agent_terminal.py --auth-style x-api-key --api-key YOUR_KEY

# Use Authorization Bearer header
python topsailai_agent_terminal.py --auth-style bearer --api-key YOUR_KEY
```

### Go Client

```bash
# Use X-API-Key header (default)
go run client_go/topsailai_send_message.go -auth-style x-api-key -api-key YOUR_KEY

# Use Authorization Bearer header
go run client_go/topsailai_send_message.go -auth-style bearer -api-key YOUR_KEY
```

The default style can also be set via the `TOPSAILAI_AGENT_DAEMON_AUTH_STYLE` environment variable.
---

## Error Codes Summary

| HTTP Status | Code | Meaning |
|-------------|------|---------|
| 200 | 0 | Success |
| 400 | -1 or 400 | Bad request / validation error |
| 401 | 401 | Missing or invalid API key |
| 403 | 403 | Permission denied |
| 404 | 404 | Resource not found |
| 429 | 429 | Rate limit exceeded |
| 500 | 500 | Internal server error |

---

## Message Processing Flow

1. A message is received via `POST /api/v1/message`.
2. The message is saved to the `message` table.
3. The session's `processed_msg_id` is checked against the latest message.
4. If there are unprocessed messages (messages after `processed_msg_id` with `role != assistant`):
   - Messages are concatenated into a markdown-formatted "unprocessed message" block.
   - The `TOPSAILAI_AGENT_DAEMON_PROCESSOR` script is executed as a new process with environment variables (`TOPSAILAI_MSG_ID`, `TOPSAILAI_TASK`, `TOPSAILAI_SESSION_ID`).
   - The processor's PID is returned in the response.
5. After the processor completes, it calls either:
   - `POST /api/v1/message` with the answer (no task generated), or
   - `POST /api/v1/task` with `task_id` and `task_result`.
6. The session's `processed_msg_id` is updated to the latest processed message.

### Unprocessed Message Format

```markdown
---
msg4 content
---
msg5 content
>>> task_id: task_001
>>> task_result: Task result text
---
```

The `task_id` and `task_result` lines are included only when present on the message record.
