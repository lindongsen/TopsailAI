---
issue_id: issue-duplicate-member-500
status: open
priority: low
created_at: 2026-06-12
related_files:
  - internal/api/handlers/group_member.go
---

# Issue: Duplicate Member Addition Returns 500 Instead of 409

## Description

When attempting to add a member that already exists in a group, the API returns HTTP 500 (Internal Server Error) instead of HTTP 409 (Conflict).

## Root Cause

In `internal/api/handlers/group_member.go`, the `JoinGroup` function (line 95) directly calls `h.db.Create(&member)` without first checking if the member already exists. When GORM encounters a duplicate primary key violation, it returns an error that is treated as a 500 Internal Server Error.

## Impact

- API consumers cannot distinguish between a server failure and a duplicate entry
- Poor API user experience
- Potential for unnecessary retry attempts by clients

## Expected Behavior

HTTP 409 Conflict with a clear error message like "member already exists in group".

## Suggested Fix

Add a pre-check before inserting:

```go
// Check if member already exists
var existingMember models.GroupMember
if err := h.db.Where("group_id = ? AND member_id = ?", groupID, req.MemberID).First(&existingMember).Error; err == nil {
    c.JSON(http.StatusConflict, gin.H{"error": "member already exists in group"})
    return
}
```

## Verification

Test case that reproduces the issue:
```bash
# Add a member
curl -s -X POST http://127.0.0.1:7370/api/v1/groups/{group_id}/members \
  -H "Content-Type: application/json" \
  -d '{"member_id":"user-001","member_name":"Alice","member_type":"user"}'

# Try to add the same member again
curl -s -X POST http://127.0.0.1:7370/api/v1/groups/{group_id}/members \
  -H "Content-Type: application/json" \
  -d '{"member_id":"user-001","member_name":"Alice","member_type":"user"}'
```

Expected: HTTP 409 with error message
Actual: HTTP 500 with error message
