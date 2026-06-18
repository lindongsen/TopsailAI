---
maintainer: AI
---
# CLI Permission and Sender-ID Verification

## Problem Statement

The ACS CLI terminal and server API currently allow behavior that violates the product requirements:

1. **Message sender can be spoofed.** The `POST /api/v1/groups/:group_id/messages` endpoint accepts `sender_id` and `sender_type` from the client. The CLI sends these fields explicitly, so any caller can impersonate another member.
2. **Group listing is not scoped to membership.** `GET /api/v1/groups` returns every group in the database, regardless of whether the caller has joined them.
3. **CLI auto-joins groups on enter.** `/group:enter` silently adds the current user as a member if they are not already one, bypassing the requirement that a user can only enter groups they have joined.
4. **PS1 does not show the user id.** The prompt shows the user name and role, but not the account id, making it impossible to verify the authenticated identity visually.

## Required Changes

### Server: `internal/api/handlers/message.go`

- Remove `sender_id` and `sender_type` from `CreateMessageRequest`.
- In `CreateMessage`, derive `sender_id` from `middleware.GetAuthContext(c).Account.AccountID`.
- Set `sender_type` to `models.MemberTypeUser`.
- Keep the existing membership validation: the derived sender must be a member of the target group.
- Update audit log detail if needed.

### Server: `internal/api/handlers/group.go`

- In `ListGroups`, for non-admin callers, join `group_member` and filter results to groups where `group_member.member_id = auth.Account.AccountID`.
- Admin callers may continue to list all groups.

### CLI: `cmd/cli/display.go`

- Update `ps1Normal` and `ps1Chat` to accept and render the authenticated user id alongside the user name and role.

### CLI: `cmd/cli/commands.go`

- Update all prompt call sites to pass the user id.
- Replace the auto-join behavior in `group:enter` with a strict membership check. If the current user is not a member of the group, print an error and return to the normal prompt.

### CLI: `cmd/cli/api.go` and `cmd/cli/chat.go`

- Remove `sender_id` and `sender_type` from the `SendMessage` request payload.
- Update `SendChatMessage` to call the new `SendMessage` signature.

## Acceptance Criteria

- [x] `go build ./cmd/server` and `go build ./cmd/cli` succeed.
- [x] `go test ./internal/api/handlers/...` passes after updating tests.
- [x] CLI PS1 shows `acs@{userName}({userId})[{role}]: ` in normal mode and `acs@{userName}({userId})[{role}]:{groupId}# ` in chat mode.
- [x] `group:list` in the CLI only displays groups where the current user is a member.
- [x] `group:enter` rejects a group id when the current user is not a member and does not add the user.
- [x] Sending a message in a group stores `sender_id` equal to the authenticated account id and `sender_type=user`, even if the client omits or changes sender fields.

## Resolution

### Files Modified

- `cmd/cli/display.go` — `ps1Normal` and `ps1Chat` now include the authenticated user id.
- `cmd/cli/main.go` — prompt/banner call sites updated to pass the user id.
- `cmd/cli/commands.go` — `updateAuthState`, `restorePrompt`, `handleAccountMe`, and `handleGroupEnter` updated; auto-join replaced with strict membership check.
- `cmd/cli/chat.go` — chat prompt setup updated to pass the user id; `SendChatMessage` no longer sends sender fields.
- `cmd/cli/api.go` — `SendMessage` request payload no longer contains `sender_id`/`sender_type`.
- `internal/api/handlers/message.go` — `CreateMessageRequest` no longer accepts `sender_id`/`sender_type`; `CreateMessage` derives them from the authenticated account.
- `internal/api/handlers/group.go` — `ListGroups` filters by membership for non-admin callers.

### Verification Results

- **PS1**: Initial prompt rendered as `acs@System Admin(acc-f835c603d42d43869805c6cb6fc6ea49)[admin]: `; chat prompt rendered as `acs@System Admin(acc-f835c603d42d43869805c6cb6fc6ea49):{groupId}# `.
- **group:list**: Empty before creating/joining groups; showed only created groups for admin; non-admin users saw only groups they had joined.
- **group:enter**: Rejected with `failed to enter group: you are not a member...` when the current user was not a member; succeeded after explicit API join.
- **sender_id derivation**: Messages created via CLI had `sender_id` equal to the authenticated account id and `sender_type=user`, even when the request body omitted sender fields.
- **Non-admin isolation**: A regular user could not list or enter an unjoined group, and messages sent by that user carried the correct sender id.

### Date of Resolution

2026-06-18
