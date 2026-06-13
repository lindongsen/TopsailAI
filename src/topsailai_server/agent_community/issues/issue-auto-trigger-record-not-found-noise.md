---
maintainer: human
programming_language: go
related_technology_stack:
  - postgresql
  - nats
keywords:
  - auto-trigger
  - logging
  - error-noise
---
# Issue: Frequent `record not found` Errors in Auto-Trigger Scanner

## Severity
Low

## Description
The auto-trigger scanner produces frequent `record not found` error logs:

```
2026/06/13 07:30:17 /TopsailAI/src/topsailai_server/agent_community/internal/nats/auto_trigger.go:143 record not found
```

These errors occur when the auto-trigger periodic task scans groups that have been deleted during testing. The scanner iterates over all groups and attempts to process them, but some may no longer exist in the database.

## Steps to Reproduce
1. Create multiple groups via API
2. Delete some of those groups
3. Wait for the auto-trigger periodic scan to run
4. Observe `record not found` errors in the logs

## Expected Behavior
- Deleted groups should be silently skipped by the auto-trigger scanner
- Or the error should be logged at WARN/DEBUG level, not ERROR

## Actual Behavior
- `record not found` is logged at ERROR level
- Creates noise in logs and may trigger false alerts in monitoring systems

## Impact
- Log noise that makes it harder to identify real issues
- Potential false alerts in production monitoring if ERROR-level logs are alerted on
- No functional impact — the system continues to work correctly

## Files to Investigate
- `internal/nats/auto_trigger.go` — around line 139-143
- The group query/scan logic should filter out deleted groups
- Error handling should distinguish between "group deleted" and actual errors

## Suggested Fix
1. Add `WHERE deleted_at IS NULL` (or equivalent) to the auto-trigger group query
2. Or catch `record not found` specifically and log at DEBUG level
3. Or maintain a separate list of active groups for the auto-trigger scanner

## Related
- ORIGIN.md: "auto-trigger" section
- ORIGIN.md: "Distributed Lock via NATS KV" section
