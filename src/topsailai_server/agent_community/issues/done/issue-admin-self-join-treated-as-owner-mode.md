---
status: resolved
priority: medium
component: api/group_member
resolved_at: 2026-06-26
---

# Issue: Admin self-join is treated as owner/admin mode

## Summary

The ACS API documentation states that "Any authenticated account can self-join a public group" and that self-join requests must not supply `member_id` or `member_type`. However, when an `admin` account attempted to self-join a public group without supplying `member_id`, the server rejected the request with `member_id is required` because admins were always routed to owner/admin mode.

## Steps to Reproduce

1. Start ACS server and obtain the default admin API key.
2. Create a public group (no `group_key`).
3. Attempt to self-join the group as the admin account:
   ```bash
   python group_lifecycle.py join-member <group_id> --self-join --name "Admin_User"
   ```

## Expected Behavior

The admin account should be able to self-join the public group with `member_id` derived from the authenticated account, just like any other account.

## Actual Behavior (Before Fix)

The server returned:

```
ERROR __main__ member_id is required
```

## Root Cause

In `internal/api/handlers/group_member.go::JoinGroup`, the authorization mode was determined as:

```go
ownerMode := false
if isAdmin(authCtx) {
    ownerMode = true
} else {
    isOwner, err := isGroupOwner(...)
    ownerMode = isOwner
}
```

Admins were unconditionally placed in `ownerMode`, so the subsequent validation required `member_id`, `member_name`, and `member_type` even when the caller intended a self-join.

## Fix

Changed mode detection to be **presence-based**:

- If the request body does **not** contain `member_id` or `member_type`, treat it as a **self-join** regardless of caller role.
- If `member_id` or `member_type` is supplied, determine owner/admin mode by role (`admin`) or group ownership.
- Admin callers can still add members to any group by providing `member_id`/`member_type`.

Files changed:
- `internal/api/handlers/group_member.go`
- `internal/api/handlers/group_member_test.go`

Tests added:
- `TestJoinGroup_AdminSelfJoinPublicGroup` — verifies an admin can self-join a public group without `member_id`/`member_type`.
- `TestJoinGroup_AdminCanStillAddMember` — verifies admin owner/admin mode still works when `member_id`/`member_type` are provided.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/...
```

Result: `ok github.com/topsailai/agent-community/internal/api/handlers 3.014s`

## Impact

- Admin accounts can now use the documented self-join flow.
- The `group_lifecycle.py --self-join` command works for admin callers.
- Behavior now aligns with `docs/API.md`.

## Related Files

- `internal/api/handlers/group_member.go`
- `internal/api/handlers/group_member_test.go`
- `docs/API.md`
- `skills/agent_community_client/scripts/group_lifecycle.py`
