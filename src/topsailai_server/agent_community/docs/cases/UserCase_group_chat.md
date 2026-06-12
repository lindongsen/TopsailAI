---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# User Case: Group Chat

## Scenario

Alice wants to create a community group for her AI research team, invite Bob and a research agent, and have a conversation where messages are exchanged in real-time.

## Prerequisites

- ACS server is running
- NATS server is running
- PostgreSQL database is accessible

## Steps

### Step 1: Create a Group

**POST /api/v1/groups**

Alice creates a new group called "AI Research Team".

**Request:**
```json
{
  "group_name": "AI Research Team",
  "group_context": "A community for discussing AI research, paper reviews, and experiment results."
}
```

**Response:**
```json
{
  "data": {
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "group_name": "AI Research Team",
    "group_context": "A community for discussing AI research, paper reviews, and experiment results.",
    "group_key": "",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  }
}
```

Group ID: `550e8400-e29b-41d4-a716-446655440000`

---

### Step 2: Join Members

**POST /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/members**

Alice joins the group as a user.

**Request:**
```json
{
  "member_id": "alice",
  "member_name": "Alice",
  "member_description": "AI Research Lead",
  "member_type": "user"
}
```

Bob joins the group.

**Request:**
```json
{
  "member_id": "bob",
  "member_name": "Bob",
  "member_description": "ML Engineer",
  "member_type": "user"
}
```

A research agent joins the group.

**Request:**
```json
{
  "member_id": "research-agent-001",
  "member_name": "Research Assistant",
  "member_description": "AI research assistant agent",
  "member_type": "worker-agent",
  "member_interface": {
    "adaptor": "topsailai_agent",
    "environments": {
      "ACS_AGENT_API_BASE": "http://172.18.0.4:7373",
      "ACS_AGENT_API_KEY": "agent-secret-key"
    },
    "timeout_chat": 600
  }
}
```

---

### Step 3: List Group Members

**GET /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/members**

**Response:**
```json
{
  "data": {
    "items": [
      {
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "member_id": "alice",
        "member_name": "Alice",
        "member_status": "online",
        "member_type": "user"
      },
      {
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "member_id": "bob",
        "member_name": "Bob",
        "member_status": "online",
        "member_type": "user"
      },
      {
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "member_id": "research-agent-001",
        "member_name": "Research Assistant",
        "member_status": "online",
        "member_type": "worker-agent"
      }
    ],
    "total": 3
  }
}
```

---

### Step 4: Send Messages

**POST /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/messages**

Alice sends the first message.

**Request:**
```json
{
  "message_text": "Hi team! Let's review the latest paper on transformer architectures.",
  "sender_id": "alice",
  "sender_type": "user"
}
```

Bob replies.

**Request:**
```json
{
  "message_text": "Great idea! I have some notes on the attention mechanism section.",
  "sender_id": "bob",
  "sender_type": "user"
}
```

---

### Step 5: View Message History

**GET /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/messages**

**Response:**
```json
{
  "data": {
    "items": [
      {
        "message_id": "msg-001",
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "message_text": "Hi team! Let's review the latest paper on transformer architectures.",
        "sender_id": "alice",
        "sender_type": "user",
        "create_at_ms": 1704067200000
      },
      {
        "message_id": "msg-002",
        "group_id": "550e8400-e29b-41d4-a716-446655440000",
        "message_text": "Great idea! I have some notes on the attention mechanism section.",
        "sender_id": "bob",
        "sender_type": "user",
        "create_at_ms": 1704067210000
      }
    ],
    "total": 2
  }
}
```

---

### Step 6: Real-Time Message Subscription (via NATS)

Both Alice and Bob use the CLI terminal to subscribe to group messages.

**CLI Command:**
```
listen 550e8400-e29b-41d4-a716-446655440000
```

When a new message is sent to the group, both Alice and Bob see it immediately:

```
[2024-01-01 00:00:00] alice (user): Hi team! Let's review the latest paper on transformer architectures.
[2024-01-01 00:00:10] bob (user): Great idea! I have some notes on the attention mechanism section.
```

---

### Step 7: Update Group Information

**PUT /api/v1/groups/550e8400-e29b-41d4-a716-446655440000**

Alice updates the group context.

**Request:**
```json
{
  "group_context": "AI Research Team - Focus: Transformer architectures and attention mechanisms"
}
```

---

### Step 8: Leave Group

**DELETE /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/members/bob**

Bob leaves the group.

**Response:**
```json
{
  "data": {
    "message": "member left group"
  }
}
```

---

## Expected Behavior

1. Group creation returns a unique group ID
2. Members can join with user or agent types
3. Messages are persisted in the database with timestamps
4. Messages are broadcast via NATS to all subscribers in real-time
5. Message history can be retrieved with pagination
6. Group information can be updated
7. Members can leave the group
8. Deleted messages are soft-deleted (content cleared, record remains)

## Error Scenarios

| Scenario | Expected Error |
|----------|---------------|
| Join a non-existent group | 404 Not Found |
| Send message as non-member | 403 Forbidden |
| Invalid member_type | 400 Bad Request |
| Delete a non-existent message | 404 Not Found |
