---
status: fixed
severity: medium
component: api/handlers/group
fixed_by: AIMember.km3-programmer
fixed_at: 2026-06-21
---

# Group API Response Missing `creator_id` and `owner_id`

## Summary
The `POST /api/v1/groups` and `GET /api/v1/groups/:group_id` endpoints did not include `creator_id` and `owner_id` in the JSON response, even though both fields are documented in `docs/API.md` and are stored in the database.

## Root Cause
`internal/api/handlers/group.go` defined a `GroupResponse` DTO that omitted `CreatorID` and `OwnerID`, and the `toGroupResponse` helper did not copy those fields from the `models.Group` persistence object.

## Fix
- Added `CreatorID` and `OwnerID` fields to `GroupResponse` with JSON tags `creator_id` and `owner_id`.
- Updated `toGroupResponse` to populate the new fields from the model.
- Updated unit tests to assert these fields are present in create/list/get responses.

## Files Changed
- `internal/api/handlers/group.go`
- `internal/api/handlers/group_test.go`

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./internal/api/handlers/ -run TestGroup -v   # PASS
go test ./...                                         # PASS
make build                                            # PASS
```

## Impact
All group endpoints (create, list, get, update) now return `creator_id` and `owner_id` as documented. Manual cluster testing can resume from `TestCase_manual_cli_cluster.md` step CLUSTER-005.
