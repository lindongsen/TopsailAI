# Issue: Audit Log Handler Unit Tests and Related Production Fixes

## Description
While implementing unit tests for `internal/api/handlers/audit_log.go`, two production-code issues were identified and fixed to make the handler testable and consistent with API documentation.

## Changes Made

### 1. Audit Log `BeforeCreate` Hook (`internal/models/audit_log.go`)
**Problem:** The `BeforeCreate` hook unconditionally overwrote `CreateAtMs` with `time.Now().UnixMilli()`, making it impossible to seed deterministic timestamps in tests or migrations.

**Fix:** Only set `CreateAtMs` when it is zero:
```go
if al.CreateAtMs == 0 {
    al.CreateAtMs = time.Now().UnixMilli()
}
```

**Impact:** Existing behavior is preserved for normal creation paths. Tests and bulk imports can now supply explicit timestamps.

### 2. Audit Log `GetAuditLog` Validation (`internal/api/handlers/audit_log.go`)
**Problem:** `GET /api/v1/audit-logs/:audit_log_id` did not validate the path parameter. An empty `audit_log_id` resulted in a 404 "not found" response, which is semantically incorrect for a missing required parameter.

**Fix:** Added an explicit check at the start of `GetAuditLog`:
```go
if auditLogID == "" {
    c.JSON(http.StatusBadRequest, gin.H{"error": "audit_log_id is required", "trace_id": traceID})
    return
}
```

**Impact:** Empty or missing `audit_log_id` now returns `400 Bad Request` instead of `404 Not Found`. Non-empty IDs that do not exist still return `404 Not Found` as before.

## Tests Added
- `internal/api/handlers/audit_log_test.go`
  - `TestAuditLogHandler_List_Success`
  - `TestAuditLogHandler_List_FilterByAccountID`
  - `TestAuditLogHandler_List_FilterByAction`
  - `TestAuditLogHandler_List_TimeRange`
  - `TestAuditLogHandler_List_Pagination`
  - `TestAuditLogHandler_List_Empty`
  - `TestAuditLogHandler_Get_Success`
  - `TestAuditLogHandler_Get_NotFound`
  - `TestAuditLogHandler_Get_InvalidID`

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test -race ./internal/api/handlers/...
go test -race ./...
go vet ./...
go build ./...
```

All commands pass successfully.

## Related Docs
- `docs/API.md` — Audit log endpoint specifications
- `README.md` — Audit logging overview
