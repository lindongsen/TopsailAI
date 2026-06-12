---
issue_id: issue-atall-mentions-empty
status: open
priority: medium
created_at: 2026-06-12
related_files:
  - internal/trigger/evaluator.go
  - internal/api/handlers/message.go
---

# Issue: @all Mention Not Stored in Message Mentions Field

## Description

When a message contains `@all`, the `mentions` field in the database and API response is stored as an empty array `[]` instead of reflecting the `@all` mention.

## Root Cause

In `internal/trigger/evaluator.go`, the `ExtractMentionsFromText` function (line 338) uses regex `@([\w\-]+)` to extract mentions. While this regex does match `@all` (capturing `all`), the subsequent member lookup loop tries to find a member with `MemberID="all"` or `MemberName="all"`. Since no such member exists, the mention is not added to the result array.

The `extractMentions` function (used for trigger evaluation) correctly handles `@all` by setting `hasAll = true` and returning early (line 176-178). However, `ExtractMentionsFromText` (used for message storage) does not have this special handling.

## Impact

- Messages with `@all` show empty mentions array in API responses
- Consumers of the API cannot determine if `@all` was used by looking at the mentions field
- The stored message metadata is incomplete

## Expected Behavior

When `@all` is present in the message text, the mentions array should either:
- Include a special mention entry indicating `@all` was used, OR
- Include all group members in the mentions array

## Suggested Fix

Add `@all` handling to `ExtractMentionsFromText`:

```go
func ExtractMentionsFromText(text string, members []models.GroupMember) []models.Mention {
    mentions := make([]models.Mention, 0)
    if text == "" {
        return mentions
    }

    // Check for @all - include all members
    if strings.Contains(text, "@all") {
        for _, m := range members {
            mentions = append(mentions, models.Mention{
                MemberID:   m.MemberID,
                MemberName: m.MemberName,
                MemberType: string(m.MemberType),
            })
        }
        return mentions
    }

    // Existing regex-based extraction...
}
```

## Verification

Test case that reproduces the issue:
```bash
curl -s -X POST http://127.0.0.1:7370/api/v1/groups/{group_id}/messages \
  -H "Content-Type: application/json" \
  -d '{"message_text":"Hello @all","sender_id":"user-001","sender_type":"user"}'
```

Expected: `mentions` field should contain all group members
Actual: `mentions` field is `[]`
