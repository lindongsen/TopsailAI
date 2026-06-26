---
status: superseded
priority: high
related_files:
  - internal/api/handlers/group_member.go
  - internal/api/handlers/group_member_test.go
  - cmd/cli/commands.go
  - cmd/cli/api.go
  - cmd/cli/commands_test.go
  - docs/API.md
superseded_by: issue-self-join-loophole-member-id-match.md
---

# Self-Join Public/Private Group Rejected After Permission Fix

## Summary

After fixing `issue-non-member-can-self-join-any-group`, non-owner/non-admin self-join requests for public and private groups were rejected with HTTP 403. The root cause was an overly strict server-side guard.

This issue was initially fixed by relaxing the guard to tolerate self-join requests that included `member_id` and `member_type` matching the caller. That fix was later found to create a permission loophole (see `issue-self-join-loophole-member-id-match.md`) and has been superseded by a strict contract: non-owner/non-admin self-join requests must **not** include `member_id` or `member_type`.

## Steps to Reproduce (Original)

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

## Expected Behavior (Final)

- Non-owner/non-admin users should be able to self-join public groups by sending a request **without** `member_id`/`member_type`.
- Non-owner/non-admin users should be able to self-join private groups with the correct `group_key` by sending a request **without** `member_id`/`member_type`.
- Any self-join request that includes `member_id` or `member_type` must be rejected with `403 Forbidden`, even if the values match the caller.

## Actual Behavior (Original)

All self-join attempts by non-owner/non-admin users returned HTTP 403.

## Root Cause (Original)

The permission fix for `issue-non-member-can-self-join-any-group` introduced a server-side guard that treated any self-join request containing `member_id` or `member_type` as an attempt to add a different member. Some callers supplied `member_type=user` or `member_id=<caller_id>` for self-joins, causing legitimate self-joins to be rejected.

## Why the Initial Fix Was Superseded

Relaxing the guard to accept matching `member_id`/`member_type` created a loophole: any authenticated user could join any public group, or bypass the private-group `group_key` check, by supplying their own `member_id` and `member_type=user`. The correct contract is to require self-join requests to omit both fields entirely.

## Final Fix

See `issue-self-join-loophole-member-id-match.md` for the final fix, tests, and verification.

## Notes

- This issue file is kept for historical context.
- The current server behavior follows the strict self-join contract documented in `docs/API.md`.
