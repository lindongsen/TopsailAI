---
status: fixed
severity: high
component: internal/api/handlers/message.go
---

# Message edit does not re-extract mentions

## Problem
When a message is edited via `PUT /api/v1/groups/:group_id/messages/:message_id`, the `mentions` field is not re-extracted from the new `message_text`. This causes stale mention data and can prevent agent triggering after an edit.

## Root cause
`UpdateMessage` in `internal/api/handlers/message.go` only updated `MessageText` and `MessageAttachments`, but did not call the mention extraction logic when the text changed.

## Fix
- In `UpdateMessage`, after validating the update, fetch current group members and call `trigger.ExtractMentionsFromText(updatedText, members)` when `message_text` is present in the request.
- Persist the new `mentions` JSON to the database.
- Added unit test `TestUpdateMessage_ReextractMentions` in `internal/api/handlers/message_test.go` covering:
  - Adding a mention on edit
  - Removing a mention on edit
  - Preserving mentions when only attachments are updated

## Changed files
- `internal/api/handlers/message.go`
- `internal/api/handlers/message_test.go`

## Verification
```bash
go test ./internal/api/handlers/... -run TestUpdateMessage_ReextractMentions -v
# PASS

go test ./internal/api/handlers/... ./internal/services/...
# ok

go build ./...
# ok
```
