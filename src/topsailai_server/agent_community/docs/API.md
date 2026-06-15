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

## Group Endpoints

### Create Group

**POST /api/v1/groups**

Create a new group (community/session).

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
  "member_name": "Research Agent",
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
  "member_name": "Alice Updated",
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
    "member_name": "Alice Updated",
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
        "member_name": "Research Agent",
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
            "member_name": "Research Agent",
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
      "member_name": "Research Agent",
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
    "ACS_AGENT_API_AUTH": "BearerToken"
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
