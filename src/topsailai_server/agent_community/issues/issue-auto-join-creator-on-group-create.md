---
status: done
labels:
  - feature
  - group
  - group_member
---

# Auto-Join Creator as User Member on Group Creation

## Problem

Previously, creating a group via `POST /api/v1/groups` only created the `group` record. The authenticated caller was not automatically added as a member, so a non-admin user could not see the group they just created when listing groups (`GET /api/v1/groups` filters by membership for non-admin callers). The CLI worked around this by calling `AddMember` after group creation.

## Solution

When any authenticated account creates a group, the caller is now automatically joined as a `group_member` with `member_type=user`, `member_id=account_id`, `member_name=account_name` (sanitized), and `member_status=online`, all inside the same database transaction as the group creation. A `group_member` create event is published to NATS after the transaction commits.

## Changes

### Group Handler (`internal/api/handlers/group.go`)

- `CreateGroup` now retrieves the authenticated caller via `middleware.GetAuthContext`.
- The creator member is built using the new `buildCreatorMember` helper and inserted inside the existing GORM transaction, before the optional manager-agent auto-join.
- After the transaction commits, `PublishGroupMemberCreate` is called for the creator member (in addition to the existing group and manager-agent events).
- Added `buildCreatorMember(groupID string, account *models.Account)` to construct the `group_member` record.
- Added `sanitizeMemberName(name, fallback string)` (local copy matching the CLI helper) to ensure `member_name` conforms to ACS validation rules.

## Behavior

- Any authenticated account (admin, manager, or user) that creates a group becomes a member of that group automatically.
- Member fields:
  - `group_id`: the newly created group's ID
  - `member_id`: the creator's `account_id`
  - `member_name`: sanitized `account_name`, falling back to `account_id` if sanitization yields an empty string
  - `member_type`: `user`
  - `member_status`: `online`
  - `member_interface`: `{}`
  - `last_read_message_id`: empty string
- If manager-agent auto-join is also configured, both the creator member and the manager-agent member are inserted atomically.
- If any insert fails, the entire transaction rolls back and the group is not created.
- NATS publish failures are logged as warnings and do not fail the HTTP request.

## Testing

- Unit tests and integration tests will be updated in a follow-up turn to assert creator auto-join behavior.

## Related Files

- `internal/api/handlers/group.go`
- `cmd/cli/commands.go` (client-side workaround to be removed in a follow-up turn)
- `internal/api/handlers/group_test.go` (tests to be updated in a follow-up turn)
- `tests/integration/test_api.py` (tests to be updated in a follow-up turn)
