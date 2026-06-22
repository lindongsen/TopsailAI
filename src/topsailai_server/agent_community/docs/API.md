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
  "status": "alive"
}
```

### Readiness Check

**GET /readyz**

Returns 200 if the server is ready to serve requests (database connected).
Returns 503 if dependencies are not ready.

**Response (ready):**
```json
{
  "status": "ready",
  "timestamp": "2024-01-01T00:00:00Z",
  "checks": {
    "database": "ok",
    "nats": "ok"
  }
}
```

**Response (not ready):**
```json
{
  "status": "not ready",
  "timestamp": "2024-01-01T00:00:00Z",
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
  "version": "v0.1.0",
  "timestamp": "2024-01-01T00:00:00Z",
  "checks": {
    "database": "ok",
    "nats": "ok"
  }
}
```

### Service Leader

**GET /health/leader**

Returns whether the current service instance is the elected Service-Leader.

**Response:**
```json
{
  "data": {
    "is_leader": true,
    "service_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "trace_id": "..."
}
```

**Response 503 Service Unavailable:**
- Service discovery is disabled (`ACS_DISCOVERY_ENABLED=false`).

---

## Service Discovery Endpoints

### List Registered Services

**GET /discovery/services**

List all service instances currently registered in NATS KV service discovery.

**Authentication:** Required.

**Response:**
```json
{
  "data": {
    "items": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "acs",
        "address": "http://10.0.0.1:7370",
        "registered_at_ms": 1704067200000,
        "last_heartbeat_ms": 1704067230000
      }
    ],
    "leader_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "trace_id": "..."
}
```

**Response 503 Service Unavailable:**
- Service discovery is disabled (`ACS_DISCOVERY_ENABLED=false`).

---

## Authentication

All API endpoints except health checks (`/healthz`, `/readyz`, `/health`, `/health/leader`) and the login endpoint (`POST /api/v1/accounts/login`) require authentication.

ACS supports two authentication methods. Only one method should be used per request.

> **Authentication Priority:** When multiple credentials are present, the server resolves the caller in the following priority: `login_name_password > login_session_key > api_key`. API requests should typically include only one authentication form.

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

A session key is returned by the login or session creation endpoints. It is valid until `expires_at_ms`.

### Authorization Roles

ACS uses a role hierarchy: `admin > manager > user`.

- `admin`: Can manage all resources including accounts, API keys, groups, and audit logs.
- `manager`: Can create user accounts, query accounts by id/external_id, and create login sessions for user accounts. Cannot create API keys.
- `user`: Can manage their own resources (account, API keys, groups they are members of) and query all non-deleted accounts for discovery.

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

**Authentication:** Required.
- `admin` can list all accounts.
- `manager` can list accounts with limited fields (sensitive fields such as `login_password`, `login_session_key`, and API keys are omitted).
- `user` can list all non-deleted accounts with the same limited fields.

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
- `user` can access any non-deleted account with the same limited fields.

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
    "session_key": "acc-abc123-550e8400e29b41d4a716446655440000",
    "expires_at_ms": 1704153600000
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
    "session_key": "acc-abc123-550e8400e29b41d4a716446655440000",
    "expires_at_ms": 1704153600000
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

**Authentication:** Required.
- Any authenticated account can create a group.
- The caller becomes the group `creator_id` and `owner_id`.

When the server is configured with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT`, a default `manager-agent` member is automatically joined to the new group as part of the same transaction. The auto-joined member uses the configured manager-agent adaptor, API settings, and timeouts. See `docs/Environment_Variables.md` for the full list of manager-agent auto-join environment variables.

**Request Body:**
```json
{
  "group_name": "AI Research Team",
  "group_context": "A group for AI research discussions",
  "group_key": "optional-secret-key"
}
```

> **Note on `group_key`:** The value is stored as a hash. An empty or omitted `group_key` means the group is public. The API never returns the plaintext key.

**Response:**
```json
{
  "data": {
    "group_id": "group-abc123",
    "group_name": "AI Research Team",
    "group_context": "A group for AI research discussions",
    "group_key": "",
    "creator_id": "acc-abc123",
    "owner_id": "acc-abc123",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### List Groups

**GET /api/v1/groups**

List all groups with pagination and filtering.

**Authentication:** Required.
- `admin` can list all groups.
- `user` can only list groups where they are a member.

**Query Parameters:**
- offset, limit, sort_key, order_by, create_at_ms, update_at_ms

**Response:**
```json
{
  "data": {
    "items": [
      {
        "group_id": "group-abc123",
        "group_name": "AI Research Team",
        "group_context": "A group for AI research discussions",
        "group_key": "",
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

### Get Group

**GET /api/v1/groups/:group_id**

Get a single group by ID.

**Authentication:** Required.
- `admin` can access any group.
- `user` can only access groups where they are a member.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format (e.g., `group-abc123`)

**Response:**
```json
{
  "data": {
    "group_id": "group-abc123",
    "group_name": "AI Research Team",
    "group_context": "A group for AI research discussions",
    "group_key": "",
    "creator_id": "acc-abc123",
    "owner_id": "acc-abc123",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### Update Group

**PUT /api/v1/groups/:group_id**

Update group information.

**Authentication:** Required.
- `admin` can update any group.
- `user` can update only groups they own.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format

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
    "group_id": "group-abc123",
    "group_name": "Updated Name",
    "group_context": "Updated context",
    "group_key": "",
    "creator_id": "acc-abc123",
    "owner_id": "acc-abc123",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067300000
  },
  "trace_id": "..."
}
```

### Delete Group

**DELETE /api/v1/groups/:group_id**

Delete a group and all associated data (members, messages).

**Authentication:** Required.
- `admin` can delete any group.
- `user` can delete only groups they own.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format

**Response:**

`204 No Content`

---

## Group Member Endpoints

### Join Group

**POST /api/v1/groups/:group_id/members**

Add a member (user or agent) to a group, or self-join a group using its access key.

**Authentication:** Required.
- `admin` can add members to any group.
- Group `owner` can add members to groups they own.
- Any authenticated account can **self-join** a public group (a group whose `group_key` is null/empty).
- Any authenticated account can **self-join** a private group by providing the correct `group_key` in the request body.

When self-joining, the server ignores any `member_id` and `member_type` supplied by the client and overrides them as follows:
- `member_id` is set to the caller's `account_id`.
- `member_type` is set to `user`.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format

**Request Body (owner/admin adding a member):**
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

**Request Body (self-joining a private group):**
```json
{
  "member_name": "Alice",
  "member_description": "Project manager",
  "group_key": "optional-secret-key"
}
```

- `group_key` is required when self-joining a private group. It is ignored when an `admin` or group owner adds a member.
- `member_name` and `member_description` may be provided for self-joins; `member_id` and `member_type` are overridden by the server.

**Response:**
```json
{
  "data": {
    "group_id": "group-abc123",
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

**Response 201 Created:**
- Returned on successful join.

**Response 403 Forbidden:**
- Caller lacks permission to add a member to the group.
- Self-join attempt on a private group without a `group_key`, or with an incorrect `group_key`.

**Response 404 Not Found:**
- Group does not exist.

### List Group Members

**GET /api/v1/groups/:group_id/members**

List all members of a group.

**Authentication:** Required.
- `admin` can list members of any group.
- `user` can list members only for groups where they are a member.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format

**Query Parameters:**
- offset, limit, sort_key, order_by

**Response:**
```json
{
  "data": {
    "items": [
      {
        "group_id": "group-abc123",
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

**Authentication:** Required.
- `admin` can update any member.
- `user` can update their own member record in groups where they are a member.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format
- member_id: string

**Request Body:**
```json
{
  "member_name": "Alice_Updated",
  "member_description": "Updated description",
  "member_status": "idle",
  "member_interface": {},
  "last_read_message_id": "msg-001"
}
```

**Response:**
```json
{
  "data": {
    "group_id": "group-abc123",
    "member_id": "user-001",
    "member_name": "Alice_Updated",
    "member_description": "Updated description",
    "member_status": "idle",
    "member_type": "user",
    "member_interface": {},
    "last_read_message_id": "msg-001",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067300000
  },
  "trace_id": "..."
}
```

### Leave Group

**DELETE /api/v1/groups/:group_id/members/:member_id**

Remove a member from a group.

**Authentication:** Required.
- `admin` can remove any member.
- `user` can remove only their own member record.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format
- member_id: string

**Response:**

`204 No Content`

---

## Message Endpoints

### Create Message

**POST /api/v1/groups/:group_id/messages**

Send a message to a group. The authenticated caller is used as the message sender; `sender_id` and `sender_type` are derived from the current account or session and must not be supplied in the request body.

Mentions in the message text (e.g., `@agent-001`, `@all`) are automatically extracted and may trigger agent responses. Automatic triggers respect `NO_TRIGGER_CASES` (e.g., messages from agents are not re-triggered). To force agent processing on any message regardless of these restrictions, use the **Trigger Message** endpoint.

**Authentication:** Required.
- `admin` can send messages to any group.
- `user` can send messages only to groups where they are a member.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format

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
  ]
}
```

**Response:**
```json
{
  "data": {
    "message_id": "msg-001",
    "group_id": "group-abc123",
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

**Authentication:** Required.
- `admin` can list messages in any group.
- `user` can list messages only in groups where they are a member.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format

**Query Parameters:**
- offset, limit, sort_key, order_by, create_at_ms, update_at_ms, processed_msg_id

**Example Request:**
```bash
GET /api/v1/groups/group-abc123/messages?processed_msg_id=msg-001&limit=10
```

**Response:**
```json
{
  "data": {
    "items": [
      {
        "message_id": "msg-001",
        "group_id": "group-abc123",
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

**Authentication:** Required.
- `admin` can update any message.
- `user` can update only messages they sent.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format
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
    "group_id": "group-abc123",
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

**Authentication:** Required.
- `admin` can delete any message.
- `user` can delete only messages they sent.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format
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

**Authentication:** Required.
- `admin` can trigger any message.
- `user` can trigger only messages in groups where they are a member.

**Path Parameters:**
- group_id: group identifier in `group-{id}` format
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
    "group_id": "group-abc123",
    "trigger": {
      "type": "manual",
      "agent_id": "agent-123"
    },
    "status": "pending"
  },
  "trace_id": "..."
}
```

When no agents are resolved for the message, the response status is `no_agents_to_trigger`:

```json
{
  "data": {
    "message_id": "msg-001",
    "group_id": "group-abc123",
    "trigger": {
      "type": "manual",
      "agent_id": ""
    },
    "status": "no_agents_to_trigger"
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

## Agent Triggering

The following rules determine whether a message triggers agent processing.

### NO_TRIGGER_CASES

A message will **not** be automatically triggered when any of the following is true:

1. The message `sender_type` ends with `-agent`.
2. The message has a non-empty `processed_msg_id`.
3. Within the 10 messages before and 10 messages after the target message, there is a sliding window of more than 10 consecutive messages whose sender type ends with `-agent`.

### Trigger via Mentions

Mentions are extracted from `@member_id` or `@member_name` references in the message text.

1. **Single agent mention:** If the only mentioned member is an agent (type ends with `-agent`), that agent is invoked with `ACS_AGENT_MODE=agent`.
2. **Multiple agent mentions without manager-agent:** All mentioned agents are invoked concurrently with `ACS_AGENT_MODE=agent`. The message is appended with: `! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !`
3. **Multiple agent mentions with manager-agent:** If one or more manager-agents are mentioned, a single randomly selected manager-agent is invoked with `ACS_AGENT_MODE=agent`.
4. **`@all` mention:** Always triggers a manager-agent with `ACS_AGENT_MODE=agent`. This case has the highest priority.

### Auto-Trigger

1. **Single user group:** If a group contains only one user and the message has no mentions, the manager-agent is triggered with `ACS_AGENT_MODE=agent`.
2. **Idle timeout:** If the last message was sent by a user and more than `ACS_AGENT_AUTO_TRIGGER_TIMEOUT` (default `10m`) has passed, the manager-agent is triggered with `ACS_AGENT_MODE=agent`. This is evaluated by a periodic task that uses a NATS KV distributed lock.

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
  "groupId": "group-abc123",
  "data": {
    "group_id": "group-abc123",
    "group_name": "AI Research Team",
    "group_context": "A group for AI research discussions",
    "group_key": "",
    "creator_id": "acc-abc123",
    "owner_id": "acc-abc123",
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
  "groupId": "group-abc123",
  "data": {
    "message_id": "msg-001",
    "group_id": "group-abc123",
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
  "groupId": "group-abc123",
  "data": {
    "group_id": "group-abc123",
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
  "group_id": "group-abc123",
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

### Runtime Environment Variables

In addition to the variables declared in `member_interface.environments`, ACS injects the following runtime variables when invoking an agent:

| Variable | Description |
|----------|-------------|
| `ACS_LOGIN_SESSION_KEY` | Plaintext login session key of the original message sender. Only injected when the triggered agent is a `manager-agent`. If the sender has no valid session or it has expired, a new session key is generated automatically. |
