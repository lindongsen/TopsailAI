---
status: fixed
priority: critical
created: 2026-06-26
related_files:
  - internal/api/handlers/group_member.go
  - internal/api/handlers/group_member_test.go
  - docs/API.md
---

# Issue: Non-Member Can Self-Join Any Group by Supplying member_id

## Summary

A non-owner/non-admin authenticated user could send a `POST /api/v1/groups/{group_id}/members` request with a body containing `member_id` and `member_type` and have it interpreted as a self-join. For public groups this succeeded silently, and for private groups the request body shape made the operation look like an add-member attempt even though the server ignored the supplied `member_id`/`member_type`. This was ambiguous and allowed users to bypass the intended "only owners/admins can add members" rule by framing an add-member request as a self-join.

Additionally, when a non-owner/non-admin who was already a member tried to add another user, the API returned the misleading error `"already a member of this group"` instead of a permission-denied error.

## Steps to Reproduce

1. Create a group as User A (owner).
2. Do not add User B as a member.
3. As User B, send:
   ```bash
   POST /api/v1/groups/{group_id}/members
   Authorization: Bearer $USER_B_TOKEN
   Content-Type: application/json

   {"member_id":"some-id","member_name":"UserC","member_type":"user"}
   ```

## Expected Behavior

- HTTP `403 Forbidden` with a clear permission-denied message, because User B is not the owner/admin and is attempting to add a member.

## Actual Behavior

- HTTP `201 Created`. User B self-joined the group. The response showed `member_id` set to User B's own account ID because the server overrode the supplied value.
- In some cases a misleading `"already a member of this group"` error was returned.

## Root Cause

In `internal/api/handlers/group_member.go`, the `JoinGroup` handler entered "self-join mode" for any caller who was not an admin or group owner. It then silently ignored any `member_id`/`member_type` in the request body and treated the call as a self-join. There was no guard rejecting self-join requests that carried `member_id` or `member_type`, so the request shape was ambiguous and the permission boundary was unclear.

## Fix

Updated `internal/api/handlers/group_member.go` so that in self-join mode (non-owner/non-admin), the handler rejects any request that supplies `member_id` or `member_type` with:

```go
if req.MemberID != "" || req.MemberType != "" {
    writeErrorResponse(c, http.StatusForbidden, "only group owners and admins can add members", traceID)
    return
}
```

This makes the API unambiguous:
- Owner/admin: may add arbitrary members with `member_id`, `member_type`, etc.
- Non-owner/non-admin: may only self-join. Self-join must not include `member_id` or `member_type`. Public groups allow self-join without a key; private groups require the correct `group_key`.

The misleading `"already a member"` error is no longer returned for these permission-denial cases because the request is rejected before the existing-member check.

## Tests

Updated `internal/api/handlers/group_member_test.go` (`TestGroupMemberHandler_Join_UserOwnGroupOnly`) to cover:

- Owner adding a member to their own group: `201 Created`.
- Non-owner self-joining a public group without `member_id`/`member_type`: `201 Created`.
- Non-owner self-joining a public group with `member_id`/`member_type`: `403 Forbidden`.
- Non-owner self-joining a private group without `group_key`: `403 Forbidden`.
- Non-owner self-joining a private group with wrong `group_key`: `403 Forbidden`.
- Non-owner self-joining a private group with correct `group_key`: `201 Created`.

All handler tests pass:

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/ -count=1 -v
```

Result: PASS.

## Documentation

Updated `docs/API.md` Join Group section to state that self-join requests must not include `member_id` or `member_type` and that doing so is rejected with `403 Forbidden`.
