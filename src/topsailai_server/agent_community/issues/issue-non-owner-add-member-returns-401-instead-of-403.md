---
status: closed
severity: medium
related_plan: Manual_Test_Plan_02_Groups_and_Members.md
related_test_case: 2.7
---

# Issue: Non-owner member adding another member returns 401 instead of 403

## Summary

Initial manual test appeared to show HTTP `401 Unauthorized` when a non-owner member attempted to add another member. Upon closer inspection, the first request failed because `member_name` contained a space (`"User B Self Join"`), which is invalid per member name validation rules. After fixing the member name, the same request returned HTTP `403 Forbidden` with body `{"error":"already a member of this group"}`.

## Root Cause

Not a bug. The `POST /api/v1/groups/:group_id/members` endpoint has two modes:

1. **Owner/Admin mode** — caller is group owner or admin; can add any member.
2. **Self-join mode** — caller is not owner/admin; request is interpreted as an attempt to join the group themselves.

In self-join mode, the handler checks whether the caller is already a member. If yes, it returns `403 Forbidden` with `"already a member of this group"`. This is correct behavior: non-owner/non-admin members cannot add other members; they can only self-join once.

## Steps to Reproduce

1. Create a group as User A.
2. Have User B self-join the public group.
3. As User B, send:
   ```bash
   POST /api/v1/groups/{group_id}/members
   Authorization: Bearer {user_b_token}
   Content-Type: application/json

   {"member_id":"user-d","member_name":"UserD","member_type":"user"}
   ```

## Expected Behavior

- HTTP `403 Forbidden` because User B lacks permission to add members.

## Actual Behavior

- HTTP `403 Forbidden` with body `{"error":"already a member of this group"}`.

## Resolution

The HTTP status code matches the expected `403 Forbidden`. The error message is a consequence of the endpoint's self-join semantics and is acceptable. The test plan should note that non-owner add attempts are treated as self-joins and rejected with `403`.

## Environment

- ACS server: rebuilt binary at `/TopsailAI/src/topsailai_server/agent_community/bin/acs-server` (built 2026-06-26 04:52)
- API base: `http://localhost:7370`
- Group: `group-6295b07003024a43abca83fb734e7c17`
