---
status: open
severity: medium
component: api
---

# Self-join `member_name` is not sanitized when defaulting to account name

## Summary
When a user self-joins a group without providing `member_name`, the handler falls back to `authCtx.Account.AccountName`. Unlike the group creator member path (`buildCreatorMember`), this fallback value is not passed through `sanitizeMemberName`, so characters outside the allowed set (alphanumeric, hyphens, underscores) can be stored in `member_name`.

## Affected file
- `internal/api/handlers/group_member.go` (`JoinGroup`)

## Expected behavior
All stored `member_name` values must match `^[a-zA-Z0-9_-]+$` (per `memberNameRegex`). When a self-joining user does not supply `member_name`, the account name should be sanitized the same way as `buildCreatorMember` sanitizes it.

## Actual behavior
In self-join mode:
```go
if req.MemberName != "" {
    memberName = req.MemberName
} else {
    memberName = authCtx.Account.AccountName
}
```
The `authCtx.Account.AccountName` value is used directly. If the account name contains spaces or special characters, the resulting `member_name` violates the regex and may cause downstream issues (e.g., mention matching, NATS subjects).

## Reproduction Steps
1. Create an account with `account_name` containing spaces or special characters, e.g., "Alice Smith".
2. Start the CLI or use curl with that account's credentials.
3. Self-join a public group without providing `member_name`:
   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
        -X POST http://localhost:7370/api/v1/groups/<group_id>/members \
        -d '{"member_description":"self join"}'
   ```
4. Observe that the created member has `member_name` = "Alice Smith" (with a space) instead of "Alice_Smith".

## Suggested fix
Apply `sanitizeMemberName` to the fallback account name in self-join mode:
```go
if req.MemberName != "" {
    memberName = req.MemberName
} else {
    memberName = sanitizeMemberName(authCtx.Account.AccountName)
}
```
`sanitizeMemberName` is already defined in `group.go` and should be moved to a shared location or duplicated in `group_member.go` if package-private sharing is not possible.

## Verification
- `go test ./internal/api/handlers/...` passes.
- Unit test: self-join with empty `member_name` and account name "Alice Smith" stores "Alice_Smith".
- Unit test: self-join with explicit invalid `member_name` still returns 400 (existing behavior).

## References
- `internal/api/handlers/group_member.go` `JoinGroup`
- `internal/api/handlers/group.go` `buildCreatorMember` / `sanitizeMemberName`
- `memberNameRegex` in `group_member.go`

## Resolution

- **Status:** resolved
- **Source files changed:**
  - `internal/api/handlers/group_member.go`
  - `internal/api/handlers/group_member_test.go`
- **Key fix:**
  - In `JoinGroup`, the self-join fallback to `authCtx.Account.AccountName` is now passed through `sanitizeMemberName()` before being stored.
  - Added unit tests covering sanitized fallback, empty account name defaulting to `"user"`, valid provided `member_name` preserved, and invalid provided `member_name` rejected with 400.
- **Test verification:**
  - `go test ./internal/api/handlers/...` passes.
  - Full suite `go test ./...` passes.
