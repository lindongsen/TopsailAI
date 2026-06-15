---
maintainer: AI
status: done
---
# `init_context_message` incorrectly included in all agent trigger messages, and missing `---` separators between messages

## Bugs

### Bug 1: `init_context_message` always prepended

`init_context_message` (group info + member list) was being prepended to **all** agent trigger messages, regardless of whether `last_read_message_id` was set.

Per ORIGIN.md, it should ONLY be included when `last_read_message_id` is empty (first time triggering an agent).

### Bug 2: Missing `---` separators between messages

Messages in the context were joined with plain newlines instead of `---` single-line separators as required by ORIGIN.md.

### Bug 3: Pending message duplication in `getRecentMessages`

The pending message was appended unconditionally at the end of `getRecentMessages`, even when it already existed in the message list within the time window, causing duplication.

## Fixes

### `internal/message/context_builder.go`

- **Bug 1:** Moved `initContext = cb.buildInitContext(...)` inside the `if lastReadMessageID == ""` block. Only prepends `initContext` when non-empty.
- **Bug 2:** Rewrote `buildMessageContext` to wrap each message with `---\n` prefix and add trailing `---\n`.
- **Bug 3:** Added skip logic in `getRecentMessages` loop to exclude `pendingMessage.MessageID`, then append it once at the end.

### `internal/message/context_builder_test.go`

- Added assertions verifying `init_context_message` is **absent** when `lastReadMessageID` is set.
- Added assertions verifying `---` separators exist between messages.
- Added `TestBuildMessageContextSeparator` test for multi-message `---` delimiter validation.
- Updated `TestGetRecentMessages` expectation from 2 to 1 message (reflects deduplication fix).

## Verification

All tests pass:
```
go test ./internal/message/... -v   # PASS
go test ./...                        # PASS (all 11 packages)
```
