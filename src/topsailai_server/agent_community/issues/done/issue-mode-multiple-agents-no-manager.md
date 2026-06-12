---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---
# Issue: Wrong ACS_AGENT_MODE for Multiple Agents Without Manager

**Status**: Open
**Priority**: Medium
**Component**: trigger/evaluator
**Related Spec**: ORIGIN.md "How to trigger agent" -> "trigger via mentions" -> rule 2

## Description

When a message mentions multiple agents and there is no manager-agent in the group, the specification requires `ACS_AGENT_MODE=agent` for all mentioned agents. However, the current implementation sets `Mode: "chat"` instead of `Mode: "agent"`.

## Spec Reference

> mentions 有多个member时，且 存在多个 xxx-agent 的memebers，不存在 manager-agent，可以并发调用对应的 member_interface 执行 cmd_chat, **ACS_AGENT_MODE=agent**, `ACS_AGENT_MESSAGE` 附加一段内容到最后一行:`! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !`;

## Current Code

File: `internal/trigger/evaluator.go:235`
```go
for _, agent := range mentionResult.agents {
    targets = append(targets, AgentTarget{
        AgentID: agent.MemberID,
        Mode:    "chat",  // BUG: should be "agent"
    })
}
```

## Expected Behavior

`Mode` should be `"agent"` so that the mentioned agents can use tools/skills as per the specification.

## Fix

Change `"chat"` to `"agent"` on line 235 of `internal/trigger/evaluator.go`.

## Impact

Agents mentioned together without a manager will currently run in chat-only mode (no tools), which contradicts the design intent.


## Fixed

- **Fix date**: 2026-06-12
- **Fixed by**: km3-programmer
- **Files changed**:
  - `internal/trigger/evaluator.go` — Changed `Mode: "chat"` to `Mode: "agent"` (line 235)
  - `internal/trigger/evaluator_test.go` — Updated test assertion to expect `"agent"` mode
