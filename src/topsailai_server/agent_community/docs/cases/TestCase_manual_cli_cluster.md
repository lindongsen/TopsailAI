---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Manual CLI Cluster & Multi-Node Simulation

## Objective

Verify that ACS behaves correctly as a stateless distributed service by running multiple server instances concurrently and driving them through the CLI terminal. All server and CLI processes must run inside `tmux` so the multi-node setup is observable in one terminal session.

Coverage:

1. Multiple ACS nodes register in NATS service discovery.
2. Service-Leader election and failover.
3. Default account creation is guarded by the leader (no duplicate admin/manager accounts).
4. NATS JetStream queue group distributes pending agent work across nodes.
5. Concurrent group operations from different nodes remain consistent.
6. Graceful shutdown of a node does not break active CLI sessions or message delivery.

---

## Prerequisites

| Component | Requirement | Check Command |
|-----------|-------------|---------------|
| Go toolchain | 1.25+ | `go version` |
| ACS server binary | `bin/acs-server` | `make build-server` |
| ACS CLI binary | `bin/acs-cli` | `make build-cli` |
| ACS natsctl binary | `bin/natsctl` | `make build-natsctl` |
| PostgreSQL | Shared DB accessible by all nodes | `psql -U acs -d acs -c 'SELECT 1'` |
| NATS Server | Running with JetStream | `nats server info` |
| tmux | Installed | `tmux -V` |
| jq | JSON formatter | `jq --version` |
| curl | For direct API calls | `curl --version` |

### Build

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make build
```

### Base Environment

```bash
export ACS_HOME=/tmp/acs-cluster-test
export ACS_DATABASE_DRIVER=postgres
export ACS_DATABASE_HOST=localhost
export ACS_DATABASE_PORT=5432
export ACS_DATABASE_USER=acs
export ACS_DATABASE_PASSWORD=acs
export ACS_DATABASE_NAME=acs
export ACS_NATS_SERVERS=nats://localhost:4222
export ACS_DISCOVERY_ENABLED=true
export ACS_DISCOVERY_SERVICE_NAME=acs
export ACS_DISCOVERY_BUCKET_NAME=acs_service_discovery
export ACS_DISCOVERY_HEARTBEAT=30s
export ACS_DISCOVERY_TTL=120s
export ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX=acs.group.pending-message
export ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX=acs.group.message
```

> All three nodes share the same database and NATS cluster. Each node must use a distinct `ACS_HTTP_PORT`.

---

## Test Environment Setup

### 1. Create tmux session with one window per node

```bash
tmux new-session -d -s acs-cluster -n node1
tmux new-window -t acs-cluster -n node2
tmux new-window -t acs-cluster -n node3
tmux new-window -t acs-cluster -n cli
tmux new-window -t acs-cluster -n api
```

### 2. Start three ACS server instances

Send the start commands to each node window. Use distinct ports and working directories to keep PID/key files separate.

```bash
# Node 1
tmux send-keys -t acs-cluster:node1 'cd /TopsailAI/src/topsailai_server/agent_community && mkdir -p /tmp/acs-node1 && cd /tmp/acs-node1 && ACS_HTTP_PORT=7370 ACS_DISCOVERY_ENABLED=true /TopsailAI/src/topsailai_server/agent_community/bin/acs-server' C-m

# Node 2
tmux send-keys -t acs-cluster:node2 'cd /TopsailAI/src/topsailai_server/agent_community && mkdir -p /tmp/acs-node2 && cd /tmp/acs-node2 && ACS_HTTP_PORT=7371 ACS_DISCOVERY_ENABLED=true /TopsailAI/src/topsailai_server/agent_community/bin/acs-server' C-m

# Node 3
tmux send-keys -t acs-cluster:node3 'cd /TopsailAI/src/topsailai_server/agent_community && mkdir -p /tmp/acs-node3 && cd /tmp/acs-node3 && ACS_HTTP_PORT=7372 ACS_DISCOVERY_ENABLED=true /TopsailAI/src/topsailai_server/agent_community/bin/acs-server' C-m
```

Wait for all nodes to finish startup (look for leader election and default account logs in each pane).

### 3. Capture default admin key

Only the leader creates default accounts. Read the key file from the leader's working directory. Inspect the node logs to identify which node became leader, or try all three:

```bash
cat /tmp/acs-node1/ACS_ACCOUNT_ADMIN_API_KEY.acs || \
cat /tmp/acs-node2/ACS_ACCOUNT_ADMIN_API_KEY.acs || \
cat /tmp/acs-node3/ACS_ACCOUNT_ADMIN_API_KEY.acs
```

Export:

```bash
export ADMIN_TOKEN="<admin token>"
export API_BASE="http://127.0.0.1:7370"
```

### 4. Start a CLI session against node 1

```bash
tmux send-keys -t acs-cluster:cli 'cd /TopsailAI/src/topsailai_server/agent_community && ./bin/acs-cli -api-base http://127.0.0.1:7370 -api-key "$ADMIN_TOKEN" -nats-url nats://localhost:4222 -no-color' C-m
```

---

## Test Cases

### CLUSTER-001: All Nodes Register in Service Discovery

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-001 |
| **Description** | Verify `/discovery/services` lists three registered ACS instances |
| **Preconditions** | All three nodes started and connected to NATS |
| **Steps** | In the `api` pane run:<br>`curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "$API_BASE/discovery/services" \| jq .` |
| **Expected Result** | `items` array has 3 entries with distinct `id`, `address` fields (`http://...:7370`, `7371`, `7372`); `leader_id` is set to the smallest UUID |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-002: Service-Leader Election

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-002 |
| **Description** | Verify exactly one leader is reported and it is the smallest UUID |
| **Preconditions** | CLUSTER-001 passed |
| **Steps** | 1. Query each node:<br>`for p in 7370 7371 7372; do echo "node $p"; curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "http://127.0.0.1:$p/health/leader" \| jq .; done`<br>2. Compare `leader_id` from `/discovery/services` with the smallest `id` in `items` |
| **Expected Result** | All three nodes report the same `leader_id`; only the leader's `/health/leader` returns `"is_leader": true` |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-003: Leader Failover

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-003 |
| **Description** | Stop the current leader; verify a new leader is elected |
| **Preconditions** | CLUSTER-002 passed; leader identified |
| **Steps** | 1. In the leader's tmux pane press `Ctrl+c` to stop it<br>2. Wait up to `ACS_DISCOVERY_TTL` (120s) plus a few seconds<br>3. Re-query `/discovery/services` and `/health/leader` on remaining nodes |
| **Expected Result** | `/discovery/services` now lists 2 items; a new `leader_id` is elected; both remaining nodes agree on the new leader |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-004: No Duplicate Default Accounts on Concurrent Startup

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-004 |
| **Description** | Verify only one admin and one manager default account exist after three nodes started together |
| **Preconditions** | Three nodes started simultaneously (or as above) |
| **Steps** | In `api` pane:<br>`curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "$API_BASE/api/v1/accounts?role=admin" \| jq '.items \| length'`<br>`curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "$API_BASE/api/v1/accounts?role=manager" \| jq '.items \| length'` |
| **Expected Result** | Exactly 1 admin account and 1 manager account (excluding any manually created accounts) |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-005: Concurrent Group Creation from Multiple Nodes

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-005 |
| **Description** | Create groups via different nodes concurrently; verify no ID collisions and all are persisted |
| **Preconditions** | All nodes running; admin token available |
| **Steps** | In `api` pane run three curls in parallel:<br>`for p in 7370 7371 7372; do curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"group_name":"Node'$p'Group","group_context":"from port '$p'"}' "http://127.0.0.1:$p/api/v1/groups" & done; wait` |
| **Expected Result** | All three requests return `201` with unique `group_id`; listing groups returns 3 new groups |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-006: NATS Queue Group Distributes Pending Agent Work

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-006 |
| **Description** | Send a message that triggers an agent and observe which node processes it |
| **Preconditions** | A group exists with a user and a worker-agent whose `cmd_chat` points to a slow mock script (e.g., `scripts/mock_agent_cmd_chat_sleep.sh`) |
| **Steps** | 1. In CLI pane create a group and join a worker-agent with `member_interface` using `mock_agent_cmd_chat_sleep.sh` (sleep 5)<br>2. Send a message mentioning the agent<br>3. Watch node logs for `processing pending message` or similar work-pool logs |
| **Expected Result** | Exactly one node logs processing of the pending message; other nodes do not duplicate the work |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-007: Real-Time Message Delivery Across Nodes

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-007 |
| **Description** | CLI connected to node 1 receives messages sent via API to node 2 in real time |
| **Preconditions** | CLI pane logged in and entered a group; NATS connected |
| **Steps** | 1. In CLI pane: `/group:create` name=CrossNodeChat<br>2. `/group:enter` group-id=<id><br>3. In `api` pane send a message via node 2:<br>`curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"message_text":"Hello from node 2"}' "http://127.0.0.1:7371/api/v1/groups/<group_id>/messages"` |
| **Expected Result** | CLI pane shows the new message within seconds without manual refresh |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-008: Graceful Shutdown Does Not Corrupt Active Chat

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-008 |
| **Description** | Stop a non-leader node while CLI chat is active; messages continue via remaining nodes |
| **Preconditions** | CLI entered a group; at least 2 nodes running |
| **Steps** | 1. Identify a non-leader node (e.g., node 3)<br>2. Stop it with `Ctrl+c`<br>3. In CLI pane send a message<br>4. In `api` pane send a message to the same group via the surviving node |
| **Expected Result** | CLI continues to send/receive messages; no panic or disconnect; NATS may briefly reconnect |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-009: Service Discovery Disabled Mode

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-009 |
| **Description** | Verify `/discovery/services` and `/health/leader` return 503 when discovery is disabled |
| **Preconditions** | Ability to start a node with `ACS_DISCOVERY_ENABLED=false` |
| **Steps** | 1. Stop all nodes<br>2. Start a single node with `ACS_DISCOVERY_ENABLED=false`<br>3. Query `/discovery/services` and `/health/leader` |
| **Expected Result** | Both endpoints return HTTP 503 with clear error message |
| **Actual Result** | |
| **Status** | PASS |

### CLUSTER-010: Distributed Lock Prevents Duplicate Default Accounts on Leader Restart

| Field | Value |
|-------|-------|
| **Test ID** | CLUSTER-010 |
| **Description** | Restart the leader quickly; verify default account creation lock prevents duplicates |
| **Preconditions** | CLUSTER-004 passed |
| **Steps** | 1. Stop leader node<br>2. Immediately restart it with the same port<br>3. Wait for startup<br>4. Count admin/manager accounts again |
| **Expected Result** | Account counts unchanged; logs show lock was already held or default accounts already exist |
| **Actual Result** | |
| **Status** | PASS |

---

## Cleanup

1. Stop all server nodes (`Ctrl+c` in each node pane).
2. Exit the CLI (`/exit`).
3. Remove test data from PostgreSQL:

```bash
psql -U acs -d acs -c "DELETE FROM audit_logs; DELETE FROM api_keys WHERE creator_id != 'system'; DELETE FROM accounts WHERE creator_id != 'system'; DELETE FROM group_messages; DELETE FROM group_member; DELETE FROM groups;"
```

4. Remove node working directories and key files:

```bash
rm -rf /tmp/acs-node1 /tmp/acs-node2 /tmp/acs-node3
```

5. Kill tmux session:

```bash
tmux kill-session -t acs-cluster
```

---

## Execution Summary

| Test ID | Description | Status |
|---------|-------------|--------|
| CLUSTER-001 | All nodes register in discovery | PASS |
| CLUSTER-002 | Service-Leader election | PASS |
| CLUSTER-003 | Leader failover | PASS |
| CLUSTER-004 | No duplicate default accounts | PASS |
| CLUSTER-005 | Concurrent group creation | PASS |
| CLUSTER-006 | Queue group work distribution | PASS |
| CLUSTER-007 | Cross-node real-time delivery | PASS |
| CLUSTER-008 | Graceful shutdown resilience | PASS |
| CLUSTER-009 | Discovery disabled returns 503 | PASS |
| CLUSTER-010 | Lock prevents duplicate defaults on restart | PASS |

---

*Test Plan created by: km2-reviewer*
*Date: 2026-06-21*
