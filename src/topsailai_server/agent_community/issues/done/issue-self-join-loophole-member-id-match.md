---
status: fixed
related_files:
  - internal/api/handlers/group_member.go
  - internal/api/handlers/group_member_test.go
  - docs/API.md
---

# Self-Join Permission Loophole via Matching member_id/member_type

## Problem

A previous fix for the self-join public-group rejection issue relaxed the
server-side guard so that a non-owner/non-admin self-join request was accepted
when it included `member_id` equal to the caller's `account_id` and
`member_type` equal to `user`. This created a permission loophole:

- Any authenticated user could join any public group without owner approval by
  simply supplying their own `member_id` and `member_type=user`.
- Any authenticated user could bypass the private-group `group_key` check by
  supplying their own `member_id` and `member_type=user` along with any key
  (or no key at all, depending on code path), because the request was treated
  as a tolerant self-join rather than an owner/admin member-add attempt.

This violated the documented contract that only group owners/admins may add
members, and that private groups require the correct `group_key` for self-join.

## Root Cause

The server-side `JoinGroup` handler in
`internal/api/handlers/group_member.go` used the following logic for
non-owner/non-admin requests:

```go
if req.MemberID != "" && req.MemberID != authCtx.Account.AccountID {
    // reject
}
if req.MemberType != "" && req.MemberType != string(models.MemberTypeUser) {
    // reject
}
```

This allowed matching values through. The intent was backward compatibility for
clients that sent the caller's own ID and `user` type, but it conflated the
self-join code path with the owner/admin add-member code path. Because the
private-group key check only ran inside the self-join branch, a request with
matching `member_id`/`member_type` could potentially skip key validation and
still be accepted as a self-join.

## Fix

Reverted the guard to the strict contract:

- Owner/admin requests **must** supply `member_id`, `member_name`, and
  `member_type`.
- Non-owner/non-admin self-join requests **must not** supply `member_id` or
  `member_type`. If either field is present, the request is rejected with
  `403 Forbidden` before any group-key or membership checks.
- Public groups allow self-join without a key.
- Private groups require the correct `group_key` for self-join.

The updated guard in `internal/api/handlers/group_member.go`:

```go
} else {
    // Self-join mode. Non-owners/admins may not supply member_id or
    // member_type; those fields are reserved for owner/admin member addition.
    if req.MemberID != "" {
        writeErrorResponse(c, http.StatusForbidden, "self-join cannot specify member_id", traceID)
        return
    }
    if req.MemberType != "" {
        writeErrorResponse(c, http.StatusForbidden, "self-join cannot specify member_type", traceID)
        return
    }
    // ... group_key and duplicate checks ...
}
```

`docs/API.md` was updated to state that self-join requests must not include
`member_id` or `member_type`, and that any such request is rejected with
`403 Forbidden`.

## Tests

Updated and added tests in `internal/api/handlers/group_member_test.go`:

- Owner/admin add member with `member_id`/`member_type`: `201 Created`.
- Non-owner self-join public group without `member_id`/`member_type`: `201 Created`.
- Non-owner self-join public group with matching `member_id`/`member_type`: `403 Forbidden`.
- Non-owner self-join public group with mismatched `member_id`: `403 Forbidden`.
- Non-owner self-join public group with non-user `member_type`: `403 Forbidden`.
- Non-owner self-join private group with correct key and no `member_id`/`member_type`: `201 Created`.
- Non-owner self-join private group with correct key but with `member_id`/`member_type`: `403 Forbidden`.
- Non-owner self-join private group with wrong key: `403 Forbidden`.
- Edge cases: matching `member_id` only, matching `member_type` only,
  mismatched `member_id` only, mismatched `member_type` only — all `403 Forbidden`.

## Verification

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/... -count=1
go test ./cmd/cli/... -count=1
go test ./... -count=1
```

All tests pass.

## Notes

The CLI `/group:join` command already omitted `member_id` and `member_type`
from self-join requests, so no CLI code change was required. The CLI unit tests
already assert this strict contract.
