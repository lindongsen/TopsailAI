---
maintainer: AI
status: open
related_test_plan: docs/cases/TestCase_integration_group_key.md
related_test_file: tests/integration/test_group_key_api.py
---

# Issue: Private Group Self-Join with `group_key` Is Not Implemented

## Summary
The ACS API does not expose a self-join endpoint that allows a user to join a private group by supplying the correct `group_key`. The only way to add a member to a private group is for the group owner or an admin to call `POST /api/v1/groups/{group_id}/members`.

## Observed Behavior
- `POST /api/v1/groups/{group_id}/members` accepts `member_id`, `member_name`, `member_type`, and `member_interface`, but **ignores any `group_key` field** in the request body.
- A non-owner/non-admin user receives `403 Forbidden` when attempting to add a member, even if the request body contains the correct plaintext `group_key`.
- There is no dedicated endpoint (e.g., `POST /api/v1/groups/{group_id}/join`) for self-joining with a key.

## Expected Behavior (per Test Plan)
`TestCase_integration_group_key.md` describes a scenario where a user can join a private group by providing the correct `group_key`, and is denied when the key is incorrect or missing.

## Actual Behavior
- Only group owners and admins can add members.
- The `group_key` is never used as an authorization credential for joining.

## Impact
- The test plan item **INT-GK-012** cannot be implemented as originally specified.
- The integration test file documents this behavior with `test_join_private_group_with_key_in_body_is_not_supported` and `test_owner_can_add_member_to_private_group`.

## Proposed Resolution
1. Decide whether self-join with `group_key` is a required feature.
2. If required, implement either:
   - A new endpoint such as `POST /api/v1/groups/{group_id}/members/join` that accepts `group_key`, or
   - Allow `POST /api/v1/groups/{group_id}/members` to accept `group_key` in the body and authorize self-join when the key matches.
3. If not required, update `docs/API.md` and `docs/cases/TestCase_integration_group_key.md` to remove the self-join scenario and clarify that only owners/admins can add members.

## Test Coverage
- `tests/integration/test_group_key_api.py::TestGroupKeyJoinBehavior::test_join_private_group_without_key_is_rejected`
- `tests/integration/test_group_key_api.py::TestGroupKeyJoinBehavior::test_join_private_group_with_key_in_body_is_not_supported`
- `tests/integration/test_group_key_api.py::TestGroupKeyJoinBehavior::test_owner_can_add_member_to_private_group`

## Related Files
- `docs/API.md` (Group Member Endpoints)
- `docs/cases/TestCase_integration_group_key.md`
- `tests/integration/test_group_key_api.py`
