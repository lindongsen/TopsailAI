---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# AI-Agent Community Server (ACS) - API Documentation

## Base URL

All API endpoints are prefixed with the server base URL. Default: `http://localhost:7370`

## Response Format

All responses use JSON format with the following structure:

```json
{
  "data": { ... },
  "error": "error message if any",
  "trace_id": "uuid-string"
}
```

## Common Query Parameters

The following query parameters are supported on list endpoints:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| offset | int | 0 | Number of records to skip |
| limit | int | 1000 | Maximum number of records to return |
| sort_key | string | create_at_ms | Field to sort by |
| order_by | string | desc | Sort direction: `asc` or `desc` |
| create_at_ms | string | - | Time range filter, format: `{startTime}-{endTime}` (epoch ms) |
| update_at_ms | string | - | Time range filter, format: `{startTime}-{endTime}` (epoch ms) |

---

## Health Endpoints

### Liveness Check

**GET /healthz**

Returns 200 if the server process is alive.

**Response:**
```json
{
  "status": "ok"
}
```

### Readiness Check

**GET /readyz**

Returns 200 if the server is ready to serve requests (database connected).
Returns 503 if dependencies are not ready.

**Response (ready):**
```json
{
  "status": "ready"
}
```

**Response (not ready):**
```json
{
  "status": "not ready",
  "checks": {
    "database": "unreachable"
  }
}
```

### Comprehensive Health

**GET /health**

Returns detailed health status of all components.

**Response:**
```json
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "nats": "ok"
  }
}
```

---

## Authentication

All API endpoints except health checks (`/healthz`, `/readyz`, `/health`) and the login endpoint (`POST /api/v1/accounts/login`) require authentication.

ACS supports two authentication methods. Only one method should be used per request.

### API Key Authentication

Include the API key in the `Authorization` header using the `Bearer` scheme.

```
Authorization: Bearer {api_key_id}.{secret}
```

- `api_key_id`: The API key identifier in the format `ak-{alphanumeric}`.
- `secret`: The plaintext secret portion generated when the key was created.

Example:

```
Authorization: Bearer ak-abc123.xYz789SecretValue
```

The API key must be `active` and its `role` must not exceed the role of the owning account.

### Session Key Authentication

Include the session key in the `X-Session-Key` header.

```
X-Session-Key: {session_key}
```

A session key is returned by the login or session creation endpoints. It is valid until `login_session_expired_time`.

### Authorization Roles

ACS uses a role hierarchy: `admin > manager > user`.

- `admin`: Can manage all resources including accounts, API keys, and audit logs.
- `manager`: Can create user accounts, query accounts by id/external_id, and create login sessions for user accounts. Cannot create API keys.
- `user`: Can manage their own resources (account, API keys, groups they are members of).

Requests that do not meet the required role are rejected with `403 Forbidden`.

---

## Account Endpoints

### Create Account

**POST /api/v1/accounts**

Create a new account.

**Authentication:** Required (`admin` or `manager`).
- `admin` can create accounts with any role.
- `manager` can only create accounts with `role=user`.

**Request Body:**
```json
{
  "account_name": "Alice Smith",
  "account_description": "Project manager",
  "role": "user",
  "login_name": "alice@example.com",
  "login_password": "secure-password",
  "external_id": "ext-123",
  "email": "alice@example.com",
  "auth_provider": "oidc",
  "avatar_url": "https://example.com/avatar.png"
}
```

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "account_name": "Alice Smith",
    "account_description": "Project manager",
    "role": "user",
    "status": "active",
    "external_id": "ext-123",
    "email": "alice@example.com",
    "auth_provider": "oidc",
    "avatar_url": "https://example.com/avatar.png",
    "login_name": "alice@example.com",
    "login_session_expired_time": 0,
    "creator_id": "acc-admin001",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

**Response 400 Bad Request:**
- Invalid request body.
- `login_name` already exists.
- `role` is not allowed for the caller.

**Response 403 Forbidden:**
- Caller does not have permission to create accounts.

---

### List Accounts

**GET /api/v1/accounts**

List accounts with pagination and filtering.

**Authentication:** Required (`admin` or `manager`).
- `admin` can list all accounts.
- `manager` can list accounts with limited fields (sensitive fields such as `login_password`, `login_session_key`, and API keys are omitted).

**Query Parameters:**
- offset, limit, sort_key, order_by, create_at_ms, update_at_ms
- `role`: filter by role
- `status`: filter by status
- `external_id`: filter by external id

**Response:**
```json
{
  "data": {
    "items": [
      {
        "account_id": "acc-abc123",
        "account_name": "Alice Smith",
        "role": "user",
        "status": "active",
        "email": "alice@example.com",
        "login_name": "alice@example.com",
        "create_at_ms": 1704067200000,
        "update_at_ms": 1704067200000
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

---

### Get Current Account

**GET /api/v1/accounts/me**

Return the account associated with the current authentication credentials.

**Authentication:** Required.

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "account_name": "Alice Smith",
    "account_description": "Project manager",
    "role": "user",
    "status": "active",
    "external_id": "ext-123",
    "email": "alice@example.com",
    "auth_provider": "oidc",
    "avatar_url": "https://example.com/avatar.png",
    "login_name": "alice@example.com",
    "login_session_expired_time": 0,
    "creator_id": "acc-admin001",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

---

### Get Account

**GET /api/v1/accounts/:account_id**

Get a single account by ID.

**Authentication:** Required.
- `admin` can access any account.
- `manager` can query accounts by id or external_id with limited fields.
- `user` can only access their own account.

**Path Parameters:**
- account_id: account identifier (e.g., `acc-abc123`)

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "account_name": "Alice Smith",
    "account_description": "Project manager",
    "role": "user",
    "status": "active",
    "external_id": "ext-123",
    "email": "alice@example.com",
    "auth_provider": "oidc",
    "avatar_url": "https://example.com/avatar.png",
    "login_name": "alice@example.com",
    "login_session_expired_time": 0,
    "creator_id": "acc-admin001",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

**Response 404 Not Found:**
- Account does not exist.

---

### Update Account

**PUT /api/v1/accounts/:account_id**

Update account information.

**Authentication:** Required.
- `admin` can update any account, including `role` and `status`.
- `user` can update only their own account and cannot change `role` or `status`.
- `manager` cannot update accounts except for creating login sessions.

**Path Parameters:**
- account_id: account identifier

**Request Body:**
```json
{
  "account_name": "Alice Smith-Updated",
  "account_description": "Updated description",
  "avatar_url": "https://example.com/avatar2.png"
}
```

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "account_name": "Alice Smith-Updated",
    "account_description": "Updated description",
    "role": "user",
    "status": "active",
    "avatar_url": "https://example.com/avatar2.png",
    "login_name": "alice@example.com",
    "update_at_ms": 1704067300000
  },
  "trace_id": "..."
}
```

**Response 400 Bad Request:**
- Invalid update fields.
- `login_name` already exists.

**Response 403 Forbidden:**
- Caller is not allowed to update the target account or field.

---

### Delete Account

**DELETE /api/v1/accounts/:account_id**

Soft-delete an account. The account `status` is set to `deleted` and `delete_at_ms` is populated. All API keys owned by the account are hard-deleted.

**Authentication:** Required (`admin`).

**Path Parameters:**
- account_id: account identifier

**Response:**
```json
{
  "data": {
    "message": "account deleted"
  },
  "trace_id": "..."
}
```

**Response 403 Forbidden:**
- Caller is not `admin`.

---

### Login

**POST /api/v1/accounts/login**

Authenticate with `login_name` and `login_password`. On success, a new login session key is created and returned.

**Authentication:** Not required.

**Request Body:**
```json
{
  "login_name": "alice@example.com",
  "login_password": "secure-password"
}
```

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "account_name": "Alice Smith",
    "role": "user",
    "session_key": "acc-abc123-550e8400e29b41d4a716446655440000",
    "login_session_expired_time": 1704153600000
  },
  "trace_id": "..."
}
```

**Response 401 Unauthorized:**
- Invalid login name or password.

**Response 400 Bad Request:**
- Account `status` is not `active`.

---

### Change Password

**POST /api/v1/accounts/:account_id/password**

Change the `login_password` for an account. Any valid authentication method can be used to authorize this request.

**Authentication:** Required.
- `admin` can change any account password.
- `user` can only change their own password.

**Path Parameters:**
- account_id: account identifier

**Request Body:**
```json
{
  "old_password": "secure-password",
  "new_password": "new-secure-password"
}
```

**Response:**
```json
{
  "data": {
    "message": "password updated"
  },
  "trace_id": "..."
}
```

**Response 400 Bad Request:**
- `old_password` does not match (for non-admin callers).
- New password is empty.

**Response 403 Forbidden:**
- Caller is not authorized to change the target account password.

---

### Create Login Session

**POST /api/v1/accounts/:account_id/session**

Create a new login session key for an account.

**Authentication:** Required.
- `admin` can create sessions for any account.
- `manager` can create sessions only for accounts with `role=user`.
- `user` can create sessions only for their own account.

**Path Parameters:**
- account_id: account identifier

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "account_name": "Alice Smith",
    "role": "user",
    "session_key": "acc-abc123-550e8400e29b41d4a716446655440000",
    "login_session_expired_time": 1704153600000
  },
  "trace_id": "..."
}
```

**Response 403 Forbidden:**
- Caller role is not allowed to create a session for the target account role.

---

## API Key Endpoints

### Create API Key

**POST /api/v1/accounts/:account_id/api-keys**

Create a new API key for an account.

**Authentication:** Required.
- `admin` can create API keys for any account with any role.
- `user` can create API keys only for their own account, and the key `role` cannot exceed `user`.
- `manager` cannot create API keys.

**Path Parameters:**
- account_id: account identifier

**Request Body:**
```json
{
  "api_key_name": "CLI Key",
  "role": "user"
}
```

**Response:**
```json
{
  "data": {
    "account_id": "acc-abc123",
    "api_key_id": "ak-xyz789",
    "api_key_name": "CLI Key",
    "role": "user",
    "status": "active",
    "token": "ak-xyz789.PlaintextSecretValue",
    "creator_id": "acc-abc123",
    "owner_id": "acc-abc123",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

**Important:** The plaintext `token` is returned only once on creation. Store it securely.

**Response 400 Bad Request:**
- API key role exceeds account role.
- Owner has reached the maximum number of API keys (`ACS_API_KEY_MAX_PER_ACCOUNT`).

**Response 403 Forbidden:**
- Caller is not authorized to create API keys for the target account.

---

### List API Keys

**GET /api/v1/accounts/:account_id/api-keys**

List API keys for an account.

**Authentication:** Required.
- `admin` can list API keys for any account.
- `user` can list API keys only for their own account.

**Path Parameters:**
- account_id: account identifier

**Query Parameters:**
- offset, limit, sort_key, order_by, status

**Response:**
```json
{
  "data": {
    "items": [
      {
        "api_key_id": "ak-xyz789",
        "api_key_name": "CLI Key",
        "role": "user",
        "status": "active",
        "creator_id": "acc-abc123",
        "owner_id": "acc-abc123",
        "create_at_ms": 1704067200000,
        "update_at_ms": 1704067200000
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

---

### Delete API Key

**DELETE /api/v1/accounts/:account_id/api-keys/:api_key_id**

Delete an API key.

**Authentication:** Required.
- `admin` can delete any API key.
- `user` can delete API keys only for their own account.

**Path Parameters:**
- account_id: account identifier
- api_key_id: API key identifier

**Response:**
```json
{
  "data": {
    "message": "api key deleted"
  },
  "trace_id": "..."
}
```

**Response 404 Not Found:**
- API key does not exist or does not belong to the account.

---

## Audit Log Endpoints

### List Audit Logs

**GET /api/v1/audit-logs**

List audit log entries.

**Authentication:** Required (`admin`).

**Query Parameters:**
- offset, limit, sort_key, order_by, create_at_ms, update_at_ms
- `account_id`: filter by account
- `api_key_id`: filter by API key
- `action`: filter by action
- `resource_type`: filter by resource type
- `resource_id`: filter by resource id

**Response:**
```json
{
  "data": {
    "items": [
      {
        "audit_log_id": "al-001",
        "account_id": "acc-abc123",
        "api_key_id": "ak-xyz789",
        "action": "create_account",
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
    "limit": 1000
  },
  "trace_id": "..."
}
```

---

### Get Audit Log

**GET /api/v1/audit-logs/:audit_log_id**

Get a single audit log entry.

**Authentication:** Required (`admin`).

**Path Parameters:**
- audit_log_id: audit log identifier

**Response:**
```json
{
  "data": {
    "audit_log_id": "al-001",
    "account_id": "acc-abc123",
    "api_key_id": "ak-xyz789",
    "action": "create_account",
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

**Response 404 Not Found:**
- Audit log entry does not exist.

---

## Group Endpoints

### Create Group

**POST /api/v1/groups**

Create a new group (community/session).

When the server is configured with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT`, a default `manager-agent` member is automatically joined to the new group as part of the same transaction. The auto-joined member uses the configured manager-agent adaptor, API settings, and timeouts. See `docs/Environment_Variables.md` for the full list of manager-agent auto-join environment variables.

**Request Body:**
```json
{
  "group_name": "AI Research Team",
  "group_context": "A group for AI research discussions",
  "group_key": "optional-secret-key"
}
```

**Response:**
```json
{
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "group_name": "AI Research Team",
    "group_context": "A group for AI research discussions",
    "group_key": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### List Groups

**GET /api/v1/groups**

List all groups with pagination and filtering.

**Query Parameters:**
- offset, limit, sort_key, order_by, create_at_ms, update_at_ms

**Response:**
```json
{
  "data": {
    "items": [
      {
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "group_name": "AI Research Team",
        "group_context": "A group for AI research discussions",
        "group_key": "",
        "create_at_ms": 1704067200000,
        "update_at_ms": 1704067200000
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

### Get Group

**GET /api/v1/groups/:group_id**

Get a single group by ID.

**Path Parameters:**
- group_id: UUID string

**Response:**
```json
{
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "group_name": "AI Research Team",
    "group_context": "A group for AI research discussions",
    "group_key": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### Update Group

**PUT /api/v1/groups/:group_id**

Update group information.

**Path Parameters:**
- group_id: UUID string

**Request Body:**
```json
{
  "group_name": "Updated Name",
  "group_context": "Updated context",
  "group_key": "new-secret-key"
}
```

**Response:**
```json
{
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "group_name": "Updated Name",
    "group_context": "Updated context",
    "group_key": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067300000
  },
  "trace_id": "..."
}
```

### Delete Group

**DELETE /api/v1/groups/:group_id**

Delete a group and all associated data (members, messages).

**Path Parameters:**
- group_id: UUID string

**Response:**
```json
{
  "data": {
    "message": "group deleted"
  },
  "trace_id": "..."
}
```

---

## Group Member Endpoints

### Join Group

**POST /api/v1/groups/:group_id/members**

Add a member (user or agent) to a group.

**Path Parameters:**
- group_id: UUID string

**Request Body:**
```json
{
  "member_id": "user-001",
  "member_name": "Alice",
  "member_description": "Project manager",
  "member_type": "user",
  "member_interface": {}
}
```

For agent members:
```json
{
  "member_id": "agent-001",
  "member_name": "Research_Agent",
  "member_description": "AI research assistant",
  "member_type": "worker-agent",
  "member_interface": {
    "adaptor": "topsailai_agent",
    "environments": {
      "ACS_AGENT_API_BASE": "http://172.18.0.4:7373",
      "ACS_AGENT_API_KEY": "secret-key"
    },
    "timeout_chat": 600
  }
}
```

**Response:**
```json
{
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "member_id": "user-001",
    "member_name": "Alice",
    "member_description": "Project manager",
    "member_status": "online",
    "member_type": "user",
    "member_interface": {},
    "last_read_message_id": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### List Group Members

**GET /api/v1/groups/:group_id/members**

List all members of a group.

**Path Parameters:**
- group_id: UUID string

**Query Parameters:**
- offset, limit, sort_key, order_by

**Response:**
```json
{
  "data": {
    "items": [
      {
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "member_id": "user-001",
        "member_name": "Alice",
        "member_description": "Project manager",
        "member_status": "online",
        "member_type": "user",
        "member_interface": {},
        "last_read_message_id": "",
        "create_at_ms": 1704067200000,
        "update_at_ms": 1704067200000
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

### Update Member

**PUT /api/v1/groups/:group_id/members/:member_id**

Update member information.

**Path Parameters:**
- group_id: UUID string
- member_id: string

**Request Body:**
```json
{
  "member_name": "Alice_Updated",
  "member_description": "Updated description",
  "member_status": "idle",
  "member_interface": {}
}
```

**Response:**
```json
{
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "member_id": "user-001",
    "member_name": "Alice_Updated",
    "member_description": "Updated description",
    "member_status": "idle",
    "member_type": "user",
    "member_interface": {},
    "last_read_message_id": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067300000
  },
  "trace_id": "..."
}
```

### Leave Group

**DELETE /api/v1/groups/:group_id/members/:member_id**

Remove a member from a group.

**Path Parameters:**
- group_id: UUID string
- member_id: string

**Response:**
```json
{
  "data": {
    "message": "member left group"
  },
  "trace_id": "..."
}
```

---

## Message Endpoints

### Create Message

**POST /api/v1/groups/:group_id/messages**

Send a message to a group. Mentions in the message text (e.g., `@agent-001`, `@all`) are automatically extracted and may trigger agent responses. Automatic triggers respect `NO_TRIGGER_CASES` (e.g., messages from agents are not re-triggered). To force agent processing on any message regardless of these restrictions, use the **Trigger Message** endpoint.

**Path Parameters:**
- group_id: UUID string

**Request Body:**
```json
{
  "message_text": "Hello @agent-001, can you help with this?",
  "message_attachments": [
    {
      "data": "base64-encoded-data",
      "size": 1024,
      "format": "image/png"
    }
  ],
  "sender_id": "user-001",
  "sender_type": "user"
}
```

**Response:**
```json
{
  "data": {
    "message_id": "msg-001",
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "message_text": "Hello @agent-001, can you help with this?",
    "message_attachments": [
      {
        "data": "base64-encoded-data",
        "size": 1024,
        "format": "image/png"
      }
    ],
    "sender_id": "user-001",
    "sender_type": "user",
    "processed_msg_id": "",
    "mentions": [
      {
        "member_id": "agent-001",
        "member_name": "Research_Agent",
        "member_type": "worker-agent"
      }
    ],
    "is_deleted": false,
    "delete_at_ms": 0,
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### List Messages

**GET /api/v1/groups/:group_id/messages**

List messages in a group with pagination and filtering.

**Path Parameters:**
- group_id: UUID string

**Query Parameters:**
- offset, limit, sort_key, order_by, create_at_ms, update_at_ms, processed_msg_id

**Example Request:**
```bash
GET /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/messages?processed_msg_id=msg-001&limit=10
```

**Response:**
```json
{
  "data": {
    "items": [
      {
        "message_id": "msg-001",
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "message_text": "Hello @agent-001, can you help with this?",
        "message_attachments": [],
        "sender_id": "user-001",
        "sender_type": "user",
        "processed_msg_id": "",
        "mentions": [
          {
            "member_id": "agent-001",
            "member_name": "Research_Agent",
            "member_type": "worker-agent"
          }
        ],
        "is_deleted": false,
        "delete_at_ms": 0,
        "create_at_ms": 1704067200000,
        "update_at_ms": 1704067200000
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 1000
  },
  "trace_id": "..."
}
```

### Update Message

**PUT /api/v1/groups/:group_id/messages/:message_id**

Update a message (e.g., edit content).

**Path Parameters:**
- group_id: UUID string
- message_id: string

**Request Body:**
```json
{
  "message_text": "Updated message text"
}
```

**Response:**
```json
{
  "data": {
    "message_id": "msg-001",
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "message_text": "Updated message text",
    "message_attachments": [],
    "sender_id": "user-001",
    "sender_type": "user",
    "processed_msg_id": "",
    "mentions": [],
    "is_deleted": false,
    "delete_at_ms": 0,
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067300000
  },
  "trace_id": "..."
}
```

### Delete Message

**DELETE /api/v1/groups/:group_id/messages/:message_id**

Soft-delete a message (clear content, mark as deleted). The message record remains but content is removed.

**Path Parameters:**
- group_id: UUID string
- message_id: string

**Response:**
```json
{
  "data": {
    "message": "message deleted"
  },
  "trace_id": "..."
}
```
### Trigger Message

**POST /api/v1/groups/:group_id/messages/:message_id/trigger**

Manually trigger agent processing for a specific message. This bypasses `NO_TRIGGER_CASES` restrictions that normally prevent automatic agent triggering (e.g., messages sent by agents, messages with `processed_msg_id` set, or messages in a long sequence of agent messages).

**Path Parameters:**
- group_id: UUID string
- message_id: string

**Request Body (optional):**
```json
{
  "agent_id": "agent-123"
}
```
- `agent_id`: Optional. If provided, only this specific agent will be triggered. Must be a member of the group with type ending in `-agent`. If omitted, the system will resolve target agents using the same rules as automatic triggers (mentions, manager-agent, auto-trigger).

**Response 202 Accepted:**
```json
{
  "data": {
    "message_id": "msg-001",
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "trigger": {
      "type": "manual",
      "agent_id": "agent-123"
    },
    "status": "pending"
  },
  "trace_id": "..."
}
```

**Response 404 Not Found:**
- Group does not exist.
- Message does not exist or does not belong to the group.
- Specified `agent_id` is not a member of the group.

**Response 400 Bad Request:**
- Specified `agent_id` is not an agent type (does not end with `-agent`).

**Response 500 Internal Server Error:**
- Database or NATS publish failure.


---

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "error": "invalid request body",
  "trace_id": "..."
}
```

### 404 Not Found
```json
{
  "error": "group not found",
  "trace_id": "..."
}
```

### 500 Internal Server Error
```json
{
  "error": "internal server error",
  "trace_id": "..."
}
```

---

## NATS Message Format

### Group Events

Published to: `{ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX}.{group_id}`

```json
{
  "type": "group",
  "action": "create",
  "groupId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "group_name": "AI Research Team",
    "group_context": "A group for AI research discussions",
    "group_key": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  }
}
```

### Message Events

```json
{
  "type": "message",
  "action": "create",
  "groupId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "message_id": "msg-001",
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "message_text": "Hello",
    "sender_id": "user-001",
    "sender_type": "user",
    "create_at_ms": 1704067200000
  }
}
```

### Member Events

```json
{
  "type": "group_member",
  "action": "create",
  "groupId": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "member_id": "user-001",
    "member_name": "Alice",
    "member_type": "user",
    "create_at_ms": 1704067200000
  }
}
```

### Pending Message

Published to: `{ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX}.{group_id}`

```json
{
  "message_id": "msg-001",
  "group_id": "550e8400-e29b-41d4-a716-446655440000",
  "message_text": "Hello @agent-001",
  "sender_id": "user-001",
  "sender_type": "user",
  "mentions": [
    {
      "member_id": "agent-001",
      "member_name": "Research_Agent",
      "member_type": "worker-agent"
    }
  ],
  "trigger": {
    "type": "mention",
    "agent_id": "agent-001"
  },
  "create_at_ms": 1704067200000
}
```

---

## Agent Interface Format

The `member_interface` field for agent members is a JSON object:

```json
{
  "adaptor": "topsailai_agent",
  "environments": {
    "ACS_AGENT_API_BASE": "http://172.18.0.4:7373",
    "ACS_AGENT_API_KEY": "secret-key",
    "ACS_AGENT_API_AUTH": "bearer"
  },
  "timeout_check_health": 5,
  "timeout_check_status": 5,
  "timeout_chat": 600,
  "cmd_check_health": "topsailai_agent_cmd_check_health",
  "cmd_check_status": "topsailai_agent_cmd_check_status",
  "cmd_chat": "topsailai_agent_cmd_chat"
}
```

For manager-agents, if `ACS_AGENT_API_BASE` is not set in the interface, it falls back to the environment variable `ACS_GROUP_MANAGER_AGENT_API_BASE`. Same for `ACS_AGENT_API_KEY` and `ACS_AGENT_API_AUTH`.
