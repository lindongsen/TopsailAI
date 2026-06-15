# ACS API Reference

## Base URL

Default: `http://localhost:7370`

Configurable via `ACS_SERVER_API_BASE` environment variable.

## Response Format

All API responses use the following JSON structure:

```json
{
  "data": { ... },
  "error": "error message if any",
  "trace_id": "uuid-string"
}
```

## Common Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| offset | int | 0 | Records to skip |
| limit | int | 1000 | Max records to return |
| sort_key | string | create_at_ms | Field to sort by |
| order_by | string | desc | Sort direction: `asc` or `desc` |
| create_at_ms | string | - | Time range filter `{start}-{end}` (epoch ms) |
| update_at_ms | string | - | Time range filter `{start}-{end}` (epoch ms) |

---

## Endpoints

### Health

| Method | Endpoint | Description | Client Method |
|--------|----------|-------------|---------------|
| GET | `/healthz` | Liveness probe | - |
| GET | `/readyz` | Readiness probe | - |
| GET | `/health` | Detailed health | - |

### Groups

| Method | Endpoint | Description | Client Method |
|--------|----------|-------------|---------------|
| POST | `/api/v1/groups` | Create group | `create_group(name, context, key)` |
| GET | `/api/v1/groups` | List groups | `list_groups()` |
| GET | `/api/v1/groups/:id` | Get group | `get_group(group_id)` |
| PUT | `/api/v1/groups/:id` | Update group | `update_group(group_id, **kwargs)` |
| DELETE | `/api/v1/groups/:id` | Delete group | `delete_group(group_id)` |

**Create Group Request Body:**
```json
{
  "group_name": "My Group",
  "group_context": "Group description",
  "group_key": "secret-key"
}
```

### Members

| Method | Endpoint | Description | Client Method |
|--------|----------|-------------|---------------|
| POST | `/api/v1/groups/:id/members` | Join member | `join_member(gid, mid, name, type, ...)` |
| GET | `/api/v1/groups/:id/members` | List members | `list_members(gid)` |
| PUT | `/api/v1/groups/:id/members/:mid` | Update member | `update_member(gid, mid, **kwargs)` |
| DELETE | `/api/v1/groups/:id/members/:mid` | Leave member | `leave_member(gid, mid)` |

**Join Member Request Body:**
```json
{
  "member_id": "agent-001",
  "member_name": "Helper Agent",
  "member_type": "worker-agent",
  "member_description": "A helpful agent",
  "member_interface": "{\"adaptor\":\"topsailai_agent\",...}"
}
```

### Messages

| Method | Endpoint | Description | Client Method |
|--------|----------|-------------|---------------|
| POST | `/api/v1/groups/:id/messages` | Send message | `send_message(gid, text, sender_id, sender_type, ...)` |
| GET | `/api/v1/groups/:id/messages` | List messages | `list_messages(gid, ...)` |
| PUT | `/api/v1/groups/:id/messages/:mid` | Update message | `update_message(gid, mid, **kwargs)` |
| DELETE | `/api/v1/groups/:id/messages/:mid` | Delete message | `delete_message(gid, mid)` |

**Send Message Request Body:**
```json
{
  "message_text": "Hello @agent-001",
  "sender_id": "user-001",
  "sender_type": "user",
  "processed_msg_id": "msg-123"
}
```

### Trigger

| Method | Endpoint | Description | Client Method |
|--------|----------|-------------|---------------|
| POST | `/api/v1/groups/:id/messages/:mid/trigger` | Manual trigger | `trigger_message(gid, mid, agent_id)` |

**Trigger Request Body:**
```json
{
  "agent_id": "agent-001"
}
```

**Trigger Response:**
```json
{
  "message_id": "msg-456",
  "group_id": "grp-123",
  "trigger": {
    "type": "manual",
    "agent_id": "agent-001"
  },
  "status": "pending"
}
```

---

## Python Client Methods

### ACSClient

```python
from api_client import ACSClient

client = ACSClient()  # Uses ACS_SERVER_API_BASE env var
```

#### Group Methods

```python
client.create_group(group_name, group_context="", group_key="")
client.list_groups(offset=0, limit=1000, sort_key="create_at_ms", order_by="desc")
client.get_group(group_id)
client.update_group(group_id, group_name=..., group_context=...)
client.delete_group(group_id)
```

#### Member Methods

```python
client.join_member(
    group_id, member_id, member_name, member_type,
    member_description="", member_interface=None
)
client.list_members(group_id)
client.update_member(group_id, member_id, ...)
client.leave_member(group_id, member_id)
```

#### Message Methods

```python
client.send_message(
    group_id, message_text, sender_id, sender_type,
    message_attachments=None, processed_msg_id=None
)
client.list_messages(
    group_id, offset=0, limit=1000,
    processed_msg_id=None, create_at_ms=None, update_at_ms=None
)
client.get_message(group_id, message_id)
client.update_message(group_id, message_id, ...)
client.delete_message(group_id, message_id)
```

#### Trigger Methods

```python
client.trigger_message(group_id, message_id, agent_id=None)
```

#### Polling Helper

```python
response = client.wait_for_response(
    group_id, processed_msg_id, timeout=600, poll_interval=2
)
```

---

## Error Handling

All client methods raise `ACSAPIError` on failure:

```python
from api_client import ACSAPIError, ACSClient

client = ACSClient()
try:
    group = client.get_group("nonexistent")
except ACSAPIError as e:
    print(f"Error: {e}")
    print(f"Status: {e.status_code}")
    print(f"Trace ID: {e.trace_id}")
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_SERVER_API_BASE` | `http://localhost:7370` | ACS API base URL |
| `ACS_AGENT_ID` | - | Agent member ID (for call_agent) |
| `ACS_AGENT_NAME` | `ACS_AGENT_ID` | Agent display name |
| `ACS_AGENT_TYPE` | `worker-agent` | Agent type |
| `ACS_AGENT_TIMEOUT` | `600` | Timeout in seconds |
| `ACS_GROUP_ID` | - | Target group ID |
| `ACS_MESSAGE_ID` | - | Message ID to process |
