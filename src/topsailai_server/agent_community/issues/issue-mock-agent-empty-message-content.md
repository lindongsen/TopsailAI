---
maintainer: human
programming_language: go
related_technology_stack:
  - postgresql
  - nats
keywords:
  - mock-agent
  - agent-interface
  - environment-variables
---
# Issue: Mock Agent Receives Empty Message Content

## Severity
Medium

## Description
During distributed testing, the mock agent server logs show that `ACS_AGENT_MESSAGE` environment variable appears to be empty when the agent chat command is executed:

```
Chat response: [Mock Test Agent] Agent mode response to: ''
```

This indicates that the message content (context_messages) is not being properly passed to the agent via the `ACS_AGENT_MESSAGE` environment variable.

## Steps to Reproduce
1. Start ACS server with mock agent configuration
2. Create a group with a worker-agent member
3. Send a message with `@agent` mention
4. Observe mock agent server logs — the message content is empty

## Expected Behavior
`ACS_AGENT_MESSAGE` should contain the formatted context_messages (unprocessed messages) that the agent needs to process.

## Actual Behavior
`ACS_AGENT_MESSAGE` is empty (`''`), so the agent responds without actual message context.

## Impact
- Agent responses are generated but may not be contextually relevant
- Integration tests pass functionally but don't validate message content passing
- Could affect real agent integrations where message content is critical

## Files to Investigate
- `internal/agent/executor.go` — where `cmd_chat` is executed with environment variables
- `internal/nats/pending_message.go` — where pending messages are processed and context is built
- `scripts/mock_agent_cmd_chat.sh` — mock agent chat script

## Related
- ORIGIN.md: "ACS_AGENT_MESSAGE -> context_messages"
- ORIGIN.md: "Send Message Format" section
