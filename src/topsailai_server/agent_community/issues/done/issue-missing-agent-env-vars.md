---
maintainer: AI
programming_language: go
---

# Issue: Missing Agent Environment Variables in BuildChatEnv

## Description

The `BuildChatEnv()` function in `internal/agent/interface.go` does not pass several environment variables that are required by the ORIGIN.md specification in the `## How to trigger agent` section.

## Missing Variables

1. **ACS_AGENT_PROMPT**
   - Spec: "ACS_AGENT_PROMPT 来自服务的环境变量 ACS_AGENT_PROMPT"
   - Current: Not passed at all
   - Fix: Read from service env var `ACS_AGENT_PROMPT` and include in `BuildChatEnv()`

2. **ACS_GROUP_CONTEXT**
   - Spec: "ACS_GROUP_CONTEXT 就是 group_context 信息，仅当 last_read_message_id 为空时才会传递这个环境变量"
   - Current: Not passed at all
   - Fix: Pass `group.GroupContext` only when `last_read_message_id` is empty

3. **ACS_MESSAGE_MENTIONS**
   - Spec: Listed as required env var in ORIGIN.md
   - Current: Not passed at all
   - Fix: Pass JSON string of message mentions

4. **ACS_MESSAGE_TRIGGER_TYPE**
   - Spec: Listed as required env var in ORIGIN.md
   - Current: Not passed at all
   - Fix: Pass trigger type (mention/auto)

## Affected File

- `internal/agent/interface.go` - `BuildChatEnv()` function

## Impact

Agents may not receive complete context information, potentially affecting their behavior and ability to process messages correctly.

## Suggested Fix

Update `BuildChatEnv()` to include the missing variables. Consider adding `AgentPrompt` to `config.Config` for centralized access.
