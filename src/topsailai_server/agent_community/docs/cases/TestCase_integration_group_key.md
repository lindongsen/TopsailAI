---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Group Key & Privacy

## Overview

Verify that group secret keys are hashed, never returned in plaintext, and enforce access control for private groups.

---

## TC-INT-GK-001: Create Group with Secret Key

### Objective

Verify creating a group with `group_key` succeeds and the response does not leak the plaintext key.

### Steps

1. Authenticate as any valid account.
2. Send `POST /api/v1/groups` with `group_key` set.

### Input

```json
{
  "group_name": "Private Group",
  "group_context": "Secret discussion",
  "group_key": "my-secret-key"
}
```

### Expected Output

Status: 201
```json
{
  "data": {
    "group_id": "group-abc123",
    "group_name": "Private Group",
    "group_context": "Secret discussion",
    "group_key": "",
    "creator_id": "acc-abc123",
    "owner_id": "acc-abc123",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Group created successfully.
- `group_key` is empty or hashed, never the plaintext value.

---

## TC-INT-GK-002: Get Group Does Not Return Plaintext Key

### Objective

Verify `GET /api/v1/groups/{group_id}` never returns the plaintext `group_key`.

### Steps

1. Create a group with `group_key`.
2. Send `GET /api/v1/groups/{group_id}`.

### Expected Output

Status: 200
- `group_key` is empty or hashed.

### Pass Criteria

- Plaintext key is not exposed.

---

## TC-INT-GK-003: Update Group Key

### Objective

Verify updating `group_key` changes the key without leaking it.

### Steps

1. Create a group with an initial key.
2. Send `PUT /api/v1/groups/{group_id}` with a new `group_key`.
3. GET the group.

### Input

```json
{
  "group_key": "new-secret-key"
}
```

### Expected Output

- PUT: 200
- GET: `group_key` is empty or hashed, not "new-secret-key".

### Pass Criteria

- Key is updated and not leaked.

---

## TC-INT-GK-004: List Groups Does Not Return Plaintext Keys

### Objective

Verify group list endpoint does not expose plaintext keys.

### Steps

1. Create multiple groups with keys.
2. Send `GET /api/v1/groups`.

### Expected Output

Status: 200
- All returned groups have `group_key` empty or hashed.

### Pass Criteria

- No plaintext keys in list response.

---

## TC-INT-GK-005: Public Group Has Empty Group Key

### Objective

Verify groups created without `group_key` are public and return empty key.

### Steps

1. Create a group without `group_key`.
2. GET the group.

### Expected Output

Status: 201 / 200
- `group_key` is empty.

### Pass Criteria

- Public group is correctly identified by empty key.

---

## TC-INT-GK-006: Private Group Access Requires Key

### Objective

Verify joining a private group requires the correct `group_key`.

### Steps

1. Create a private group with `group_key`.
2. Attempt to join without providing the key.
3. Attempt to join with an incorrect key.
4. Attempt to join with the correct key.

### Expected Output

- No key: 403 or 400
- Incorrect key: 403 or 400
- Correct key: 201

### Pass Criteria

- Only correct key allows access.

---

## TC-INT-GK-007: Non-Member Cannot Access Private Group Messages

### Objective

Verify non-members cannot list messages in a private group.

### Steps

1. Create a private group and add user A.
2. As user B (not a member), attempt `GET /groups/{group_id}/messages`.

### Expected Output

Status: 403 or 404

### Pass Criteria

- Non-member is denied access to private group messages.

---

## TC-INT-GK-008: Group Owner Can Convert Public Group to Private

### Objective

Verify owner can add a `group_key` to an existing public group.

### Steps

1. Create a public group as user A.
2. As user A, send PUT with `group_key`.

### Expected Output

Status: 200
- Group now requires key for new members.

### Pass Criteria

- Owner can change group privacy.

---

## TC-INT-GK-009: Group Owner Can Convert Private Group to Public

### Objective

Verify owner can remove a `group_key` from an existing private group.

### Steps

1. Create a private group as user A.
2. As user A, send PUT with empty `group_key`.

### Expected Output

Status: 200
- `group_key` becomes empty.

### Pass Criteria

- Owner can make group public.

---

## TC-INT-GK-010: Admin Can Access Any Private Group

### Objective

Verify admin bypasses group key restrictions.

### Steps

1. Create a private group as user A.
2. As admin, GET group and list messages without providing key.

### Expected Output

Status: 200

### Pass Criteria

- Admin can access any group regardless of key.

---

## TC-INT-GK-011: Group Key Hash Comparison

### Objective

Verify the stored key is a hash (e.g., bcrypt) and not plaintext in the database.

### Steps

1. Create a group with `group_key`.
2. Query the database directly for `groups.group_key`.

### Expected Output

- `group_key` value is a hash, not the plaintext string.

### Pass Criteria

- Database does not store plaintext key.

---

## TC-INT-GK-012: Join Private Group with Key in Request Body

### Objective

Verify the join endpoint accepts `group_key` in the request body.

### Steps

1. Create a private group.
2. Send `POST /groups/{group_id}/members` with `group_key` in body.

### Input

```json
{
  "member_id": "user-002",
  "member_name": "Alice",
  "member_type": "user",
  "group_key": "my-secret-key"
}
```

### Expected Output

Status: 201

### Pass Criteria

- Correct key in body allows join.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_group_key.py -v
```

## Notes

- Exact API for providing `group_key` when joining may differ; verify against `docs/API.md`.
- If the API does not support key-based join, document the actual behavior and adjust tests.
- Database inspection requires PostgreSQL credentials.
