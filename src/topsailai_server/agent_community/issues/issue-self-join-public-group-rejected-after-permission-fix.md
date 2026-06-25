---
status: fixed
priority: high
related_files:
  - internal/api/handlers/group_member.go
  - internal/api/handlers/group_member_test.go
  - cmd/cli/commands.go
  - cmd/cli/api.go
  - cmd/cli/commands_test.go
  - docs/API.md
---

# Self-Join Public/Private Group Rejected After Permission Fix

## Summary

After fixing `issue-non-member-can-self-join-any-group`, non-owner/non-admin self-join requests for public and private groups were rejected with HTTP 403. The root cause was a combination of:

1. The server-side guard was too strict: it rejected any self-join request containing `member_id` or `member_type`, even when the values matched the caller.
2. The CLI's `/group:join` command continued to send `member_id` and `member_type` in the request body for self-join attempts.

## Steps to Reproduce

1. Start the ACS server.
2. Create a public group as User A.
3. As User B (not a member), run the CLI command:
   ```
   /group:join group-id=<group_id>
   ```
4. Observe the response:
   ```
   access denied. Your role does not have permission. (trace: HTTP 403: only group owners and admins can add members)
   ```

## Expected Behavior

- Non-owner/non-admin users should be able to self-join public groups.
- Non-owner/non-admin users should be able to self-join private groups with the correct `group_key`.
- The CLI should send a self-join request that the server accepts.

## Actual Behavior

All self-join attempts by non-owner/non-admin users returned HTTP 403.

## Root Cause

The permission fix for `issue-non-member-can-self-join-any-group` introduced a guard that treated any self-join request with `member_id` or `member_type` as an attempt to add a different member. Because the CLI sent both fields, legitimate self-joins were rejected.

## Fix

1. **Server (`internal/api/handlers/group_member.go`)**: Relaxed the self-join guard to allow `member_id` and `member_type` when they match the caller (`member_id == account_id` and `member_type == user`). Any mismatch is still rejected with `403 Forbidden`.
2. **CLI (`cmd/cli/api.go`, `cmd/cli/commands.go`)**: The `JoinGroup` API client method and `handleGroupJoin` command already send self-join requests without `member_id` and `member_type`; no CLI code change was required after verifying the contract.
3. **Tests (`cmd/cli/commands_test.go`)**: Updated `TestHandleGroupJoin` to assert that self-join requests do **not** include `member_id` or `member_type`.
4. **Tests (`internal/api/handlers/group_member_test.go`)**: Existing `TestGroupMemberHandler_Join_UserOwnGroupOnly` already covers:
   - Owner adding a member to their own group.
   - Non-owner self-joining a public group without `member_id`/`member_type`.
   - Non-owner self-joining a public group with matching `member_id`/`member_type`.
   - Non-owner self-joining with mismatched `member_id`/`member_type` rejected.
   - Non-owner self-joining a private group without key rejected.
   - Non-owner self-joining a private group with correct key.
   - Non-owner self-joining a private group with wrong key rejected.
5. **Documentation (`docs/API.md`)**: Updated the Join Group section to describe the tolerant self-join contract.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/... ./internal/api/handlers/... -count=1
```

Result: PASS.

## Notes

- The error message "only group owners and admins can add members" was from the strict guard and is no longer returned for valid self-joins.
- The server now derives `member_id` and `member_type` from the authenticated account for self-joins, matching the documented API contract.
