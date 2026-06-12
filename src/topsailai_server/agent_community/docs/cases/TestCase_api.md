---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: API Testing

## Overview

This document describes test scenarios for all REST API endpoints of the AI-Agent Community Server (ACS).

---

## TC-API-001: Health Endpoints

### TC-API-001-1: Liveness Check

| Field | Value |
|-------|-------|
| **Endpoint** | GET /healthz |
| **Input** | None |
| **Expected Output** | Status: 200, Body: `{"status": "ok"}` |
| **Pass Criteria** | Returns 200 with correct JSON structure |

### TC-API-001-2: Readiness Check (Ready)

| Field | Value |
|-------|-------|
| **Endpoint** | GET /readyz |
| **Input** | Database is connected |
| **Expected Output** | Status: 200, Body: `{"status": "ready"}` |
| **Pass Criteria** | Returns 200 when database is accessible |

### TC-API-001-3: Readiness Check (Not Ready)

| Field | Value |
|-------|-------|
| **Endpoint** | GET /readyz |
| **Input** | Database is disconnected |
| **Expected Output** | Status: 503, Body: `{"status": "not ready", "checks": {"database": "unreachable"}}` |
| **Pass Criteria** | Returns 503 when database is not accessible |

### TC-API-001-4: Comprehensive Health

| Field | Value |
|-------|-------|
| **Endpoint** | GET /health |
| **Input** | All services running |
| **Expected Output** | Status: 200, Body with `status`, `checks` containing database and NATS status |
| **Pass Criteria** | Returns detailed health status for all components |

---

## TC-API-002: Group CRUD

### TC-API-002-1: Create Group

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups |
| **Input** | `{"group_name": "Test Group", "group_context": "Test context"}` |
| **Expected Output** | Status: 201, Body contains `group_id`, `group_name`, `group_context`, `create_at_ms`, `update_at_ms` |
| **Pass Criteria** | Group created with valid UUID, timestamps are set |

### TC-API-002-2: Create Group with Secret Key

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups |
| **Input** | `{"group_name": "Private Group", "group_context": "Secret", "group_key": "my-secret"}` |
| **Expected Output** | Status: 201, `group_key` is hashed/empty in response |
| **Pass Criteria** | Group created, key is not returned in plaintext |

### TC-API-002-3: Create Group - Invalid Input

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups |
| **Input** | `{"group_name": ""}` (empty name) |
| **Expected Output** | Status: 400, Body contains error message |
| **Pass Criteria** | Returns 400 with validation error |

### TC-API-002-4: Get Group

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups/{group_id} |
| **Input** | Valid group_id |
| **Expected Output** | Status: 200, Body contains full group data |
| **Pass Criteria** | Returns correct group information |

### TC-API-002-5: Get Group - Not Found

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups/invalid-uuid |
| **Input** | Invalid or non-existent group_id |
| **Expected Output** | Status: 404, Body: `{"error": "group not found"}` |
| **Pass Criteria** | Returns 404 for non-existent group |

### TC-API-002-6: List Groups

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups |
| **Input** | None |
| **Expected Output** | Status: 200, Body contains `items` array, `total`, `offset`, `limit` |
| **Pass Criteria** | Returns paginated list of groups |

### TC-API-002-7: List Groups with Pagination

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups?offset=0&limit=2 |
| **Input** | offset=0, limit=2 |
| **Expected Output** | Status: 200, `items` has at most 2 items, `offset=0`, `limit=2` |
| **Pass Criteria** | Pagination parameters are respected |

### TC-API-002-8: List Groups with Time Range Filter

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups?create_at_ms=1704067200000-1704153600000 |
| **Input** | Time range in epoch milliseconds |
| **Expected Output** | Status: 200, Only groups created within the time range |
| **Pass Criteria** | Time range filter is applied correctly |

### TC-API-002-9: Update Group

| Field | Value |
|-------|-------|
| **Endpoint** | PUT /api/v1/groups/{group_id} |
| **Input** | `{"group_name": "Updated Name", "group_context": "Updated context"}` |
| **Expected Output** | Status: 200, Body contains updated fields, `update_at_ms` is newer |
| **Pass Criteria** | Group is updated, timestamp is refreshed |

### TC-API-002-10: Delete Group

| Field | Value |
|-------|-------|
| **Endpoint** | DELETE /api/v1/groups/{group_id} |
| **Input** | Valid group_id |
| **Expected Output** | Status: 200, Body: `{"message": "group deleted"}` |
| **Pass Criteria** | Group and associated members/messages are deleted |

### TC-API-002-11: Delete Group - Not Found

| Field | Value |
|-------|-------|
| **Endpoint** | DELETE /api/v1/groups/invalid-uuid |
| **Input** | Invalid group_id |
| **Expected Output** | Status: 404 |
| **Pass Criteria** | Returns 404 for non-existent group |

---

## TC-API-003: Member Operations

### TC-API-003-1: Join Group as User

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/members |
| **Input** | `{"member_id": "user-001", "member_name": "Alice", "member_type": "user"}` |
| **Expected Output** | Status: 201, Body contains member data with `member_status: online` |
| **Pass Criteria** | User is added to group |

### TC-API-003-2: Join Group as Agent

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/members |
| **Input** | `{"member_id": "agent-001", "member_name": "Agent", "member_type": "worker-agent", "member_interface": {...}}` |
| **Expected Output** | Status: 201, Body contains agent member data |
| **Pass Criteria** | Agent is added to group with interface |

### TC-API-003-3: Join Group - Invalid Type

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/members |
| **Input** | `{"member_id": "x", "member_name": "X", "member_type": "invalid-type"}` |
| **Expected Output** | Status: 400 |
| **Pass Criteria** | Returns 400 for invalid member_type |

### TC-API-003-4: Join Group - Duplicate Member

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/members |
| **Input** | Same member_id twice |
| **Expected Output** | Status: 409 or 400 |
| **Pass Criteria** | Prevents duplicate member entries |

### TC-API-003-5: List Group Members

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups/{group_id}/members |
| **Input** | Valid group_id |
| **Expected Output** | Status: 200, Body contains `items` array with all members |
| **Pass Criteria** | Returns all members of the group |

### TC-API-003-6: Update Member

| Field | Value |
|-------|-------|
| **Endpoint** | PUT /api/v1/groups/{group_id}/members/{member_id} |
| **Input** | `{"member_name": "Updated Name", "member_status": "idle"}` |
| **Expected Output** | Status: 200, Body contains updated member data |
| **Pass Criteria** | Member information is updated |

### TC-API-003-7: Leave Group

| Field | Value |
|-------|-------|
| **Endpoint** | DELETE /api/v1/groups/{group_id}/members/{member_id} |
| **Input** | Valid group_id and member_id |
| **Expected Output** | Status: 200, Body: `{"message": "member left group"}` |
| **Pass Criteria** | Member is removed from group |

### TC-API-003-8: Leave Group - Not Found

| Field | Value |
|-------|-------|
| **Endpoint** | DELETE /api/v1/groups/{group_id}/members/non-existent |
| **Input** | Non-existent member_id |
| **Expected Output** | Status: 404 |
| **Pass Criteria** | Returns 404 for non-existent member |

---

## TC-API-004: Message Operations

### TC-API-004-1: Create Message

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/messages |
| **Input** | `{"message_text": "Hello world", "sender_id": "user-001", "sender_type": "user"}` |
| **Expected Output** | Status: 201, Body contains message data with `message_id`, timestamps |
| **Pass Criteria** | Message is created and stored |

### TC-API-004-2: Create Message with Attachments

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/messages |
| **Input** | `{"message_text": "See attachment", "message_attachments": [{"data": "base64...", "size": 1024, "format": "image/png"}], "sender_id": "user-001", "sender_type": "user"}` |
| **Expected Output** | Status: 201, Body contains message with attachments array |
| **Pass Criteria** | Message with attachments is stored correctly |

### TC-API-004-3: Create Message with Mentions

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/messages |
| **Input** | `{"message_text": "@agent-001 Hello", "sender_id": "user-001", "sender_type": "user"}` |
| **Expected Output** | Status: 201, Body contains `mentions` array with agent info |
| **Pass Criteria** | Mentions are extracted and stored |

### TC-API-004-4: Create Message - Trigger Agent

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups/{group_id}/messages |
| **Input** | Message mentioning an agent in a group with only one user |
| **Expected Output** | Status: 201, Message stored, NATS pending message published |
| **Pass Criteria** | Message created and agent trigger initiated |

### TC-API-004-5: List Messages

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups/{group_id}/messages |
| **Input** | Valid group_id |
| **Expected Output** | Status: 200, Body contains paginated messages |
| **Pass Criteria** | Returns messages in the group |

### TC-API-004-6: List Messages with Pagination

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups/{group_id}/messages?offset=0&limit=10 |
| **Input** | offset=0, limit=10 |
| **Expected Output** | Status: 200, At most 10 messages returned |
| **Pass Criteria** | Pagination works correctly |

### TC-API-004-7: List Messages Sorted

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups/{group_id}/messages?sort_key=create_at_ms&order_by=asc |
| **Input** | sort by create_at_ms ascending |
| **Expected Output** | Status: 200, Messages sorted oldest first |
| **Pass Criteria** | Sorting parameters are applied |

### TC-API-004-8: Update Message

| Field | Value |
|-------|-------|
| **Endpoint** | PUT /api/v1/groups/{group_id}/messages/{message_id} |
| **Input** | `{"message_text": "Updated text"}` |
| **Expected Output** | Status: 200, Body contains updated message |
| **Pass Criteria** | Message text is updated |

### TC-API-004-9: Delete Message (Soft Delete)

| Field | Value |
|-------|-------|
| **Endpoint** | DELETE /api/v1/groups/{group_id}/messages/{message_id} |
| **Input** | Valid message_id |
| **Expected Output** | Status: 200, Body: `{"message": "message deleted"}` |
| **Pass Criteria** | Message content is cleared, `is_deleted=true`, record remains |

### TC-API-004-10: Delete Message - Not Found

| Field | Value |
|-------|-------|
| **Endpoint** | DELETE /api/v1/groups/{group_id}/messages/invalid-id |
| **Input** | Invalid message_id |
| **Expected Output** | Status: 404 |
| **Pass Criteria** | Returns 404 for non-existent message |

---

## TC-API-005: Query Parameters

### TC-API-005-1: Offset and Limit

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups?offset=5&limit=3 |
| **Input** | offset=5, limit=3 |
| **Expected Output** | Returns items starting from index 5, at most 3 items |
| **Pass Criteria** | Pagination parameters work on all list endpoints |

### TC-API-005-2: Sort Key and Order

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups?sort_key=group_name&order_by=asc |
| **Input** | sort by group_name ascending |
| **Expected Output** | Groups sorted alphabetically by name |
| **Pass Criteria** | Sorting works correctly |

### TC-API-005-3: Time Range Filter - Create Time

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/messages?create_at_ms=1704067200000-1704153600000 |
| **Input** | Time range: start-end (epoch ms) |
| **Expected Output** | Only messages created within the range |
| **Pass Criteria** | Time filter is applied correctly |

### TC-API-005-4: Time Range Filter - Update Time

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups?update_at_ms=1704067200000-1704153600000 |
| **Input** | Time range: start-end (epoch ms) |
| **Expected Output** | Only groups updated within the range |
| **Pass Criteria** | Update time filter works |

### TC-API-005-5: Invalid Time Range Format

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/groups?create_at_ms=invalid |
| **Input** | Invalid time range format |
| **Expected Output** | Status: 400 or ignored filter |
| **Pass Criteria** | Handles invalid format gracefully |

---

## TC-API-006: Error Handling

### TC-API-006-1: Invalid JSON Body

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups |
| **Input** | Invalid JSON: `{invalid` |
| **Expected Output** | Status: 400, Error about invalid JSON |
| **Pass Criteria** | Returns clear error message |

### TC-API-006-2: Missing Required Fields

| Field | Value |
|-------|-------|
| **Endpoint** | POST /api/v1/groups |
| **Input** | `{}` (empty body) |
| **Expected Output** | Status: 400, Validation error |
| **Pass Criteria** | Validates required fields |

### TC-API-006-3: Method Not Allowed

| Field | Value |
|-------|-------|
| **Endpoint** | PATCH /api/v1/groups/{group_id} |
| **Input** | Any body |
| **Expected Output** | Status: 405 |
| **Pass Criteria** | Returns 405 for unsupported methods |

### TC-API-006-4: Not Found Route

| Field | Value |
|-------|-------|
| **Endpoint** | GET /api/v1/non-existent |
| **Input** | None |
| **Expected Output** | Status: 404 |
| **Pass Criteria** | Returns 404 for undefined routes |

---

## TC-API-007: Trace ID

### TC-API-007-1: Auto-Generated Trace ID

| Field | Value |
|-------|-------|
| **Endpoint** | Any endpoint |
| **Input** | Request without X-Trace-ID header |
| **Expected Output** | Response contains `trace_id` in body and `X-Trace-ID` header |
| **Pass Criteria** | Trace ID is auto-generated |

### TC-API-007-2: Custom Trace ID

| Field | Value |
|-------|-------|
| **Endpoint** | Any endpoint |
| **Input** | Request with `X-Trace-ID: my-custom-trace` header |
| **Expected Output** | Response contains the same trace ID |
| **Pass Criteria** | Custom trace ID is preserved |
