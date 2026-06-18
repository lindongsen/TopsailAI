---
title: CLI auto-join uses account/member names containing spaces, violating member_name validation
status: open
priority: high
---

# Issue: CLI auto-join member_name invalid

## Description

When a user runs `/group:enter` and is not already a member, the CLI auto-joins them using `state.userName` or `state.memberName` as the `member_name`. If these names contain spaces (e.g., "Test User" or the default "CLI User"), the server rejects the request with:

```
invalid member_name: must contain only alphanumeric characters, hyphens, and underscores
```

## Steps to Reproduce

1. Create an account with `account_name` containing a space (e.g., "Test User").
2. Log in as that user via `/login`.
3. Run `/group:create` to create a group.
4. Run `/group:enter <group_id>`.
5. Observe the auto-join fails with HTTP 400.

## Expected Behavior

The CLI should derive a valid `member_name` (e.g., by replacing spaces with underscores or falling back to the `member_id`) when auto-joining a group.

## Affected Code

- `cmd/cli/commands.go` — `resolveOrJoinMember()` uses `state.userName` / `state.memberName` directly.
- `cmd/cli/main.go` — default `member-name` is "CLI User", which itself contains a space.

## Fix Suggestion

1. In `resolveOrJoinMember`, sanitize the candidate `memberName` to replace spaces and other invalid characters with underscores.
2. Ensure the sanitized name is non-empty; fall back to `memberID` if necessary.
3. Consider changing the default `--member-name` to a space-free value such as "cli-user".

## Related

- ORIGIN.md: `member_name` must contain only alphanumeric characters, hyphens, and underscores.
- API.md: Group member endpoints validate `member_name`.
