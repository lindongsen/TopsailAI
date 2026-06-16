# Issue: CLI `@` mention auto-completion in chat mode

## Description
When a user enters a group chat via `/group:enter`, typing `@` should trigger auto-completion suggestions for member names in that group. This improves the user experience when mentioning other members or agents.

## Expected Behavior
- Typing `@` shows all members + `@all`
- Typing `@A` filters to members starting with "A" (case-insensitive)
- After selecting a completion, the input contains `@member_name ` (with trailing space)
- Slash commands (`/help`, `/exit`, etc.) continue to work as before

## Implementation

### Files Modified
1. `cmd/cli/completer.go`
   - Added `chatMentionCompleter` struct implementing `readline.AutoCompleter`
   - Added `newChatMentionCompleter(membersGetter)` constructor
   - `Do()` method handles:
     - Slash commands delegated to existing `newChatCompleter()`
     - `@` prefix detection and member name filtering
     - Case-insensitive prefix matching
     - Deduplication of member names
     - Automatic `@all` suggestion

2. `cmd/cli/chat.go`
   - Changed `EnterChat` to use `newChatMentionCompleter` with a closure that returns the current cached members from `ChatMode`
   - Members are dynamically fetched via `refreshMembers()` and updated through NATS events

3. `cmd/cli/completer_test.go`
   - Added 12 new test cases for mention completion:
     - `TestChatMentionCompleterEmptyMembers`
     - `TestChatMentionCompleterWithMembers`
     - `TestChatMentionCompleterPrefixFilter`
     - `TestChatMentionCompleterCaseInsensitive`
     - `TestChatMentionCompleterDeduplicates`
     - `TestChatMentionCompleterSkipsEmptyName`
     - `TestChatMentionCompleterSlashCommands`
     - `TestChatMentionCompleterMidLine`
     - `TestChatMentionCompleterNoAtSymbol`
     - `TestChatMentionCompleterUnicodeName`
     - `TestChatMentionCompleterAllPrefix`
     - `TestChatMentionCompleterTrailingSpace`

## Bug Fix: Prefix Duplication

### Problem
Typing `@d` + Tab resulted in `@d@dawson` instead of `@dawson `.

### Root Cause
In `github.com/chzyer/readline`, the `AutoCompleter.Do()` interface contract is:
- `offset` = number of shared characters before `pos` that should be kept
- `newLine` = suffixes to append AFTER those shared characters

The original implementation returned the FULL candidate string (e.g., `@dawson `) with `offset = 2`. readline kept the shared `@d` prefix and appended the full candidate, producing `@d@dawson `.

### Fix
Modified `Do()` in `cmd/cli/completer.go` to return only the suffix after the already-typed prefix:
- For `@d` → member "dawson": returns `("awson ", 2)` instead of `("@dawson ", 2)`
- Same logic applied to `@all` suggestions
- Fixed word boundary detection to use rune-based iteration for Unicode safety

### Files Changed for Fix
- `cmd/cli/completer.go` — corrected candidate generation and offset calculation
- `cmd/cli/completer_test.go` — updated all tests to expect suffix-only candidates; added `TestChatMentionCompleterNoPrefixDuplication` regression test

## Status
- Fixed

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/... -v -run "TestChatMention"
```
All 13 mention completer tests pass.
