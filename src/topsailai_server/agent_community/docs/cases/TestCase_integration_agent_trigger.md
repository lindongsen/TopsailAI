---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Agent Triggering

## Overview

Verify all agent triggering rules: mentions, `@all`, single-user auto-trigger, timeout auto-trigger, `NO_TRIGGER_CASES`, concurrent multi-agent mentions, and manual trigger bypass.

---

## TC-INT-AGENT-001: Single Mention Triggers Worker-Agent

### Objective

Verify mentioning a single worker-agent triggers it with `ACS_AGENT_MODE=agent`.

### Setup

- Group with 1 user and 1 worker-agent.
- Mock agent server running.

### Steps

1. Create group and join user + worker-agent.
2. Send message: `"Hello @agent-001, can you help?"`.
3. Poll messages for agent response.

### Expected Output

- Message stored with `mentions` array.
- Agent response appears within timeout.
- Response `sender_type=worker-agent`.
- Response `processed_msg_id` = original message ID.

### Pass Criteria

- Mention extraction correct.
- Agent invoked in `agent` mode.
- Response linked to original message.

---

## TC-INT-AGENT-002: @all Triggers Manager-Agent with Priority

### Objective

Verify `@all` triggers only the manager-agent, even if worker-agents are also mentioned.

### Setup

- Group with 1 user, 1 manager-agent, 2 worker-agents.

### Steps

1. Send message: `"@all Please review this document"`.
2. Poll messages.

### Expected Output

- Only manager-agent responds.
- Worker-agents are not triggered.
- Response `sender_type=manager-agent`.

### Pass Criteria

- `@all` has highest priority and routes to manager-agent.

---

## TC-INT-AGENT-003: Multiple Worker-Agent Mentions Run Concurrently

### Objective

Verify mentioning multiple worker-agents without a manager-agent triggers them concurrently.

### Setup

- Group with 1 user and 3 worker-agents.
- Mock agents with small delays.

### Steps

1. Send message: `"@agent-1 @agent-2 @agent-3 help!"`.
2. Poll messages.

### Expected Output

- 3 agent response messages appear.
- Responses have similar timestamps (concurrent execution).
- Each response `processed_msg_id` = original message ID.

### Pass Criteria

- All mentioned agents respond.
- Execution is concurrent.

---

## TC-INT-AGENT-004: Multiple Mentions with Manager-Agent Route to One Manager

### Objective

Verify mentioning multiple agents including a manager-agent routes to a single randomly selected manager-agent.

### Setup

- Group with 1 user, 2 manager-agents, 2 worker-agents.

### Steps

1. Send message: `"@manager-1 @manager-2 @agent-1 help!"`.
2. Poll messages.

### Expected Output

- Exactly one manager-agent responds.
- No worker-agents respond.

### Pass Criteria

- Single manager-agent selected.

---

## TC-INT-AGENT-005: Single-User Group Auto-Triggers Manager-Agent

### Objective

Verify a message without mentions in a single-user group auto-triggers the manager-agent.

### Setup

- Group with exactly 1 user and 1 manager-agent.

### Steps

1. Send message: `"What do you think?"` (no mentions).
2. Poll messages.

### Expected Output

- Manager-agent responds.
- Response `sender_type=manager-agent`.

### Pass Criteria

- Auto-trigger works for single-user groups.

---

## TC-INT-AGENT-006: Idle Timeout Auto-Triggers Manager-Agent

### Objective

Verify a user message triggers the manager-agent after `ACS_AGENT_AUTO_TRIGGER_TIMEOUT`.

### Setup

- Group with 2 users and 1 manager-agent.
- Set `ACS_AGENT_AUTO_TRIGGER_TIMEOUT=30s` and `ACS_AUTO_TRIGGER_INTERVAL_SECONDS=10s`.

### Steps

1. User A sends message.
2. Wait for timeout period without any response.
3. Poll messages.

### Expected Output

- Manager-agent responds after timeout.
- Only one response (distributed lock prevents duplicates).

### Pass Criteria

- Timeout auto-trigger works.
- No duplicate triggers.

---

## TC-INT-AGENT-007: Agent Message Does Not Trigger (NO_TRIGGER_CASE #1)

### Objective

Verify messages from agents do not trigger further agents.

### Setup

- Group with 1 user and 1 worker-agent.

### Steps

1. User sends message triggering agent.
2. Agent responds.
3. Verify no new pending message or agent response is created from the agent message.

### Expected Output

- Exactly one agent response.
- No infinite loop.

### Pass Criteria

- Agent messages are not re-triggered.

---

## TC-INT-AGENT-008: Message with processed_msg_id Does Not Trigger (NO_TRIGGER_CASE #2)

### Objective

Verify messages with `processed_msg_id` set do not trigger agents automatically.

### Setup

- Group with 1 user and 1 worker-agent.

### Steps

1. Create a message with `processed_msg_id` referencing another message.
2. Verify no agent is triggered.

### Expected Output

- No agent response.

### Pass Criteria

- `processed_msg_id` prevents auto-trigger.

---

## TC-INT-AGENT-009: Long Agent Chain Does Not Trigger (NO_TRIGGER_CASE #3)

### Objective

Verify a message in a long sequence of agent messages is not triggered.

### Setup

- Group with 1 user and 1 worker-agent.
- Pre-populate >10 consecutive agent messages.

### Steps

1. User sends a message after the agent chain.
2. Verify no agent is triggered.

### Expected Output

- No agent response.

### Pass Criteria

- Long agent chain prevents trigger.

---

## TC-INT-AGENT-010: Manual Trigger Bypasses NO_TRIGGER_CASES

### Objective

Verify `POST /messages/{message_id}/trigger` bypasses `NO_TRIGGER_CASES`.

### Steps

1. Create an agent-sent message.
2. Send manual trigger request.

### Expected Output

Status: 202
- `status=pending`.
- Agent is triggered despite NO_TRIGGER_CASES.

### Pass Criteria

- Manual trigger bypass works.

---

## TC-INT-AGENT-011: Manual Trigger with Specific Agent ID

### Objective

Verify manual trigger with `agent_id` triggers only that agent.

### Steps

1. Create a message.
2. Send `POST /messages/{message_id}/trigger` with `agent_id`.

### Expected Output

Status: 202
- `trigger.agent_id` matches request.
- Only specified agent is invoked.

### Pass Criteria

- Specific agent trigger works.

---

## TC-INT-AGENT-012: Manual Trigger with Non-Agent Member Returns 400

### Objective

Verify manual trigger with a user member ID returns 400.

### Steps

1. Create a message.
2. Send manual trigger with `agent_id={user_member_id}`.

### Expected Output

Status: 400
- Error indicates member is not an agent.

### Pass Criteria

- Non-agent member rejected.

---

## TC-INT-AGENT-013: Manual Trigger with Non-Member Agent Returns 404

### Objective

Verify manual trigger with an agent not in the group returns 404.

### Steps

1. Create a message.
2. Send manual trigger with `agent_id=agent-not-in-group`.

### Expected Output

Status: 404

### Pass Criteria

- Non-member agent rejected.

---

## TC-INT-AGENT-014: Agent Health Check Blocks Unhealthy Agent

### Objective

Verify an unhealthy agent is not invoked.

### Setup

- Group with 1 user and 1 worker-agent pointing to a dead port.

### Steps

1. Send message mentioning the agent.
2. Verify no agent response and no `processing` status change.

### Expected Output

- No agent response.
- Member status remains `online`.

### Pass Criteria

- Health check prevents invocation.

---

## TC-INT-AGENT-015: Agent Failure Produces Manager-Agent Error Message

### Objective

Verify agent invocation failure creates an error message from the manager-agent.

### Setup

- Group with 1 user and 1 worker-agent configured to always error.

### Steps

1. Send message mentioning the failing agent.
2. Poll messages.

### Expected Output

- Error message appears.
- Error message `sender_type=manager-agent`.
- Error message `processed_msg_id` = original message ID.

### Pass Criteria

- Failure is handled gracefully.
- No infinite retry.

---

## TC-INT-AGENT-016: Per-Group Work-Pool Concurrency Limit

### Objective

Verify `ACS_AGENT_WORK_POOL_PER_GROUP` limits concurrent agent invocations per group.

### Setup

- `ACS_AGENT_WORK_POOL_PER_GROUP=2`.
- Group with 1 user and 3 worker-agents with slow responses.

### Steps

1. Send message mentioning all 3 agents.
2. Observe that only 2 agents are `processing` at a time.

### Expected Output

- Max 2 concurrent processing statuses in the group.
- All 3 eventually complete.

### Pass Criteria

- Per-group limit enforced.

---

## TC-INT-AGENT-017: Per-User Work-Pool Concurrency Limit

### Objective

Verify `ACS_AGENT_WORK_POOL_PER_USER` limits concurrent invocations per original sender.

### Setup

- `ACS_AGENT_WORK_POOL_PER_USER=1`.
- Two groups with the same user and slow agents.

### Steps

1. Send messages in both groups simultaneously.
2. Observe sequential processing.

### Expected Output

- Only 1 agent invocation per user at a time.

### Pass Criteria

- Per-user limit enforced.

---

## TC-INT-AGENT-018: Per-Node Work-Pool Concurrency Limit

### Objective

Verify `ACS_AGENT_WORK_POOL_PER_NODE` limits total concurrent invocations per service node.

### Setup

- `ACS_AGENT_WORK_POOL_PER_NODE=2`.
- Multiple groups with slow agents.

### Steps

1. Trigger agents across groups simultaneously.
2. Observe max 2 concurrent processing statuses.

### Expected Output

- Max 2 concurrent invocations on the node.

### Pass Criteria

- Per-node limit enforced.

---

## TC-INT-AGENT-019: Context Messages Include Group Info When No last_read_message_id

### Objective

Verify agent receives init context message when `last_read_message_id` is empty.

### Setup

- Group with context and members.
- Worker-agent with empty `last_read_message_id`.

### Steps

1. Send message mentioning the agent.
2. Inspect mock agent received environment/context.

### Expected Output

- `ACS_GROUP_CONTEXT` is present.
- Context messages include group info and member list.

### Pass Criteria

- Init context is included.

---

## TC-INT-AGENT-020: last_read_message_id Updated After Processing

### Objective

Verify agent's `last_read_message_id` is updated after processing.

### Steps

1. Trigger agent.
2. Wait for response.
3. GET member and check `last_read_message_id`.

### Expected Output

- `last_read_message_id` equals the processed pending message ID.

### Pass Criteria

- Read position updated.

---

## TC-INT-AGENT-021: Multiple Groups Trigger Agents in Parallel

### Objective

Verify agents in different groups can be triggered concurrently.

### Setup

- 2 groups, each with 1 user and 1 worker-agent.

### Steps

1. Send trigger messages in both groups.
2. Poll both groups.

### Expected Output

- Both agents respond.

### Pass Criteria

- Cross-group parallelism works.

---

## TC-INT-AGENT-022: Manager-Agent Receives ACS_LOGIN_SESSION_KEY

### Objective

Verify manager-agent invocation includes `ACS_LOGIN_SESSION_KEY` for the original sender.

### Setup

- Group with 1 user and 1 manager-agent.
- Mock agent logs environment variables.

### Steps

1. Send message triggering manager-agent.
2. Inspect mock agent environment.

### Expected Output

- `ACS_LOGIN_SESSION_KEY` is present and valid.

### Pass Criteria

- Session key injected for manager-agent.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_agent_trigger.py -v
```

## Notes

- Timeout auto-trigger tests may need adjusted environment variables.
- Work-pool limit tests require slow mock agents to observe concurrency.
- Some tests may need direct database inspection or NATS subscription to verify pending messages.
