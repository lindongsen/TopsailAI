---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Role-Based Access Control

## Overview

Verify that role hierarchy (`admin > manager > user`) is enforced across accounts, API keys, groups, members, and messages.

---

## TC-INT-RBAC-001: Admin Can Create Any Role Account

### Objective

Verify admin can create `admin`, `manager`, and `user` accounts.

### Steps

1. Authenticate as admin.
2. Create accounts with each role.

### Expected Output

Status: 201 for all roles.

### Pass Criteria

- Admin can create accounts of any role.

---

## TC-INT-RBAC-002: Manager Can Only Create User Accounts

### Objective

Verify manager can create `user` accounts but not `admin` or `manager`.

### Steps

1. Authenticate as manager.
2. Attempt to create `user`, `manager`, and `admin` accounts.

### Expected Output

- `user`: 201
- `manager`: 403
- `admin`: 403

### Pass Criteria

- Manager creation is restricted to `user` role.

---

## TC-INT-RBAC-003: User Cannot Create Accounts

### Objective

Verify user role cannot create accounts.

### Steps

1. Authenticate as user.
2. Send `POST /api/v1/accounts`.

### Expected Output

Status: 403

### Pass Criteria

- User is forbidden from account creation.

---

## TC-INT-RBAC-004: Manager Cannot Create API Keys

### Objective

Verify manager role cannot create API keys for any account.

### Steps

1. Authenticate as manager.
2. Send `POST /api/v1/accounts/{manager_account_id}/api-keys`.

### Expected Output

Status: 403

### Pass Criteria

- Manager cannot create API keys.

---

## TC-INT-RBAC-005: User Can Create Own API Key

### Objective

Verify user can create API keys only for themselves and with role ≤ `user`.

### Steps

1. Authenticate as user (session or API key).
2. Create API key for own account with `role=user`.

### Expected Output

Status: 201

### Pass Criteria

- User can create own user-level API key.

---

## TC-INT-RBAC-006: User Cannot Create API Key for Other Account

### Objective

Verify user cannot create API keys for other accounts.

### Steps

1. Authenticate as user A.
2. Attempt to create API key for user B.

### Expected Output

Status: 403

### Pass Criteria

- Cross-account API key creation is forbidden.

---

## TC-INT-RBAC-007: API Key Role Cannot Exceed Owner Role

### Objective

Verify an API key's role is constrained by the owning account's role.

### Steps

1. Create a `user` account.
2. Attempt to create `manager` or `admin` API key for that account.

### Expected Output

Status: 403

### Pass Criteria

- API key role is rejected if it exceeds owner role.

---

## TC-INT-RBAC-008: Admin Can Access Any Group

### Objective

Verify admin can list/get/update/delete any group.

### Steps

1. Create a group as user A.
2. As admin, perform GET/PUT/DELETE on that group.

### Expected Output

- GET: 200
- PUT: 200
- DELETE: 204

### Pass Criteria

- Admin has full group access regardless of ownership.

---

## TC-INT-RBAC-009: User Can Only Access Own Groups

### Objective

Verify user can only list/get groups where they are a member.

### Steps

1. Create a group as user A and add user B as member.
2. As user B, list groups and GET the group.
3. As user C (not a member), attempt to GET the group.

### Expected Output

- User B: 200
- User C: 403 or 404

### Pass Criteria

- Non-member user is denied access.

---

## TC-INT-RBAC-010: Group Owner Can Update and Delete Own Group

### Objective

Verify group owner (creator) can update and delete their group.

### Steps

1. Create a group as user A.
2. As user A, update and delete the group.

### Expected Output

- PUT: 200
- DELETE: 204

### Pass Criteria

- Owner has full control over own group.

---

## TC-INT-RBAC-011: Non-Owner User Cannot Delete Others' Groups

### Objective

Verify a user cannot delete a group they do not own.

### Steps

1. Create a group as user A.
2. As user B (member but not owner), attempt DELETE.

### Expected Output

Status: 403

### Pass Criteria

- Non-owner deletion is forbidden.

---

## TC-INT-RBAC-012: Admin Can Manage Any Group Members

### Objective

Verify admin can add/remove/update members in any group.

### Steps

1. Create a group as user A.
2. As admin, add and remove members.

### Expected Output

- POST member: 201
- DELETE member: 204

### Pass Criteria

- Admin has full member management access.

---

## TC-INT-RBAC-013: Group Owner Can Add Members

### Objective

Verify group owner can add members to their group.

### Steps

1. Create a group as user A.
2. As user A, add user B as member.

### Expected Output

Status: 201

### Pass Criteria

- Owner can add members.

---

## TC-INT-RBAC-014: Non-Member User Cannot List Members

### Objective

Verify a user cannot list members of a group they are not in.

### Steps

1. Create a group as user A.
2. As user B (not a member), send `GET /groups/{group_id}/members`.

### Expected Output

Status: 403 or 404

### Pass Criteria

- Non-member is denied.

---

## TC-INT-RBAC-015: User Can Update Own Member Record

### Objective

Verify a user can update their own member record in a group.

### Steps

1. Add user A to a group.
2. As user A, update member name/status.

### Expected Output

Status: 200

### Pass Criteria

- User can update own member record.

---

## TC-INT-RBAC-016: User Cannot Update Others' Member Records

### Objective

Verify a user cannot update another member's record.

### Steps

1. Add users A and B to a group.
2. As user A, attempt to update user B's member record.

### Expected Output

Status: 403

### Pass Criteria

- Cross-member update is forbidden.

---

## TC-INT-RBAC-017: User Can Delete Own Member Record

### Objective

Verify a user can leave a group by deleting their own member record.

### Steps

1. Add user A to a group.
2. As user A, delete own member record.

### Expected Output

Status: 204

### Pass Criteria

- User can leave group.

---

## TC-INT-RBAC-018: User Can Send Messages to Member Groups

### Objective

Verify user can send messages to groups where they are a member.

### Steps

1. Add user A as member of a group.
2. As user A, create a message.

### Expected Output

Status: 201

### Pass Criteria

- Member can send messages.

---

## TC-INT-RBAC-019: Non-Member User Cannot Send Messages

### Objective

Verify a user cannot send messages to a group they are not in.

### Steps

1. Create a group as user A.
2. As user B (not a member), attempt to create a message.

### Expected Output

Status: 403 or 404

### Pass Criteria

- Non-member message creation is denied.

---

## TC-INT-RBAC-020: User Can Update Own Messages

### Objective

Verify a user can edit messages they sent.

### Steps

1. As user A, create a message.
2. As user A, update the message.

### Expected Output

Status: 200

### Pass Criteria

- Message owner can update.

---

## TC-INT-RBAC-021: User Cannot Update Others' Messages

### Objective

Verify a user cannot edit messages sent by others.

### Steps

1. As user A, create a message.
2. As user B, attempt to update the message.

### Expected Output

Status: 403

### Pass Criteria

- Non-owner update is forbidden.

---

## TC-INT-RBAC-022: User Can Delete Own Messages

### Objective

Verify a user can soft-delete their own messages.

### Steps

1. As user A, create a message.
2. As user A, delete the message.

### Expected Output

Status: 200 or 204

### Pass Criteria

- Message owner can delete.

---

## TC-INT-RBAC-023: User Cannot Delete Others' Messages

### Objective

Verify a user cannot delete messages sent by others.

### Steps

1. As user A, create a message.
2. As user B, attempt to delete the message.

### Expected Output

Status: 403

### Pass Criteria

- Non-owner deletion is forbidden.

---

## TC-INT-RBAC-024: Manager Can Query Accounts by ID and External ID

### Objective

Verify manager can query accounts but receives limited fields.

### Steps

1. Create a user account as admin.
2. As manager, GET `/api/v1/accounts/{account_id}` and `/api/v1/accounts?external_id=...`.

### Expected Output

Status: 200
- Response does NOT contain `login_password`, `login_session_key`, or API keys.

### Pass Criteria

- Manager query succeeds with limited fields.

---

## TC-INT-RBAC-025: Manager Can Create Login Session for User

### Objective

Verify manager can create a login session only for `user` role accounts.

### Steps

1. As manager, create a session for a user account.
2. As manager, attempt to create a session for an admin account.

### Expected Output

- User: 200
- Admin: 403

### Pass Criteria

- Manager session creation is restricted to users.

---

## TC-INT-RBAC-026: Manager Cannot Query API Keys or Login Secrets

### Objective

Verify manager cannot access sensitive account fields.

### Steps

1. As manager, GET `/api/v1/accounts/{account_id}`.
2. Verify response excludes `login_password`, `login_session_key`.

### Expected Output

- Fields are absent.

### Pass Criteria

- Sensitive fields are omitted for manager.

---

## TC-INT-RBAC-027: Admin Can Delete Any Account

### Objective

Verify admin can soft-delete any account.

### Steps

1. Create an account as manager or admin.
2. As admin, DELETE `/api/v1/accounts/{account_id}`.

### Expected Output

Status: 200

### Pass Criteria

- Admin can delete any account.

---

## TC-INT-RBAC-028: Manager and User Cannot Delete Accounts

### Objective

Verify non-admin roles cannot delete accounts.

### Steps

1. As manager, attempt to delete an account.
2. As user, attempt to delete an account.

### Expected Output

Status: 403

### Pass Criteria

- Only admin can delete accounts.

---

## TC-INT-RBAC-029: Authentication Priority

### Objective

Verify authentication priority: login_name/password > session key > API key.

### Steps

1. Send request with both valid API key and invalid session key.
2. Send request with valid session key and invalid API key.

### Expected Output

- Invalid session + valid API key: authenticated via API key.
- Valid session + invalid API key: authenticated via session key.

### Pass Criteria

- Priority order is respected.

---

## TC-INT-RBAC-030: Unauthenticated Requests Rejected

### Objective

Verify protected endpoints reject requests without credentials.

### Steps

1. Send `GET /api/v1/accounts/me` without authentication.

### Expected Output

Status: 401

### Pass Criteria

- Unauthenticated access is rejected.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_rbac.py -v
```

## Notes

- Tests require admin, manager, and multiple user API keys/sessions.
- Some endpoints may return 404 instead of 403 for non-existent or unauthorized resources; document actual behavior.
- Group ownership tests assume the creator becomes `owner_id`.
