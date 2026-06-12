---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Manual API Testing

## Objective

Manual API tests verify REST API endpoints by executing real HTTP requests against a running ACS server using `curl` or HTTP clients. These tests complement automated integration tests by:

1. **Human-verifiable behavior**: Each request/response is visible and inspectable
2. **Edge case exploration**: Testing boundary conditions that automated tests may miss
3. **Error path validation**: Verifying HTTP status codes, error messages, and validation behavior
4. **Real-world workflow validation**: End-to-end user workflows executed step-by-step
5. **Infrastructure independence**: Can be run against any deployed instance (dev, staging, prod)

---

## Prerequisites

| Component | Requirement | Check Command |
|-----------|-------------|---------------|
| ACS Server | Running on port 7370 | `curl -s http://127.0.0.1:7370/healthz` |
| PostgreSQL | `agent_community` database accessible | Server readiness check |
| NATS | Running with JetStream | Server readiness check |
| curl | Version 7.68+ | `curl --version` |
| jq | JSON formatter (optional) | `jq --version` |
| Python 3 | 3.9+ with `requests` | `python3 -c "import requests"` |

**Environment Variable:**
```bash
export ACS_API_BASE="http://127.0.0.1:7370"
```

---

## Test Execution Legend

| Status | Meaning |
|--------|---------|
| PASS | Actual result matches expected result |
| FAIL | Actual result does NOT match expected result |
| PENDING | Test not yet executed |
| SKIP | Test skipped (e.g., feature not implemented) |
| BLOCKED | Cannot execute due to prerequisite failure |

---

## Category A: Health & Readiness Endpoints

### MANUAL-API-001: Liveness Probe

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-001 |
| **Description** | Verify the liveness probe returns alive status |
| **Preconditions** | ACS server process is running |
| **Steps** | `curl -s "${ACS_API_BASE}/healthz" \| jq .` |
| **Expected Result** | HTTP 200, body: `{"status":"alive"}` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-002: Readiness Probe (Ready)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-002 |
| **Description** | Verify readiness when all dependencies are healthy |
| **Preconditions** | PostgreSQL and NATS are connected |
| **Steps** | `curl -s "${ACS_API_BASE}/readyz" \| jq .` |
| **Expected Result** | HTTP 200, body: `{"status":"ready","checks":{"database":"ok"}}` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-003: Comprehensive Health Check

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-003 |
| **Description** | Verify detailed health status of all components |
| **Preconditions** | All services running |
| **Steps** | `curl -s "${ACS_API_BASE}/health" \| jq .` |
| **Expected Result** | HTTP 200, body contains `status`, `version`, `checks` with `database` and `nats` |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category B: Group CRUD Operations

### MANUAL-API-004: Create Group (Minimal)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-004 |
| **Description** | Create a group with only required fields |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups" -H "Content-Type: application/json" -d '{"group_name":"Manual Test Group","group_context":"Created via manual API test"}' \| jq .``` |
| **Expected Result** | HTTP 201, response contains `group_id` (UUID), `group_name`, `group_context`, `create_at_ms`, `update_at_ms` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-005: Create Group with Secret Key

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-005 |
| **Description** | Create a private group with group_key; verify key is not returned in plaintext |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups" -H "Content-Type: application/json" -d '{"group_name":"Secret Group","group_context":"Private","group_key":"my-secret-key"}' \| jq .``` |
| **Expected Result** | HTTP 201, `group_key` is empty or hashed (NOT "my-secret-key") |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-006: Create Group — Invalid Input (Empty Name)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-006 |
| **Description** | Verify validation rejects empty group_name |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups" -H "Content-Type: application/json" -d '{"group_name":"","group_context":"test"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400, body contains error message about invalid request |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-007: Create Group — Invalid Input (Missing Required Field)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-007 |
| **Description** | Verify validation rejects missing group_name |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups" -H "Content-Type: application/json" -d '{"group_context":"test"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400, body contains validation error |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-008: Get Group

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-008 |
| **Description** | Retrieve a group by its ID |
| **Preconditions** | Group created in MANUAL-API-004; save $GROUP_ID |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}" \| jq .``` |
| **Expected Result** | HTTP 200, body matches created group data |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-009: Get Group — Not Found

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-009 |
| **Description** | Verify 404 for non-existent group |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups/non-existent-id" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 404, body contains error message |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-010: List Groups

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-010 |
| **Description** | List all groups with default pagination |
| **Preconditions** | At least one group exists |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups" \| jq .``` |
| **Expected Result** | HTTP 200, body contains `items` array, `total`, `offset`, `limit` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-011: List Groups with Pagination

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-011 |
| **Description** | Verify offset and limit parameters |
| **Preconditions** | Multiple groups exist |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups?offset=0&limit=2" \| jq .``` |
| **Expected Result** | HTTP 200, `items` has at most 2 entries, `offset=0`, `limit=2` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-012: List Groups with Sorting

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-012 |
| **Description** | Verify sorting by create_at_ms ascending and descending |
| **Preconditions** | Multiple groups exist |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups?sort_key=create_at_ms&order_by=asc" \| jq '.items[0:2] \| map(.create_at_ms)'``` |
| **Expected Result** | HTTP 200, timestamps are in ascending order |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-013: Update Group

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-013 |
| **Description** | Update group name and context |
| **Preconditions** | Group exists ($GROUP_ID from MANUAL-API-004) |
| **Steps** | ```curl -s -X PUT "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}" -H "Content-Type: application/json" -d '{"group_name":"Updated Manual Group","group_context":"Updated context"}' \| jq .``` |
| **Expected Result** | HTTP 200, `group_name` and `group_context` updated, `update_at_ms` > `create_at_ms` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-014: Update Group — Partial Update (Name Only)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-014 |
| **Description** | Update only group_name, leaving other fields unchanged |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X PUT "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}" -H "Content-Type: application/json" -d '{"group_name":"Partially Updated"}' \| jq .``` |
| **Expected Result** | HTTP 200, only `group_name` changed, `group_context` preserved |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-015: Delete Group

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-015 |
| **Description** | Delete a group and verify it is removed |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X DELETE "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 204 (or 200 with message body), subsequent GET returns 404 |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-016: Delete Group — Not Found

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-016 |
| **Description** | Verify 404 when deleting non-existent group |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -X DELETE "${ACS_API_BASE}/api/v1/groups/non-existent-id" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 404 |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category C: Group Member Management

### MANUAL-API-017: Join Group as User

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-017 |
| **Description** | Add a human user to a group |
| **Preconditions** | Group exists ($GROUP_ID) |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" -H "Content-Type: application/json" -d '{"member_id":"manual-user-001","member_name":"Manual Tester","member_description":"A human tester","member_type":"user"}' \| jq .``` |
| **Expected Result** | HTTP 201, `member_status` is "online", `member_type` is "user" |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-018: Join Group as Worker-Agent

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-018 |
| **Description** | Add a worker-agent with interface configuration |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" -H "Content-Type: application/json" -d '{"member_id":"manual-agent-001","member_name":"Test Worker Agent","member_description":"A test worker agent","member_type":"worker-agent","member_interface":"{\"adaptor\":\"topsailai_agent\",\"environments\":{\"ACS_AGENT_API_BASE\":\"http://127.0.0.1:7373\",\"ACS_AGENT_API_KEY\":\"test-key\"},\"timeout_chat\":30}"}' \| jq .``` |
| **Expected Result** | HTTP 201, `member_type` is "worker-agent", `member_interface` is non-empty JSON string |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-019: Join Group as Manager-Agent

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-019 |
| **Description** | Add a manager-agent to coordinate group |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" -H "Content-Type: application/json" -d '{"member_id":"manual-manager-001","member_name":"Test Manager","member_description":"Group coordinator","member_type":"manager-agent","member_interface":"{\"adaptor\":\"topsailai_agent\",\"environments\":{\"ACS_AGENT_API_BASE\":\"http://127.0.0.1:7373\",\"ACS_AGENT_API_KEY\":\"test-key\"},\"timeout_chat\":30}"}' \| jq .``` |
| **Expected Result** | HTTP 201, `member_type` is "manager-agent" |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-020: Join Group — Duplicate Member

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-020 |
| **Description** | Verify duplicate member_id is rejected |
| **Preconditions** | Member already joined (MANUAL-API-017) |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" -H "Content-Type: application/json" -d '{"member_id":"manual-user-001","member_name":"Duplicate","member_type":"user"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 409 or 400 with error about duplicate member |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-021: Join Group — Invalid Member Type

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-021 |
| **Description** | Verify invalid member_type is rejected |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" -H "Content-Type: application/json" -d '{"member_id":"bad-type-user","member_name":"Bad","member_type":"invalid-type"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400 with validation error |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-022: List Group Members

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-022 |
| **Description** | List all members in a group |
| **Preconditions** | Members exist in group |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" \| jq .``` |
| **Expected Result** | HTTP 200, `items` contains user, worker-agent, manager-agent; `total` >= 3 |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-023: Update Member Status

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-023 |
| **Description** | Update member name and status |
| **Preconditions** | Member exists ($MEMBER_ID = manual-user-001) |
| **Steps** | ```curl -s -X PUT "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members/manual-user-001" -H "Content-Type: application/json" -d '{"member_name":"Updated Tester","member_status":"idle"}' \| jq .``` |
| **Expected Result** | HTTP 200, `member_name` and `member_status` updated |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-024: Leave Group

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-024 |
| **Description** | Remove a member from a group |
| **Preconditions** | Member exists |
| **Steps** | ```curl -s -X DELETE "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members/manual-user-001" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 204 (or 200), member no longer appears in list |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-025: Leave Group — Not Found

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-025 |
| **Description** | Verify 404 when removing non-existent member |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X DELETE "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members/non-existent-member" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 404 |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category D: Message Operations

### MANUAL-API-026: Create Message (Plain Text)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-026 |
| **Description** | Send a plain text message to a group |
| **Preconditions** | Group exists, sender is a member |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"Hello from manual API test!","sender_id":"manual-user-001","sender_type":"user"}' \| jq .``` |
| **Expected Result** | HTTP 201, `message_id` generated, `sender_id` and `sender_type` match, `is_deleted`=false |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-027: Create Message with Attachments

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-027 |
| **Description** | Send a message with file attachments |
| **Preconditions** | Group exists, sender is a member |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"See this image","message_attachments":[{"data":"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==","size":67,"format":"image/png"}],"sender_id":"manual-user-001","sender_type":"user"}' \| jq .``` |
| **Expected Result** | HTTP 201, `message_attachments` array preserved with data, size, format |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-028: Create Message with Mention (by ID)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-028 |
| **Description** | Send message mentioning an agent by member_id |
| **Preconditions** | Agent member exists in group |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"Hello @manual-agent-001, can you help?","sender_id":"manual-user-001","sender_type":"user"}' \| jq .``` |
| **Expected Result** | HTTP 201, `mentions` array contains agent info with `member_id`, `member_name`, `member_type` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-029: Create Message with @all Mention

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-029 |
| **Description** | Send message with @all to trigger manager-agent |
| **Preconditions** | Manager-agent exists in group |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"@all Please review this document","sender_id":"manual-user-001","sender_type":"user"}' \| jq .``` |
| **Expected Result** | HTTP 201, `mentions` contains all members or @all marker; NATS pending message published |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-030: Create Message — Invalid Sender (Not a Member)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-030 |
| **Description** | Verify message from non-member is rejected |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"Unauthorized","sender_id":"not-a-member","sender_type":"user"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400 with error about invalid sender |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-031: Create Message — Missing Required Fields

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-031 |
| **Description** | Verify missing message_text or sender_id is rejected |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"sender_id":"manual-user-001","sender_type":"user"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400 with validation error |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-032: List Messages

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-032 |
| **Description** | List all messages in a group |
| **Preconditions** | Messages exist in group |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" \| jq .``` |
| **Expected Result** | HTTP 200, `items` array contains messages, `total` >= 1 |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-033: List Messages with Pagination

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-033 |
| **Description** | Verify message pagination with offset and limit |
| **Preconditions** | Multiple messages exist |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages?offset=0&limit=2" \| jq '.items \| length'``` |
| **Expected Result** | HTTP 200, returns at most 2 messages |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-034: List Messages with Time Range Filter

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-034 |
| **Description** | Filter messages by create_at_ms time range |
| **Preconditions** | Messages exist with known timestamps |
| **Steps** | ```START=$(($(date +%s)*1000 - 600000)); END=$(($(date +%s)*1000 + 600000)); curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages?create_at_ms=${START}-${END}" \| jq '.items \| length'``` |
| **Expected Result** | HTTP 200, returns messages within the time range |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-035: List Messages with Sorting

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-035 |
| **Description** | Verify ascending and descending sort by create_at_ms |
| **Preconditions** | Multiple messages exist |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages?sort_key=create_at_ms&order_by=asc" \| jq '.items[0:2] \| map(.create_at_ms)'``` |
| **Expected Result** | HTTP 200, timestamps in ascending order |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-036: Update Message

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-036 |
| **Description** | Edit an existing message |
| **Preconditions** | Message exists ($MESSAGE_ID from MANUAL-API-026) |
| **Steps** | ```curl -s -X PUT "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages/${MESSAGE_ID}" -H "Content-Type: application/json" -d '{"message_text":"This message has been edited"}' \| jq .``` |
| **Expected Result** | HTTP 200, `message_text` updated, `update_at_ms` refreshed |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-037: Delete Message (Soft Delete / Withdraw)

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-037 |
| **Description** | Soft-delete a message; verify record remains but content is cleared |
| **Preconditions** | Message exists |
| **Steps** | ```curl -s -X DELETE "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages/${MESSAGE_ID}" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 204 (or 200), message `is_deleted`=true, `message_text` empty or marked deleted |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-038: Delete Message — Not Found

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-038 |
| **Description** | Verify 404 when deleting non-existent message |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X DELETE "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages/non-existent-msg" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 404 |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category E: Agent Trigger Scenarios

### MANUAL-API-039: Mention Trigger — Single Agent

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-039 |
| **Description** | Verify mentioning a single agent triggers it with ACS_AGENT_MODE=agent |
| **Preconditions** | Group with user + worker-agent; mock agent server running |
| **Steps** | 1. Send message: `@manual-agent-001 Help me!` 2. Poll messages for agent response |
| **Expected Result** | Agent response message appears with `sender_type=worker-agent`, `processed_msg_id` set to original message |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-040: @all Trigger — Manager-Agent Priority

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-040 |
| **Description** | Verify @all triggers manager-agent, not worker-agents |
| **Preconditions** | Group with user + manager-agent + worker-agents |
| **Steps** | 1. Send message: `@all Everyone please respond` 2. Check which agent responds |
| **Expected Result** | Only manager-agent responds; worker-agents do not trigger |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-041: Auto-Trigger — Single User in Group

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-041 |
| **Description** | Verify message without mentions triggers manager-agent when only 1 user exists |
| **Preconditions** | Group with exactly 1 user + 1 manager-agent |
| **Steps** | 1. Send message without mentions: `What do you think?` 2. Wait for auto-trigger |
| **Expected Result** | Manager-agent auto-triggered, response appears |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-042: Anti-Trigger — Agent Message Does Not Trigger

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-042 |
| **Description** | Verify messages from agents do not trigger further agents |
| **Preconditions** | Agent response exists in message history |
| **Steps** | 1. Check that agent response message has no `processed_msg_id` chain beyond max length 2. Verify no infinite loop |
| **Expected Result** | Agent messages do not create new pending messages; max chain length respected |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category F: Edge Cases & Error Handling

### MANUAL-API-043: Invalid JSON Body

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-043 |
| **Description** | Verify malformed JSON is rejected |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups" -H "Content-Type: application/json" -d '{invalid json' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400 with JSON parse error |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-044: Method Not Allowed

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-044 |
| **Description** | Verify PATCH is not supported on groups |
| **Preconditions** | Group exists |
| **Steps** | ```curl -s -X PATCH "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}" -H "Content-Type: application/json" -d '{"group_name":"test"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 405 Method Not Allowed |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-045: Not Found Route

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-045 |
| **Description** | Verify undefined routes return 404 |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s "${ACS_API_BASE}/api/v1/non-existent-endpoint" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 404 |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-046: Trace ID — Auto-Generated

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-046 |
| **Description** | Verify trace_id is auto-generated in response |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -D - "${ACS_API_BASE}/healthz" 2>&1 \| grep -i "X-Trace-ID\|trace_id"``` |
| **Expected Result** | Response body contains `trace_id` field; response header contains `X-Trace-ID` |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-047: Trace ID — Preserved from Request

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-047 |
| **Description** | Verify custom trace ID is preserved in response |
| **Preconditions** | Server is ready |
| **Steps** | ```curl -s -H "X-Trace-ID: manual-test-trace-123" "${ACS_API_BASE}/healthz" \| jq '.trace_id'``` |
| **Expected Result** | `trace_id` equals "manual-test-trace-123" |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-048: Very Long Message Text

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-048 |
| **Description** | Verify server handles messages up to reasonable size limits |
| **Preconditions** | Group exists, sender is member |
| **Steps** | ```LONG_TEXT=$(python3 -c "print('A'*5000)"); curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d "{\"message_text\":\"$LONG_TEXT\",\"sender_id\":\"manual-user-001\",\"sender_type\":\"user\"}" -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 201, message stored with full text |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-049: Unicode and Multi-byte Characters

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-049 |
| **Description** | Verify UTF-8 characters are preserved correctly |
| **Preconditions** | Group exists, sender is member |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"你好世界 🎉 ñoño émojis: 🔥🚀💡","sender_id":"manual-user-001","sender_type":"user"}' \| jq '.data.message_text'``` |
| **Expected Result** | HTTP 201, message_text contains exact Unicode string |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-050: Empty Message Text

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-050 |
| **Description** | Verify empty message text is handled |
| **Preconditions** | Group exists, sender is member |
| **Steps** | ```curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d '{"message_text":"","sender_id":"manual-user-001","sender_type":"user"}' -w "\nHTTP_CODE:%{http_code}"``` |
| **Expected Result** | HTTP 400 (rejected) or HTTP 201 (allowed); behavior documented |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category G: Concurrent / Race Condition Scenarios

### MANUAL-API-051: Rapid Message Creation

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-051 |
| **Description** | Send 10 messages rapidly and verify all are stored |
| **Preconditions** | Group exists, sender is member |
| **Steps** | ```for i in {1..10}; do curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" -H "Content-Type: application/json" -d "{\"message_text\":\"Rapid message $i\",\"sender_id\":\"manual-user-001\",\"sender_type\":\"user\"}" > /dev/null & done; wait; curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/messages" \| jq '.total'``` |
| **Expected Result** | All 10 messages stored, total count increased by 10 |
| **Actual Result** | |
| **Status** | PENDING |

### MANUAL-API-052: Concurrent Member Joins

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-052 |
| **Description** | Multiple members join simultaneously |
| **Preconditions** | Group exists |
| **Steps** | ```for i in {1..5}; do curl -s -X POST "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" -H "Content-Type: application/json" -d "{\"member_id\":\"concurrent-user-$i\",\"member_name\":\"User $i\",\"member_type\":\"user\"}" > /dev/null & done; wait; curl -s "${ACS_API_BASE}/api/v1/groups/${GROUP_ID}/members" \| jq '.total'``` |
| **Expected Result** | All 5 members joined successfully, no duplicates or errors |
| **Actual Result** | |
| **Status** | PENDING |

---

## Category H: Cleanup & Teardown

### MANUAL-API-053: Delete Group with Members and Messages

| Field | Value |
|-------|-------|
| **Test ID** | MANUAL-API-053 |
| **Description** | Verify deleting a group cascades to members and messages |
| **Preconditions** | Group with members and messages exists |
| **Steps** | 1. DELETE group 2. GET group → 404 3. GET members → 404 4. GET messages → 404 |
| **Expected Result** | All related data is removed; 404 for all subsequent queries |
| **Actual Result** | |
| **Status** | PENDING |

---

## Test Execution Summary

| Category | Total Tests | Passed | Failed | Skipped | Pending |
|----------|-------------|--------|--------|---------|---------|
| A: Health & Readiness | 3 | | | | |
| B: Group CRUD | 13 | | | | |
| C: Member Management | 9 | | | | |
| D: Message Operations | 13 | | | | |
| E: Agent Trigger | 4 | | | | |
| F: Edge Cases & Errors | 8 | | | | |
| G: Concurrent Scenarios | 2 | | | | |
| H: Cleanup | 1 | | | | |
| **Total** | **53** | | | | |

---

## Automated Execution

Two scripts are provided for automated execution of these test cases:

1. **`tests/e2e/manual_api_test.sh`** — Bash/curl-based script
2. **`tests/e2e/manual_api_test.py`** — Python/requests-based script

Run either script to execute the manual API tests and populate the Actual Result column:

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./tests/e2e/manual_api_test.sh
# OR
python3 tests/e2e/manual_api_test.py
```

---

*Test Plan created by: km1-tester*
*Date: 2026-06-13*
