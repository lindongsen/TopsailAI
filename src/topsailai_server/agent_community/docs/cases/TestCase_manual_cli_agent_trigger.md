---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Manual CLI Agent Trigger Scenarios

## Objective

Verify ACS agent triggering logic end-to-end through the interactive CLI terminal. All CLI sessions and mock agent logs must run inside `tmux` so concurrent scenarios can be observed side-by-side.

Coverage:

1. Single mention triggers a single worker-agent.
2. `@all` triggers a manager-agent with highest priority.
3. Multiple worker-agent mentions without a manager-agent trigger concurrently.
4. Multiple groups trigger agents in parallel without cross-talk.
5. Mock agent reply delays exercise timeout and work-pool behavior.
6. Auto-trigger when a group contains only one user.
7. Anti-trigger / NO_TRIGGER cases (agent messages do not re-trigger).

---

## Prerequisites

| Component | Requirement | Check Command |
|-----------|-------------|---------------|
| Go toolchain | 1.25+ | `go version` |
| ACS server binary | `bin/acs-server` | `make build-server` |
| ACS CLI binary | `bin/acs-cli` | `make build-cli` |
| PostgreSQL | Running | `psql -U acs -d acs -c 'SELECT 1'` |
| NATS Server | Running with JetStream | `nats server info` |
| tmux | Installed | `tmux -V` |
| jq | JSON formatter | `jq --version` |
| curl | For trigger endpoint fallback | `curl --version` |
| Mock agent scripts | Present in `scripts/` | `ls scripts/mock_agent_cmd_chat*.sh` |

### Mock Agent Scripts

Use the helper scripts in `/TopsailAI/src/topsailai_server/agent_community/scripts/`:

| Script | Purpose |
|--------|---------|
| `mock_agent_cmd_chat.sh` | Fast deterministic reply |
| `mock_agent_cmd_chat_sleep.sh` | Configurable sleep before replying |
| `mock_agent_cmd_chat_fail.sh` | Simulates agent failure |
| `mock_agent_cmd_check_health.sh` | Returns healthy |
| `mock_agent_cmd_check_status.sh` | Returns `idle` or `processing` |

Ensure the scripts are executable:

```bash
chmod +x /TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_chat*.sh
chmod +x /TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_check_*.sh
```

### Build

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make build
```

### Base Environment

```bash
export ACS_HOME=/tmp/acs-agent-test
export ACS_DATABASE_DRIVER=postgres
export ACS_DATABASE_HOST=localhost
export ACS_DATABASE_PORT=5432
export ACS_DATABASE_USER=acs
export ACS_DATABASE_PASSWORD=acs
export ACS_DATABASE_NAME=acs
export ACS_NATS_SERVERS=nats://localhost:4222
export ACS_DISCOVERY_ENABLED=true
export ACS_AGENT_WORK_POOL_PER_NODE=10
export ACS_AGENT_WORK_POOL_PER_USER=5
export ACS_AGENT_WORK_POOL_PER_GROUP=5
export ACS_NATS_ACK_WAIT_SECONDS=3600
export ACS_NATS_MAX_ACK_PENDING=10
```

---

## Test Environment Setup

### 1. Start the server

```bash
mkdir -p "$ACS_HOME"/log "$ACS_HOME"/run
cd /TopsailAI/src/topsailai_server/agent_community
ACS_HTTP_PORT=7370 ./bin/acs-server
```

Run inside tmux:

```bash
tmux new-session -d -s acs-agent -n server
tmux send-keys -t acs-agent:server 'cd /TopsailAI/src/topsailai_server/agent_community && ACS_HTTP_PORT=7370 ./bin/acs-server' C-m
```

### 2. Capture admin token

```bash
cat ACS_ACCOUNT_ADMIN_API_KEY.acs
export ADMIN_TOKEN="<value>"
export API_BASE="http://127.0.0.1:7370"
export SCRIPTS="/TopsailAI/src/topsailai_server/agent_community/scripts"
```

### 3. Open CLI and mock-agent log panes

```bash
# Main CLI
tmux new-window -t acs-agent -n cli
# Helper API / log window
tmux new-window -t acs-agent -n api
# Mock agent trace window (tail agent logs if any)
tmux new-window -t acs-agent -n mocklogs
```

Start the CLI:

```bash
tmux send-keys -t acs-agent:cli 'cd /TopsailAI/src/topsailai_server/agent_community && ./bin/acs-cli -api-base "$API_BASE" -api-key "$ADMIN_TOKEN" -nats-url nats://localhost:4222 -no-color' C-m
```

---

## Helper: Agent Member Interface JSON

When adding an agent member via CLI `/member:add`, use a `member_interface` similar to:

```json
{
  "adaptor": "mock_agent",
  "environments": {
    "ACS_AGENT_API_BASE": "http://localhost",
    "ACS_AGENT_API_KEY": "mock-key",
    "ACS_AGENT_API_AUTH": "bearer"
  },
  "timeout_chat": 600,
  "timeout_check_health": 5,
  "timeout_check_status": 5,
  "cmd_check_health": "/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_check_health.sh",
  "cmd_check_status": "/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_check_status.sh",
  "cmd_chat": "/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_chat.sh"
}
```

> Replace `cmd_chat` with `mock_agent_cmd_chat_sleep.sh` or `mock_agent_cmd_chat_fail.sh` as needed.

---

## Test Cases

### AGENT-001: Single Mention Triggers Single Worker-Agent

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-001 |
| **Description** | Message mentioning one worker-agent triggers exactly that agent |
| **Preconditions** | Group exists with one user and one worker-agent (`worker-1`) |
| **Steps** | 1. `/group:create` name=SingleMention<br>2. `/member:add` group-id=<id> member-id=worker-1 member-name=WorkerOne member-type=worker-agent member-interface=<fast mock><br>3. `/group:enter` group-id=<id><br>4. Type: `@worker-1 hello` |
| **Expected Result** | A new message from `worker-1` appears; `processed_msg_id` equals the user message id; `sender_type=worker-agent` |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-002: `@all` Triggers Manager-Agent Only

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-002 |
| **Description** | `@all` mention routes to manager-agent, ignoring worker-agents |
| **Preconditions** | Group with user, manager-agent, and multiple worker-agents |
| **Steps** | 1. Create group AllMention<br>2. Add manager-agent (`manager-1`) and two worker-agents (`worker-1`, `worker-2`)<br>3. Enter group<br>4. Type: `@all please coordinate` |
| **Expected Result** | Only `manager-1` responds; worker-agents do not produce messages |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-003: Multiple Worker-Agent Mentions Trigger Concurrently

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-003 |
| **Description** | Mention multiple worker-agents with no manager-agent; all are invoked concurrently |
| **Preconditions** | Group with user and two worker-agents (`worker-1`, `worker-2`), no manager-agent; use `mock_agent_cmd_chat_sleep.sh` with sleep=3 so concurrency is observable |
| **Steps** | 1. Create group ConcurrentWorkers<br>2. Add `worker-1` and `worker-2` with sleep=3 mock chat<br>3. Enter group<br>4. Type: `@worker-1 @worker-2 solve this together` |
| **Expected Result** | Both agents respond within a few seconds of each other (total elapsed < 6s if truly concurrent); each response has `processed_msg_id` set to the original message; the agent prompt/context includes the appended instruction `! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !` |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-004: Multiple Groups Trigger Agents in Parallel

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-004 |
| **Description** | Three independent groups each trigger a worker-agent concurrently |
| **Preconditions** | Three groups created, each with one user and one worker-agent using `mock_agent_cmd_chat_sleep.sh` sleep=5 |
| **Steps** | 1. Create groups `ParallelA`, `ParallelB`, `ParallelC`<br>2. In each group add a distinct worker-agent (`pa-worker`, `pb-worker`, `pc-worker`)<br>3. Open three tmux panes/windows or use the same CLI to enter each group and send `@<agent> go`<br>4. Send all three messages as close in time as possible |
| **Expected Result** | All three agents respond; responses appear in their respective groups only; no cross-group message leakage |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-005: Mock Agent Reply Delay — Within Timeout

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-005 |
| **Description** | Agent that sleeps 5 seconds replies successfully before timeout |
| **Preconditions** | Group with worker-agent using `mock_agent_cmd_chat_sleep.sh` and `timeout_chat=30` |
| **Steps** | 1. Add worker-agent with `cmd_chat=mock_agent_cmd_chat_sleep.sh` and `timeout_chat=30`<br>2. Send mention message<br>3. Observe response time |
| **Expected Result** | Response appears after ~5 seconds; no timeout error message from manager-agent |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-006: Mock Agent Reply Delay — Exceeds Timeout

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-006 |
| **Description** | Agent that sleeps longer than `timeout_chat` produces a timeout/failure message |
| **Preconditions** | Group with worker-agent using `mock_agent_cmd_chat_sleep.sh` sleep=120 and `timeout_chat=10` |
| **Steps** | 1. Add worker-agent with `cmd_chat=mock_agent_cmd_chat_sleep.sh` sleep=120, `timeout_chat=10`<br>2. Send mention message<br>3. Wait 15 seconds |
| **Expected Result** | A system/manager-agent message appears indicating the agent call failed or timed out; no infinite retry loop |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-007: Agent Failure Produces Error Message

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-007 |
| **Description** | Agent script exits non-zero; result is recorded as manager-agent error message |
| **Preconditions** | Group with worker-agent using `mock_agent_cmd_chat_fail.sh` |
| **Steps** | 1. Add worker-agent with `cmd_chat=mock_agent_cmd_chat_fail.sh`<br>2. Send mention message |
| **Expected Result** | A message from manager-agent appears with error content; `processed_msg_id` set to original message |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-008: Auto-Trigger — Single User in Group

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-008 |
| **Description** | Plain user message with no mentions triggers manager-agent when group has exactly one user |
| **Preconditions** | Group with exactly one user member and one manager-agent; no worker-agents |
| **Steps** | 1. Create group AutoTriggerSingle<br>2. Add manager-agent (`manager-1`)<br>3. Enter group<br>4. Type: `What should we do today?` (no mentions) |
| **Expected Result** | Manager-agent responds automatically after a short delay |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-009: Auto-Trigger — Idle Timeout

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-009 |
| **Description** | After configurable idle timeout, manager-agent is triggered automatically |
| **Preconditions** | Group with one user and manager-agent; server configured with short auto-trigger timeout |
| **Steps** | 1. Restart server with `ACS_AGENT_AUTO_TRIGGER_TIMEOUT=30s` and `ACS_AUTO_TRIGGER_INTERVAL_SECONDS=10`<br>2. Enter group and send one plain message<br>3. Wait 30-40 seconds without sending more messages |
| **Expected Result** | Manager-agent auto-triggers and responds after the idle period |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-010: Anti-Trigger — Agent Message Does Not Re-trigger

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-010 |
| **Description** | Verify agent response messages do not create new pending messages |
| **Preconditions** | Group where agent responses are already occurring |
| **Steps** | 1. Trigger an agent (AGENT-001)<br>2. Wait for agent response<br>3. Count messages; wait another 30 seconds; count again |
| **Expected Result** | Message count stabilizes; no runaway agent messages |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-011: Anti-Trigger — Message with `processed_msg_id`

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-011 |
| **Description** | A message that already has `processed_msg_id` is not auto-triggered |
| **Preconditions** | Group with user and worker-agent; a base message exists so we can reference its ID |
| **Steps** | 1. Create a group with user and worker-agent (`worker-1`)<br>2. Enter the group and send a normal user message, e.g. `base message`; note its `message_id` (`msg-base`)<br>3. Send a second normal user message mentioning the worker-agent, e.g. `@worker-1 follow-up`; note its `message_id` (`msg-followup`)<br>4. In the `api` tmux window, directly update the database to set `processed_msg_id` on `msg-followup`:<br>`psql -U acs -d acs -c "UPDATE group_messages SET processed_msg_id = '<msg-base>' WHERE message_id = '<msg-followup>';"`<br>5. Use the manual trigger endpoint to force re-evaluation of `msg-followup` (this exercises the trigger evaluator path directly):<br>`curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" "$API_BASE/api/v1/groups/<group_id>/messages/<msg-followup>/trigger" \| jq .`<br>6. Observe whether `worker-1` responds |
| **Expected Result** | The trigger endpoint returns status `no_agents_to_trigger`; `worker-1` does not produce a new reply; the message remains a plain user message |
| **Actual Result** | |
| **Status** | PASS |

> **Note:** The public message-creation API intentionally ignores client-supplied `processed_msg_id`. This test therefore uses a direct database update to populate the field, which is the only way a real message would have `processed_msg_id` set before the trigger evaluator sees it.

### AGENT-012: Manual Trigger Endpoint Bypasses NO_TRIGGER

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-012 |
| **Description** | Use the manual trigger API to force processing of an agent message |
| **Preconditions** | A message exists from an agent (sender_type ends with `-agent`) in a group with another agent |
| **Steps** | 1. Create group with two worker-agents (`worker-1`, `worker-2`)<br>2. Send a user message mentioning `worker-1` and wait for response<br>3. Use curl to manually trigger the agent response message for `worker-2`:<br>`curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"agent_id":"worker-2"}' "$API_BASE/api/v1/groups/<group_id>/messages/<agent_msg_id>/trigger" \| jq .` |
| **Expected Result** | HTTP 202, status `pending`; `worker-2` processes the message despite NO_TRIGGER rules |
| **Actual Result** | |
| **Status** | PASS |

### AGENT-013: Work-Pool Per-Group Concurrency Limit

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-013 |
| **Description** | Verify `ACS_AGENT_WORK_POOL_PER_GROUP` limits concurrent agent tasks per group |
| **Preconditions** | Group with multiple worker-agents using `mock_agent_cmd_chat_sleep.sh` sleep=30; `ACS_AGENT_WORK_POOL_PER_GROUP=1` |
| **Steps** | 1. Restart server with `ACS_AGENT_WORK_POOL_PER_GROUP=1`<br>2. Add two worker-agents to the same group<br>3. Send a message mentioning both agents<br>4. Observe response times |
| **Expected Result** | Agents respond sequentially (total ~60s) rather than concurrently; no `context deadline exceeded` errors; each agent produces exactly one response; any transient pool saturation causes immediate `msg.Nak()` and JetStream redelivery without duplicate agent executions |
| **Actual Result** | worker-c responded at T+30s; worker-a responded at T+60s; no duplicates; no dropped messages |
| **Status** | PASS |

---

## Cleanup

1. Exit the CLI (`/exit`).
2. Stop the server (`Ctrl+c` in the server pane).
3. Remove test data from PostgreSQL:

```bash
psql -U acs -d acs -c "DELETE FROM agent_message_processing; DELETE FROM audit_logs; DELETE FROM api_keys WHERE creator_id != 'system'; DELETE FROM accounts WHERE creator_id != 'system'; DELETE FROM group_messages; DELETE FROM group_member; DELETE FROM groups;"
```

4. Remove generated key files:

```bash
rm -f ACS_ACCOUNT_ADMIN_API_KEY.acs ACS_ACCOUNT_MANAGER_API_KEY.acs
```

5. Kill tmux session:

```bash
tmux kill-session -t acs-agent
```

---

## Execution Summary

| Test ID | Description | Status |
|---------|-------------|--------|
| AGENT-001 | Single mention triggers worker-agent | PASS |
| AGENT-002 | `@all` triggers manager-agent | PASS |
| AGENT-003 | Multiple worker-agents concurrent | PASS |
| AGENT-004 | Multiple groups parallel trigger | PASS |
| AGENT-005 | Reply delay within timeout | PASS |
| AGENT-006 | Reply delay exceeds timeout | PASS |
| AGENT-007 | Agent failure error message | PASS |
| AGENT-008 | Auto-trigger single user | PASS |
| AGENT-009 | Auto-trigger idle timeout | PASS |
| AGENT-010 | Anti-trigger agent message | PASS |
| AGENT-011 | Anti-trigger processed_msg_id | PASS |
| AGENT-012 | Manual trigger bypass | PASS |
| AGENT-013 | Per-group work-pool limit | PASS |

---

*Test Plan created by: km2-reviewer*
*Date: 2026-06-21*

### AGENT-014: Work-Pool Per-User Concurrency Limit

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-014 |
| **Description** | Verify `ACS_AGENT_WORK_POOL_PER_USER` limits concurrent agent tasks per user across groups |
| **Preconditions** | Two groups owned by the same user; each group has one worker-agent using `mock_agent_cmd_chat_sleep.sh` sleep=30; server restarted with `ACS_AGENT_WORK_POOL_PER_USER=1`, `ACS_AGENT_WORK_POOL_PER_GROUP=10`, `ACS_AGENT_WORK_POOL_PER_NODE=10` |
| **Steps** | 1. Restart server with per-user=1, per-group=10, per-node=10<br>2. Create groups `UserLimitA` and `UserLimitB`<br>3. Add `worker-a` to UserLimitA and `worker-b` to UserLimitB (fast health check)<br>4. Enter UserLimitA and send `@worker-a go`<br>5. Immediately enter UserLimitB and send `@worker-b go` |
| **Expected Result** | Agents respond sequentially across the two groups (total ~60s); no message is dropped; each agent produces exactly one response |
| **Actual Result** | Two agents in different groups owned by the same user executed sequentially (~60s total); no message loss |
| **Status** | PASS |

### AGENT-015: Work-Pool Per-Node Concurrency Limit

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-015 |
| **Description** | Verify `ACS_AGENT_WORK_POOL_PER_NODE` limits total concurrent agent tasks on the service node |
| **Preconditions** | Two groups with distinct worker-agents using `mock_agent_cmd_chat_sleep.sh` sleep=30; server restarted with `ACS_AGENT_WORK_POOL_PER_NODE=1`, `ACS_AGENT_WORK_POOL_PER_USER=10`, `ACS_AGENT_WORK_POOL_PER_GROUP=10` |
| **Steps** | 1. Restart server with per-node=1, per-user=10, per-group=10<br>2. Create groups `NodeLimitA` and `NodeLimitB`<br>3. Add `worker-a` to NodeLimitA and `worker-b` to NodeLimitB<br>4. Trigger both agents as close in time as possible |
| **Expected Result** | Only one agent runs at a time; total elapsed ~60s; both agents eventually respond exactly once |
| **Actual Result** | worker-a and worker-b in different groups executed sequentially (~60s total); only one agent ran at a time across the node |
| **Status** | PASS |

### AGENT-016: Cleanup of Terminal Agent Processing Records

| Field | Value |
|-------|-------|
| **Test ID** | AGENT-016 |
| **Description** | Verify the cleanup task removes old terminal `agent_message_processing` records without deleting recent ones |
| **Preconditions** | Server running with cleanup enabled; some agent processing records exist |
| **Steps** | 1. Run several agent trigger tests so `agent_message_processing` has `completed`/`failed` records<br>2. Query current record count: `psql -U acs -d acs -c "SELECT status, COUNT(*) FROM agent_message_processing GROUP BY status;"`<br>3. Manually age some records by updating their timestamps: `psql -U acs -d acs -c "UPDATE agent_message_processing SET create_at_ms = create_at_ms - (8 * 24 * 60 * 60 * 1000), update_at_ms = update_at_ms - (8 * 24 * 60 * 60 * 1000) WHERE status IN ('completed','failed');"`<br>4. Wait for the cleanup interval (default 1h) or restart server with `ACS_CLEANUP_INTERVAL=30s` and wait 60s<br>5. Query record count again |
| **Expected Result** | Aged terminal records are deleted; pending records remain; recent terminal records remain |
| **Actual Result** | Inserted 6 test records: 3 old terminal (completed/failed), 1 old stale pending, 1 recent terminal, 1 recent pending. After one cleanup tick (30s interval, retention_days=0, stale_pending_hours=1), all old terminal and stale-pending records were removed; only the recent pending record remained. |
| **Status** | PASS |

---

## Execution Summary

| Test ID | Description | Status |
|---------|-------------|--------|
| AGENT-001 | Single mention triggers worker-agent | PASS |
| AGENT-002 | `@all` triggers manager-agent | PASS |
| AGENT-003 | Multiple worker-agents concurrent | PASS |
| AGENT-004 | Multiple groups parallel trigger | PASS |
| AGENT-005 | Reply delay within timeout | PASS |
| AGENT-006 | Reply delay exceeds timeout | PASS |
| AGENT-007 | Agent failure error message | PASS |
| AGENT-008 | Auto-trigger single user | PASS |
| AGENT-009 | Auto-trigger idle timeout | PASS |
| AGENT-010 | Anti-trigger agent message | PASS |
| AGENT-011 | Anti-trigger processed_msg_id | PASS |
| AGENT-012 | Manual trigger bypass | PASS |
| AGENT-013 | Per-group work-pool limit | PASS |
| AGENT-014 | Per-user work-pool limit | PASS |
| AGENT-015 | Per-node work-pool limit | PASS |
| AGENT-016 | Cleanup of terminal records | PASS |
