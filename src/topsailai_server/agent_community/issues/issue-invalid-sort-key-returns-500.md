---
status: open
priority: low
assignee: 
created: 2026-06-12
---

# Issue: Invalid sort_key returns HTTP 500 instead of 400

## Description

When querying messages with an invalid `sort_key` parameter, the API returns HTTP 500 Internal Server Error instead of HTTP 400 Bad Request.

## Steps to Reproduce

```bash
curl -s -w "\n%{http_code}" "http://127.0.0.1:7370/api/v1/groups/{group_id}/messages?sort_key=invalid&limit=1"
```

## Expected Behavior

HTTP 400 Bad Request with an error message like `{"error": "invalid sort_key"}`.

## Actual Behavior

HTTP 500 Internal Server Error.

## Root Cause

The `ListMessages` handler in `internal/api/handlers/message.go` does not validate the `sort_key` parameter against allowed values before constructing the database query. The invalid column name causes a database error that bubbles up as a 500 response.

## Suggested Fix

Add validation for `sort_key` in `ListMessages`:

```go
allowedSortKeys := map[string]bool{"create_at_ms": true, "update_at_ms": true}
if !allowedSortKeys[sortKey] {
    c.JSON(http.StatusBadRequest, gin.H{"error": "invalid sort_key"})
    return
}
```

## Impact

LOW — Client error is incorrectly exposed as a server error. Does not affect functionality with valid parameters.
