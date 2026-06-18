---
status: done
priority: medium
created_at: 2026-06-18
created_by: AIMember.km2-reviewer
related_files:
  - /TopsailAI/src/topsailai_server/agent_community/internal/api/handlers/group.go
---

# Hard-coded table names in `ListGroups`

## What was found

In `/TopsailAI/src/topsailai_server/agent_community/internal/api/handlers/group.go`, the `ListGroups` handler built a GORM query using literal table names:

```go
query = query.Joins("JOIN group_member ON group_member.group_id = groups.group_id").
    Where("group_member.member_id = ?", authCtx.Account.AccountID)
```

and

```go
orderClause := fmt.Sprintf("groups.%s %s", sortKey, orderBy)
```

The literals `group_member` and `groups` were hard-coded instead of using the existing `TableName()` methods defined in `internal/models/`.

## Why it matters

- **Maintainability**: Table names should be defined in one place (`models.*.TableName()`). If a table is renamed or the naming convention changes, every hard-coded literal must be hunted down.
- **Consistency**: The rest of the project relies on GORM model structs and `TableName()` methods. Raw SQL fragments that embed table names break that convention.
- **Refactoring safety**: Centralized table names make future schema changes less error-prone.

## Fix applied

Refactored `ListGroups` to use:

```go
models.Group{}.TableName()       // returns "groups"
models.GroupMember{}.TableName() // returns "group_member"
```

The JOIN, WHERE, and ORDER BY clauses now construct table names dynamically from the model methods.

## Verification

- `go build ./cmd/server` passed.
- `go test ./internal/api/handlers/...` passed.

## Related issue

A follow-up review found additional hard-coded table names / column filters in other packages. See:
`/TopsailAI/src/topsailai_server/agent_community/issues/issue-hardcoded-table-names-follow-up.md`
