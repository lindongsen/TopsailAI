---
status: open
priority: medium
created_at: 2026-06-18
created_by: AIMember.km2-reviewer
---

# Follow-up: hard-coded table names / raw SQL fragments across the codebase

## Background

While fixing hard-coded table names in `internal/api/handlers/group.go` (`ListGroups`), a broader review was performed on the Go codebase to find similar issues.

## Scope

Reviewed packages:

- `internal/api/handlers/*.go`
- `internal/services/*.go`
- `internal/db/*.go`
- `internal/nats/*.go`
- `cmd/server/main.go`

## Findings

### 1. `internal/nats/auto_trigger.go` — hard-coded `deleted_at IS NULL` filter

- **Lines**: 107, 187, 193
- **Code snippets**:
  - Line 107: `at.db.Where("deleted_at IS NULL").Find(&groups)`
  - Line 187: `at.db.Where("group_id = ? AND deleted_at IS NULL", group.GroupID).Find(&members)`
  - Line 193: `at.db.Where("group_id = ? AND deleted_at IS NULL AND is_deleted = ?", group.GroupID, false)`
- **Issue**: The `deleted_at IS NULL` check is a raw column literal. While GORM soft-delete usually handles this automatically, the explicit raw fragment is inconsistent with the model-driven approach.
- **Recommended fix**: Rely on GORM's built-in soft-delete behavior (`gorm.DeletedAt`) or, if the explicit check is required, reference the model struct field name/tag. If the intent is to include deleted records, use `Unscoped()` explicitly.
- **Severity**: low

### 2. `internal/db/db.go` — raw PostgreSQL catalog query

- **Line**: 97
- **Code snippet**: `query := "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)"`
- **Issue**: This is a PostgreSQL system-catalog query. `pg_database` is a Postgres system table and cannot be replaced by a project `TableName()`. It is acceptable as-is, but should be documented as a Postgres-specific raw query.
- **Recommended fix**: No code change required; optionally add a comment explaining that `pg_database` is a Postgres system catalog.
- **Severity**: low (informational)

### 3. `internal/db/db.go` — dynamic `CREATE DATABASE` statement

- **Line**: 107
- **Code snippet**: `createSQL := fmt.Sprintf("CREATE DATABASE %s", cfg.Name)`
- **Issue**: Database name is interpolated directly into SQL. This is a database name, not a project table name, so `TableName()` does not apply. However, it is a raw SQL construction and could be a SQL-injection risk if `cfg.Name` is ever user-controlled.
- **Recommended fix**: Validate/sanitize `cfg.Name` or use parameterized DDL if the driver supports it. At minimum, document that `cfg.Name` must come from trusted configuration.
- **Severity**: low

### 4. `internal/db/cleanup.go` — raw column names in cleanup conditions

- **Lines**: 86, 101
- **Code snippets**:
  - Line 86: `.Where("status IN ? AND create_at_ms < ?", ...)`
  - Line 101: `.Where("status = ? AND create_at_ms < ?", ...)`
- **Issue**: Column names `status` and `create_at_ms` are raw literals. These map to `models.AgentMessageProcessing` fields. While less critical than table names, centralizing column references would improve maintainability.
- **Recommended fix**: Use GORM model scopes or constants for column names if the project decides to enforce a no-raw-literal policy.
- **Severity**: low

### 5. `internal/api/handlers/group.go` — raw column names in time-range filters

- **Lines**: 305, 311
- **Code snippets**:
  - Line 305: `query = query.Where("create_at_ms BETWEEN ? AND ?", start, end)`
  - Line 311: `query = query.Where("update_at_ms BETWEEN ? AND ?", start, end)`
- **Issue**: Column names `create_at_ms` and `update_at_ms` are raw literals. They exist on `models.Group`.
- **Recommended fix**: If the project adopts a strict no-raw-column-name policy, introduce column-name constants or use struct tags to derive them. Otherwise acceptable.
- **Severity**: low

### 6. `internal/api/handlers/message.go` — raw column names

- **Lines**: 187, 264-281, 295
- **Code snippets**:
  - Line 187: `.Where("group_id = ?", msg.GroupID).Order("create_at_ms ASC")`
  - Lines 264-281: list filters on `group_id`, `create_at_ms`, `update_at_ms`, `processed_msg_id`
  - Line 295: `orderClause := sortKey + " " + orderBy`
- **Issue**: Raw column names in GORM `Where`/`Order` clauses. `sortKey` is user-controlled but validated against an allow-list, so injection risk is mitigated.
- **Recommended fix**: Consider centralizing common column names (e.g., `create_at_ms`, `update_at_ms`, `group_id`) as constants.
- **Severity**: low

### 7. `internal/api/handlers/group_member.go` — raw column names

- **Lines**: 201-228
- **Issue**: Similar to `message.go` and `group.go`: raw `group_id`, `create_at_ms`, `update_at_ms` literals in filters and ordering.
- **Severity**: low

### 8. `internal/services/account_service.go` — `ListAccounts` does not filter deleted accounts

- **Line**: 167-180
- **Code snippet**:
  ```go
  func (s *AccountService) ListAccounts(...) ([]models.Account, int64, error) {
      ...
      if err := s.db.WithContext(ctx).Model(&models.Account{}).Count(&total).Error; err != nil { ... }
      ...
      if err := s.db.WithContext(ctx).Order("create_at_ms desc").Offset(offset).Limit(limit).Find(&accounts).Error; err != nil { ... }
  }
  ```
- **Issue**: `models.Account` has a `status` field and a `delete_at_ms` soft-delete field. The service returns **all** accounts, including those with `status=deleted` and soft-deleted records (depending on GORM soft-delete behavior). This may leak deleted accounts to admin list endpoints.
- **Recommended fix**: Explicitly exclude `status = deleted` and/or rely on GORM soft-delete. Verify whether this is intentional for admin visibility.
- **Severity**: medium (potential data-leak / behavior bug)

### 9. `internal/services/api_key_service.go` — raw column names

- **Lines**: 183-253
- **Issue**: `owner_id`, `create_at_ms` used as raw literals in `Where`, `Order`, `Count`, `Delete`.
- **Severity**: low

### 10. `internal/services/audit_log_service.go` — raw column names

- **Lines**: 89-117
- **Issue**: `account_id`, `api_key_id`, `action`, `resource_type`, `resource_id`, `create_at_ms` used as raw literals.
- **Severity**: low

### 11. `internal/nats/consumer.go` — raw column names

- **Lines**: 216, 261, 285, 450, 670, 716
- **Issue**: `group_id`, `message_id`, `agent_id`, `status`, `member_id`, `create_at_ms` used as raw literals.
- **Severity**: low

### 12. `internal/services/bootstrap.go` — raw column names

- **Lines**: 190, 258, 263
- **Issue**: `role`, `status` used as raw literals.
- **Severity**: low

## Summary

- **Hard-coded table names requiring `TableName()` refactor**: 1 remaining location (`internal/api/handlers/group.go` JOIN/WHERE/ORDER BY was already fixed; no other literal table names found in SQL).
- **Raw column-name literals**: widespread but low severity. A project-wide decision is needed on whether to enforce column-name constants.
- **Potential behavior bug**: `internal/services/account_service.go#ListAccounts` may include deleted accounts.
- **Postgres system-catalog queries**: acceptable as raw SQL.

## Recommended next steps

1. Decide project policy:
   - Must table names always use `models.*.TableName()`? (already mostly true)
   - Should column names also be centralized/constants, or are raw column literals acceptable when GORM model context is clear?
2. Fix the medium-severity `ListAccounts` deleted-account leak if confirmed as a bug.
3. If column-name centralization is adopted, create a shared constants package (e.g., `internal/models/columns.go`) and refactor gradually.
4. Close this issue once the policy is recorded and the `ListAccounts` behavior is clarified/fixed.
