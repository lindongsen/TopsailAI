---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---
# Issue: Missing ACS_AGENT_TYPE in BuildChatEnv

**Status**: Open
**Priority**: Low
**Component**: agent/executor
**Related Spec**: ORIGIN.md "How to trigger agent" -> "trigger agent with environment variables"

## Description

The specification lists `ACS_AGENT_TYPE` as a required environment variable that maps to `member_type`. However, `BuildChatEnv()` in `executor.go` does not set this variable. It is only set in `BuildInitEnv()`.

## Spec Reference

> ACS_AGENT_TYPE -> member_type

## Current Code

File: `internal/agent/executor.go:BuildChatEnv()` (lines 52-82)

The function sets `ACS_AGENT_ID`, `ACS_AGENT_NAME`, `ACS_AGENT_API_BASE`, `ACS_AGENT_API_KEY`, `ACS_AGENT_API_AUTH`, `ACS_AGENT_MODE`, `ACS_AGENT_MESSAGE`, `ACS_AGENT_TIMEOUT`, `ACS_AGENT_PROMPT`, `ACS_GROUP_ID`, `ACS_GROUP_NAME`, `ACS_GROUP_CONTEXT`, `ACS_SENDER_ID`, `ACS_SENDER_NAME`, `ACS_MESSAGE_ID`, `ACS_MESSAGE_MENTIONS`, `ACS_MESSAGE_TRIGGER_TYPE` — but **not** `ACS_AGENT_TYPE`.

## Expected Behavior

`BuildChatEnv()` should include:
```go
fmt.Sprintf("ACS_AGENT_TYPE=%s", agentMember.MemberType),
```

## Fix

Add `ACS_AGENT_TYPE` environment variable to `BuildChatEnv()` using the agent member's `MemberType` field.

## Impact

Low. Most agent adaptors can infer the agent type from other context, but the spec explicitly requires this variable.


## Fixed

- **Fix date**: 2026-06-12
- **Fixed by**: km3-programmer
- **Files changed**:
  - `internal/agent/interface.go` — Added `memberType` parameter to `BuildChatEnv()` and set `env["ACS_AGENT_TYPE"] = memberType`
  - `internal/agent/interface_test.go` — Updated test call and added assertion for `ACS_AGENT_TYPE`
  - `internal/nats/consumer.go` — Pass `string(agentMember.MemberType)` to `BuildChatEnv()`
