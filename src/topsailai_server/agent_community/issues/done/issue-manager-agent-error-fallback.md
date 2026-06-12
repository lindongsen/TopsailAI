---
maintainer: AI
programming_language: go
---

# Issue: No Fallback When Manager-Agent Is Missing for Error Messages

## Description

In `internal/nats/consumer.go`, when an agent call fails, the code attempts to create a system error message using the manager-agent's identity. However, if the group has no manager-agent, the error message is silently dropped.

## Affected Code

File: `internal/nats/consumer.go`
Function: `processPendingMessage()` (around lines 296-318)

```go
managerAgent := findManagerAgent(members)
if managerAgent == nil {
    log.Error("no manager agent found for error message", ...)
    return
}
```

## Problem

- The spec says: "如果agent调用失败，也会得到一个系统生成的`错误结果`，这个消息使用 manager-agent 的身份进行标识（新消息的 sender 是 manager-agent），避免无限重试。"
- When no manager-agent exists, the error is logged but no error message is created in the database.
- This means the user never sees that the agent failed, and the system has no record of the failure.

## Suggested Fix

When `findManagerAgent()` returns nil, create the error message with a system-level identity:
- `SenderID`: `"system"` or `"acs-system"`
- `SenderName`: `"System"`
- `SenderType`: `models.MemberTypeManagerAgent` (to maintain the anti-retry property)

This ensures error messages are always recorded, even in groups without a manager-agent.
