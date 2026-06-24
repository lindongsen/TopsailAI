---
status: open
severity: medium
component: trigger
---

# Trigger loop sliding window size is off-by-one

## Summary
The `NO_TRIGGER_CASES` rule states that a message should not trigger agents if, within the 10 messages before and 10 messages after it, there is a sliding window of more than 10 consecutive agent messages. The current implementation fetches 11 messages before and 11 messages after, producing a 22-message window instead of the documented 20-message window.

## Affected file
- `internal/trigger/evaluator.go` (`isLoopMessage`)

## Expected behavior
- Fetch exactly 10 messages before and 10 messages after the target message.
- Check for more than 10 consecutive messages whose sender type ends with `-agent`.
- The total inspected window should be 20 messages.

## Actual behavior
```go
beforeMessages, err := s.messageRepo.ListMessages(ctx, groupID, ListMessageFilter{BeforeMessageID: messageID, Limit: 11})
afterMessages, err := s.messageRepo.ListMessages(ctx, groupID, ListMessageFilter{AfterMessageID: messageID, Limit: 11})
```
`Limit: 11` on each side yields 22 messages total, which is inconsistent with the documented 20-message window.

## Reproduction Steps
1. Create a group with one user and one manager-agent.
2. Send exactly 10 user messages interleaved so that the agent replies once after each user message.
3. Send an 11th user message.
4. With the current code, the agent may be incorrectly suppressed because the 22-message window contains enough consecutive agent replies to exceed the threshold.
5. With the fix (`Limit: 10`), the 11th user message should still trigger the agent because the documented 20-message window is used.

## Suggested fix
Change both `Limit` values from `11` to `10`:
```go
beforeMessages, err := s.messageRepo.ListMessages(ctx, groupID, ListMessageFilter{BeforeMessageID: messageID, Limit: 10})
afterMessages, err := s.messageRepo.ListMessages(ctx, groupID, ListMessageFilter{AfterMessageID: messageID, Limit: 10})
```
Verify that the consecutive-agent check (`maxConsecutive > 10`) remains correct for the 20-message window.

## Verification
- `go test ./internal/trigger/...` passes.
- New unit test: with 10 agent messages in a 20-message window, the 11th user message is not suppressed.
- New unit test: with 11 consecutive agent messages in a 20-message window, the user message is suppressed.

## References
- `docs/API.md` "Agent Triggering" > NO_TRIGGER_CASES
- `ORIGIN.md` "How to trigger agent" > NO_TRIGGER_CASES
- `internal/trigger/evaluator.go` `isLoopMessage`

## Resolution

- **Status:** resolved
- **Source files changed:**
  - `internal/trigger/evaluator.go`
  - `internal/trigger/evaluator_test.go`
- **Key fix:**
  - In `isLoopMessage`, changed the message window limits from 11 before/after to 10 before/after, matching the documented 20-message window.
  - Updated the inline comment and boundary unit tests accordingly.
- **Test verification:**
  - `go test ./internal/trigger/...` passes.
  - Full suite `go test ./...` passes.
