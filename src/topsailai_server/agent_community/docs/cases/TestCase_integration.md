---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration Testing

## Overview

This document describes end-to-end integration test scenarios for the AI-Agent Community Server (ACS). These tests verify the interaction between all components: HTTP API, database, NATS message bus, agent triggering, and agent execution.

---

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| ACS Server | Built and running (`make run` or `go run cmd/server/main.go`) |
| PostgreSQL | Running with `agent_community` database |
| NATS Server | Running with JetStream enabled |
| Mock Agent Server | Running on configured port |
| Python | 3.9+ with dependencies from `tests/integration/requirements.txt` |

### Mock Agent Server Setup

Start the mock agent server before running integration tests:

```bash
cd tests/integration
python mock_agent_server.py --port 7373 --delay 0.5 --error-rate 0.0
```

The mock agent server provides:
- `GET /health` - Returns healthy status
- `GET /status` - Returns `idle` or `processing`
- `POST /chat` - Returns contextual responses based on input

Authentication: Bearer Token (configured via `ACS_AGENT_API_KEY`)

---

## TC-INT-001: End-to-End Group Lifecycle

### Objective

Verify the complete lifecycle of a group: create, join members, send messages, receive agent responses, and cleanup.

### Steps

1. **Create Group**
   - POST /api/v1/groups
   - Input: `{"group_name": "Integration Test Group", "group_context": "E2E testing"}`
   - Verify: 201 status, valid group_id returned

2. **Join User Member**
   - POST /api/v1/groups/{group_id}/members
   - Input: `{"member_id": "test-user", "member_name": "Test_User", "member_type": "user"}`
   - Verify: 201 status, member is online

3. **Join Agent Member**
   - POST /api/v1/groups/{group_id}/members
   - Input: Agent member with mock server interface
   - Verify: 201 status, interface is stored

4. **Send Message**
   - POST /api/v1/groups/{group_id}/messages
   - Input: `{"message_text": "Hello @agent-001", "sender_id": "test-user", "sender_type": "user"}`
   - Verify: 201 status, mentions extracted

5. **Wait for Agent Response**
   - Poll GET /api/v1/groups/{group_id}/messages
   - Verify: Agent response message appears within 30 seconds
   - Verify: Response has `processed_msg_id` pointing to original message

6. **Verify NATS Events**
   - Subscribe to `acs.group.message.{group_id}`
   - Verify: Events received for message create, agent response

7. **Cleanup**
   - DELETE /api/v1/groups/{group_id}
   - Verify: 200 status, group removed

### Pass Criteria

- All API calls return expected status codes
- Agent response is generated and stored
- NATS events are published for all mutations
- Database state is consistent throughout

---

## TC-INT-002: Agent Trigger via Mention

### Objective

Verify that mentioning an agent in a message correctly triggers the agent workflow.

### Setup

- Group with 1 user and 1 worker-agent
- Mock agent server running

### Steps

1. Create group and join user + agent
2. Send message: `"@agent-001 What is the weather?"`
3. Verify:
   - Message stored with mentions array
   - NATS pending message published to `acs.group.pending-message.{group_id}`
   - AgentWorkPool processes the message
   - Mock agent server receives chat request with:
     - `ACS_AGENT_MODE=agent`
     - Context messages including init context and conversation history
   - Agent response message created with:
     - `sender_id=agent-001`
     - `sender_type=worker-agent`
     - `processed_msg_id=original-message-id`

### Pass Criteria

- Mention extraction is correct
- Pending message is published to NATS
- Agent is called with correct mode and context
- Response is stored and linked to original message

---

## TC-INT-003: Agent Trigger via @all

### Objective

Verify that `@all` mention triggers the manager-agent with highest priority.

### Setup

- Group with 1 user, 1 manager-agent, 2 worker-agents
- Mock agent server running

### Steps

1. Create group with manager-agent and worker-agents
2. Send message: `"@all Please review the document"`
3. Verify:
   - Message stored with mentions (all members)
   - Manager-agent is triggered (not worker-agents)
   - `ACS_AGENT_MODE=agent`
   - Only one agent response (manager-agent)

### Pass Criteria

- `@all` triggers manager-agent only
- Worker-agents are not triggered
- Manager-agent receives agent mode

---

## TC-INT-004: Auto-Trigger Single User

### Objective

Verify auto-trigger when there is only one user in the group.

### Setup

- Group with 1 user and 1 manager-agent
- No other users

### Steps

1. Create group with 1 user and 1 manager-agent
2. Send message without mentions: `"What do you think?"`
3. Verify:
   - Message stored
   - Manager-agent is automatically triggered
   - Agent response appears

### Pass Criteria

- Single user message triggers manager-agent
- No mention required for auto-trigger

---

## TC-INT-005: Auto-Trigger Timeout

### Objective

Verify auto-trigger after timeout period with no response.

### Setup

- Group with 2 users and 1 manager-agent
- `ACS_AUTO_TRIGGER_TIMEOUT_MINUTES=1` (for testing)
- `ACS_AUTO_TRIGGER_INTERVAL_SECONDS=10` (for testing)

### Steps

1. Create group with 2 users and manager-agent
2. User A sends message: `"Any thoughts on this?"`
3. Wait 1 minute without any response
4. Verify:
   - Periodic task detects timeout
   - Distributed lock acquired via NATS KV
   - Manager-agent is triggered
   - Agent response appears

### Pass Criteria

- Timeout is detected by periodic task
- Distributed lock prevents duplicate triggers
- Manager-agent responds after timeout

---

## TC-INT-006: Anti-Trigger Rules

### Objective

Verify that messages from agents do not trigger further agents.

### Setup

- Group with 1 user and 1 worker-agent

### Steps

1. Create group and join members
2. User sends message triggering agent
3. Agent responds
4. Verify:
   - Agent response does NOT trigger another pending message
   - No infinite loop occurs
   - Max chain length is respected

### Pass Criteria

- Agent messages do not trigger other agents
- Loop prevention works correctly

---

## TC-INT-007: Concurrent Agent Processing

### Objective
Verify that multiple agents can be triggered concurrently within semaphore limits.

### Setup
- `ACS_AGENT_WORK_POOL_PER_NODE=5`
- `ACS_AGENT_WORK_POOL_PER_USER=5`
- `ACS_AGENT_WORK_POOL_PER_GROUP=3`

### Steps

1. Create group with 1 user and 3 worker-agents
2. Send message mentioning all 3 agents: `"@agent-1 @agent-2 @agent-3 Help!"`
3. Verify:
   - All 3 agents are triggered concurrently
   - Semaphore limits are respected
   - All 3 responses appear
   - No deadlock or resource exhaustion

### Pass Criteria

- Multiple agents process concurrently
- Semaphore limits prevent overload
- All responses are received

---

## TC-INT-008: NATS Real-Time Message Delivery

### Objective

Verify real-time message delivery via NATS pub/sub.

### Setup

- ACS server running
- NATS server running
- Python test client with nats-py

### Steps

1. Create group
2. Subscribe to `acs.group.message.{group_id}` via NATS
3. Send message via API
4. Verify:
   - NATS message received within 1 second
   - Message format matches API response
   - Event type is `message`, action is `create`

5. Update message via API
6. Verify:
   - NATS message received for update
   - Event action is `modify`

7. Delete message via API
8. Verify:
   - NATS message received for delete
   - Event action is `delete`

### Pass Criteria

- All mutations publish NATS events
- Events are received in real-time
- Event format is correct

---

## TC-INT-009: Distributed Lock

### Objective

Verify distributed lock functionality using NATS KV.

### Setup

- 2 ACS server instances running
- NATS KV bucket configured

### Steps

1. Both instances attempt to acquire lock for same resource
2. Verify:
   - Only one instance acquires the lock
   - Second instance fails to acquire
3. First instance renews lock periodically
4. First instance releases lock
5. Verify:
   - Second instance can now acquire the lock

### Pass Criteria

- Lock is exclusive
- Renewal works correctly
- Lock is released properly

---

## TC-INT-010: Graceful Shutdown

### Objective

Verify graceful shutdown sequence.

### Setup

- ACS server running with active connections

### Steps

1. Start ACS server
2. Create group, join members, send messages
3. Send SIGTERM to server process
4. Verify:
   - HTTP server stops accepting new requests
   - Active requests complete
   - NATS consumer unsubscribes
   - Auto-trigger task stops
   - NATS connection closes
   - Database connection closes
   - Process exits cleanly

### Pass Criteria

- No panic or error during shutdown
- Active requests complete
- Resources are released

---

## TC-INT-011: CLI Terminal

### Objective

Verify CLI terminal functionality.

### Setup

- ACS server running
- CLI built (`make build-cli`)

### Steps

1. Start CLI: `./bin/acs-cli`
2. Execute commands:
   - `groups` - List groups
   - `join {group_id} test-user "Test_User"` - Join group
   - `send {group_id} "Hello from CLI"` - Send message
   - `listen {group_id}` - Subscribe to messages
   - `members {group_id}` - List members
   - `history {group_id}` - Show history
   - `quit` - Exit

3. Verify:
   - Commands execute without errors
   - Messages are displayed in formatted output
   - Real-time messages appear during listen

### Pass Criteria

- All CLI commands work
- Output is formatted correctly
- Real-time subscription works

---

## TC-INT-012: Error Recovery

### Objective

Verify system behavior when agent fails.

### Setup

- Group with 1 user and 1 agent
- Mock agent server configured with error

### Steps

1. Create group and join members
2. Configure mock agent to return error
3. Send message triggering agent
4. Verify:
   - Agent call fails
   - System error message is created
   - Error message has `sender_type=manager-agent`
   - No infinite retry loop

### Pass Criteria

- Agent failure is handled gracefully
- Error message is generated
- System does not enter infinite loop

---

## TC-INT-013: Message Pagination and Filtering

### Objective

Verify message pagination and time range filtering.

### Setup

- Group with multiple messages

### Steps

1. Create group and join user
2. Send 25 messages
3. Test pagination:
   - GET /messages?offset=0&limit=10 - Returns messages 1-10
   - GET /messages?offset=10&limit=10 - Returns messages 11-20
   - GET /messages?offset=20&limit=10 - Returns messages 21-25
4. Test sorting:
   - GET /messages?order_by=asc - Oldest first
   - GET /messages?order_by=desc - Newest first
5. Test time filtering:
   - GET /messages?create_at_ms={start}-{end} - Only messages in range

### Pass Criteria

- Pagination returns correct slices
- Sorting works in both directions
- Time filtering is accurate

---

## Test Execution

### Run All Integration Tests

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make test-integration
```

### Run Specific Test

```bash
cd tests/integration
pytest test_api.py::TestGroupAPI -v
pytest test_nats.py::TestNATSRealtime -v
```

### Run with Coverage

```bash
cd tests/integration
pytest --cov=. --cov-report=html -v
```

---

## Verification Checklist

| # | Check | Status |
|---|-------|--------|
| 1 | All API endpoints return correct status codes | |
| 2 | Database state is consistent after operations | |
| 3 | NATS events are published for all mutations | |
| 4 | Agent triggers work for mentions and auto-triggers | |
| 5 | Agent responses are stored with correct metadata | |
| 6 | Distributed locks prevent race conditions | |
| 7 | Semaphore limits are respected | |
| 8 | Graceful shutdown releases all resources | |
| 9 | CLI terminal functions correctly | |
| 10 | Error scenarios are handled gracefully | |
| 11 | Pagination and filtering work correctly | |
| 12 | Real-time message delivery via NATS works | |
