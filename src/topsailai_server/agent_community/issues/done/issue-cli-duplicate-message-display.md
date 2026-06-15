---
issue_id: issue-cli-duplicate-message-display
status: done
priority: high
created: 2026-06-16
assignee: km3-programmer
---

# Bug Fix: CLI Duplicate Message Display

## Problem Description

In the ACS CLI terminal, messages with the same `message_id` were displayed repeatedly. Example output:

```
acs@dawson:89aa879f-822f-4709-9fb8-353468810a91# test3 @manager-agent
acs@dawson:89aa879f-822f-4709-9fb8-353468810a91# [2026-06-16T02:43:47] 📡 Event: message create 89aa879f-822f-4709-9fb8-353468810a91
[2026-06-15T18:43:47] dawson
  test3 @manager-agent
[2026-06-15T18:43:47] dawson.local
  test3 @manager-agent
```

The same message "test3 @manager-agent" appeared twice with different sender names ("dawson" and "dawson.local").

## Root Cause

1. `SendChatMessage()` in `chat.go` sends a message via HTTP API and immediately displays it locally (without `message_id`).
2. The same message comes back via NATS or HTTP polling with a `message_id`, and `displayEvent()` renders it again.
3. No deduplication mechanism existed to prevent the same message from being displayed multiple times.

## Solution

Implemented message deduplication in the CLI by tracking already-displayed `message_id` values.

### Changes Made

#### 1. `cmd/cli/chat.go`

- Added `displayedMsgIDs map[string]struct{}` field to `ChatMode` struct.
- Initialized `displayedMsgIDs` in `NewChatMode()`.
- Added thread-safe helper methods:
  - `isMessageDisplayed(msgID string) bool`
  - `markMessageDisplayed(msgID string)`
  - `clearDisplayedMessages()`
- Modified `SendChatMessage()` to parse the API response for `message_id` and mark it as displayed before local echo.
- Modified `displayEvent()` to skip rendering if `message_id` is already in `displayedMsgIDs`.
- Modified `LeaveChat()` to call `clearDisplayedMessages()` to prevent memory leaks.

#### 2. `cmd/cli/chat_test.go`

Added 7 new unit tests covering the deduplication logic:

- `TestIsMessageDisplayed` - verifies check logic
- `TestMarkMessageDisplayed` - verifies marking logic
- `TestClearDisplayedMessages` - verifies cleanup logic
- `TestDisplayEventDeduplication` - verifies duplicate events are skipped
- `TestDisplayEventDifferentGroup` - verifies cross-group isolation
- `TestDisplayEventNonMessageType` - verifies non-message events don't interfere
- `TestMessageDeduplicationConcurrency` - verifies thread-safety under concurrent access

## Test Results

All tests pass:

```
ok  github.com/topsailai/agent-community/cmd/cli  0.014s
```

Full test suite also passes:

```
ok  github.com/topsailai/agent-community/cmd/cli
ok  github.com/topsailai/agent-community/internal/agent
ok  github.com/topsailai/agent-community/internal/api/handlers
ok  github.com/topsailai/agent-community/internal/config
ok  github.com/topsailai/agent-community/internal/db
ok  github.com/topsailai/agent-community/internal/discovery
ok  github.com/topsailai/agent-community/internal/message
ok  github.com/topsailai/agent-community/internal/models
ok  github.com/topsailai/agent-community/internal/nats
ok  github.com/topsailai/agent-community/internal/trigger
ok  github.com/topsailai/agent-community/internal/workpool
```

## Files Modified

- `cmd/cli/chat.go`
- `cmd/cli/chat_test.go`
