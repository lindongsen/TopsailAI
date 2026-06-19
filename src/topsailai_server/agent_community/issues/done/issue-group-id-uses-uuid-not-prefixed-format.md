---
maintainer: AI
status: resolved
severity: medium
component: server
---
# Group IDs are generated as UUIDs instead of the documented `group-{id}` format

## Summary
The API documentation and `ORIGIN.md` specify that `group_id` values should use the format `group-{id}` (e.g., `group-abc123`). In the current implementation, groups are created with raw UUID values such as `60964b1f-3358-4c81-aa91-0345e4a9dad4`. This breaks format consistency across the API, CLI prompts, and documentation.

## Steps to Reproduce
1. Start the ACS server with any database backend.
2. Create a group via the API or CLI:
   ```bash
   curl -X POST http://localhost:17370/api/v1/groups \
     -H "Authorization: Bearer <token>" \
     -d '{"group_name":"Test"}'
   ```
3. Inspect the returned `group_id`.

## Expected Behavior
`group_id` should follow the documented format `group-{id}`, for example `group-60964b1f33584c81aa910345e4a9dad4` or a shorter generated slug.

## Actual Behavior
`group_id` is returned as a bare UUID:
```json
{"group_id":"60964b1f-3358-4c81-aa91-0345e4a9dad4"}
```

## Evidence
Database query from the manual test run:
```
0d6dca7a-8202-4926-8595-5af17ec8fe8a
1393cd0a-f6e0-4cc7-9cfc-49ef386f517a
481c2a45-778e-4499-9674-ba6b8224ee8a
60964b1f-3358-4c81-aa91-0345e4a9dad4
a670eda0-d1cc-4f8c-b173-43eeefc1814c
```

## Affected Code
- Server-side group creation ID generation.
- Possibly related format validation for `group_id` path parameters.

## Impact
- CLI prompts and message headers display UUIDs instead of readable `group-{id}` values.
- Scripts and tests that rely on the documented format may fail.
- Inconsistent with `account_id` (`acc-{id}`) and `api_key_id` (`ak-{id}`) formats.

## Fix

Resolved in `internal/models/group.go` and `internal/api/handlers/group.go`.

- Added `GenerateGroupID()` in `internal/models/group.go` which returns `group-` + a UUID with dashes removed, producing values like `group-60964b1f33584c81aa910345e4a9dad4`.
- Updated `Group.BeforeCreate` to auto-generate a group ID if one is not already set.
- Updated `GroupHandler.CreateGroup` to use `models.GenerateGroupID()` instead of `uuid.New().String()`.
- Added `CreatorID` and `OwnerID` fields to the `Group` model to align with the documented schema.

### Files Modified
- `internal/models/group.go`
- `internal/api/handlers/group.go`

### Verification
- `make build` succeeds.
- `go test ./...` passes.
