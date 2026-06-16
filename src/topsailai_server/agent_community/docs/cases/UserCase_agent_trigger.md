---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# User Case: Agent Trigger

## Scenario

Alice is in a group with a research agent. She wants to trigger the agent by mentioning it in a message, and the agent should respond with relevant information.

## Prerequisites

- ACS server is running
- NATS server is running with JetStream enabled
- PostgreSQL database is accessible
- Mock AI-agent server is running (or a real agent is available)
- Group exists with Alice (user) and research-agent-001 (worker-agent) as members

## Steps

### Step 1: Verify Group Setup

**GET /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/members**

Ensure the group has at least one user and one agent.

**Expected Response:**
```json
{
  "data": {
    "items": [
      {
        "member_id": "alice",
        "member_name": "Alice",
        "member_type": "user"
      },
      {
        "member_id": "research-agent-001",
        "member_name": "Research_Assistant",
        "member_type": "worker-agent",
        "member_interface": {
          "adaptor": "topsailai_agent",
          "environments": {
            "ACS_AGENT_API_BASE": "http://mock-agent:7373",
            "ACS_AGENT_API_KEY": "agent-secret"
          }
        }
      }
    ]
  }
}
```

---

### Step 2: Send Message with Mention

**POST /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/messages**

Alice sends a message mentioning the research agent.

**Request:**
```json
{
  "message_text": "@research-agent-001 Can you summarize the key findings from the transformer paper?",
  "sender_id": "alice",
  "sender_type": "user"
}
```

**Response:**
```json
{
  "data": {
    "message_id": "msg-003",
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "message_text": "@research-agent-001 Can you summarize the key findings from the transformer paper?",
    "sender_id": "alice",
    "sender_type": "user",
    "mentions": [
      {
        "member_id": "research-agent-001",
        "member_name": "Research_Assistant",
        "member_type": "worker-agent"
      }
    ],
    "create_at_ms": 1704067300000
  }
}
```

---

### Step 3: NATS Pending Message Flow

The ACS server automatically:

1. Extracts mentions from the message text (`@research-agent-001`)
2. Identifies the mentioned member as a worker-agent
3. Publishes a pending message to NATS JetStream:
   - Subject: `acs.group.pending-message.550e8400-e29b-41d4-a716-446655440000`
   - Content includes trigger info: `{"type": "mention", "agent_id": "research-agent-001"}`

---

### Step 4: AgentWorkPool Processing

One of the ACS service nodes (via NATS Queue Group) receives the pending message:

1. Acquires semaphore from AgentWorkPool
2. Checks if the agent is alive (health check)
3. Builds context messages (init context + unprocessed messages)
4. Calls the agent's chat endpoint with `ACS_AGENT_MODE=agent`
5. Receives the agent's response
6. Creates a new message in the group with:
   - `sender_id`: `research-agent-001`
   - `sender_type`: `worker-agent`
   - `processed_msg_id`: `msg-003`
7. Updates `group_member.last_read_message_id` for the agent
8. Releases the semaphore

---

### Step 5: View Agent Response

**GET /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/messages**

**Response:**
```json
{
  "data": {
    "items": [
      {
        "message_id": "msg-003",
        "message_text": "@research-agent-001 Can you summarize the key findings from the transformer paper?",
        "sender_id": "alice",
        "sender_type": "user",
        "create_at_ms": 1704067300000
      },
      {
        "message_id": "msg-004",
        "message_text": "Based on the transformer paper, the key findings are: 1) Self-attention mechanism allows parallel processing...",
        "sender_id": "research-agent-001",
        "sender_type": "worker-agent",
        "processed_msg_id": "msg-003",
        "create_at_ms": 1704067310000
      }
    ]
  }
}
```

---

### Step 6: Real-Time Subscription

Alice is subscribed to the group via NATS and sees the agent response in real-time:

```
[2024-01-01 00:01:40] alice (user): @research-agent-001 Can you summarize the key findings from the transformer paper?
[2024-01-01 00:01:50] Research_Assistant (worker-agent): Based on the transformer paper, the key findings are: 1) Self-attention mechanism allows parallel processing...
```

---

### Step 7: Trigger @all

**POST /api/v1/groups/550e8400-e29b-41d4-a716-446655440000/messages**

Alice sends a message with `@all` mention. If a manager-agent exists, it will be triggered.

**Request:**
```json
{
  "message_text": "@all Let's schedule a meeting to discuss the results.",
  "sender_id": "alice",
  "sender_type": "user"
}
```

**Expected Behavior:**
- `@all` has highest priority
- If manager-agent exists, it is triggered with `ACS_AGENT_MODE=agent`
- If no manager-agent but multiple worker-agents exist, all are triggered concurrently with `ACS_AGENT_MODE=chat`

---

### Step 8: Auto-Trigger (Single User)

If Alice is the only user in the group and sends a message without mentions:

**Request:**
```json
{
  "message_text": "What do you think about the new approach?",
  "sender_id": "alice",
  "sender_type": "user"
}
```

**Expected Behavior:**
- Since there is only one user in the group
- The manager-agent (if exists) is automatically triggered
- `ACS_AGENT_MODE=agent`

---

### Step 9: Auto-Trigger (Timeout)

If Alice sends a message and no one responds for 10 minutes (configurable via `ACS_AUTO_TRIGGER_TIMEOUT_MINUTES`):

**Expected Behavior:**
- The periodic auto-trigger task (running every `ACS_AUTO_TRIGGER_INTERVAL_SECONDS`) detects the timeout
- Acquires distributed lock for the group via NATS KV
- Triggers the manager-agent with `ACS_AGENT_MODE=agent`
- The manager-agent may ask follow-up questions or provide suggestions

---

## Trigger Rules Summary

### Mention Triggers (Priority: High to Low)

| Condition | Triggered Agent | Mode |
|-----------|----------------|------|
| `@all` in message | Manager-agent (if exists) | agent |
| Single agent mention | Mentioned agent | agent |
| Multiple agent mentions, no manager | All mentioned agents (concurrent) | chat |
| Multiple agent mentions, with manager | One random manager-agent | agent |

### Auto Triggers

| Condition | Triggered Agent | Mode |
|-----------|----------------|------|
| Only 1 user in group, no mentions | Manager-agent | agent |
| Last message from user, timeout exceeded | Manager-agent | agent |

### Anti-Trigger Rules (Never Trigger)

| Condition | Reason |
|-----------|--------|
| Sender is an agent | Prevent agent-to-agent loops |
| Message has `processed_msg_id` | Already processed |
| Sliding window shows 10+ consecutive agent messages | Prevent runaway chains |
| Max chain length exceeded (5) | Loop prevention |

---

## Error Scenarios

| Scenario | Expected Behavior |
|----------|------------------|
| Mentioned agent not found | Message stored, no trigger |
| Agent health check fails | System error message from manager-agent |
| Agent chat timeout | System error message, semaphore released |
| Agent returns error | System error message with error details |
| Group deleted during processing | Reject processing, message dropped |
| Member left during processing | Reject processing, message dropped |
