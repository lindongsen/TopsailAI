# Issue: Agent 执行时间过长导致重复执行

## 描述

当触发 agent 后，如果 agent 执行时间较长（超过 30 秒），在 agent 返回后会被再次执行一次，造成重复处理。

## 根本原因

1. **NATS JetStream Consumer 的 `AckWait` 仅 30 秒**，但 agent 默认超时 `timeout_chat` 为 600 秒，导致 NATS 在 agent 未完成时就重发消息
2. **`msg.Ack()` 在 `processMessage()` 完全结束后才发送**，而 processMessage 包含 agent chat 执行，可能耗时数分钟
3. **缺少 `InProgress()` 心跳机制**，无法在长时间处理中重置 AckWait 计时器
4. **缺少 agent 级别的"处理中"状态保护**，无法阻止 NATS 重发后同一 agent 对同一条消息的重复执行

## 修复方案

### 1. 延长 NATS Consumer 的 AckWait 时间

**文件**: `internal/nats/client.go`

将 `AckWait` 从 `30*time.Second` 改为 `15*time.Minute`，确保大于 agent 默认超时 600 秒。

```go
nats.AckWait(15*time.Minute),
```

### 2. 添加 InProgress() 心跳机制

**文件**: `internal/nats/consumer.go` - `Handler()`

在处理消息时启动 goroutine，每 20 秒调用一次 `msg.InProgress()`，重置 NATS 的 AckWait 计时器。处理完成后通过 `close(stopInProgress)` 停止心跳。

```go
stopInProgress := make(chan struct{})
go func() {
    ticker := time.NewTicker(20 * time.Second)
    defer ticker.Stop()
    for {
        select {
        case <-ticker.C:
            if err := msg.InProgress(); err != nil {
                logger.WarnM(consumerModule, traceID, "failed to send InProgress", "error", err)
            }
        case <-stopInProgress:
            return
        }
    }
}()
// ... processMessage ...
close(stopInProgress)
```

### 3. 添加 **agent 级别** 的重复处理检查

> **关键设计决策：去重粒度必须是 agent 级别，而非消息级别。**
>
> 原因：同一个 pending_message 可能触发多个不同的 agent（例如 mentions 中有多个 worker-agent）。如果实现消息级别去重，当 A1 正在处理消息 M1 时，A2 也会被错误地阻止，导致合法的并发处理被中断。
>
> **agent 级别去重的含义**：以 `(group_id, message_id, agent_id)` 为唯一键进行去重。不同的 agents 可以同时处理同一条消息；只有同一个 agent 对同一条消息的重复执行（如 NATS 重发导致）才会被阻止。

**文件**: `internal/nats/consumer.go`

#### 3a. 移除 message 级别的重复检查

从 `processMessage()` 中移除消息级别的 `isMessageAlreadyRunning` 检查。因为同一个 pending_message 可能触发多个不同的 agent，消息级别的检查会错误地阻止不同 agent 的合法并发处理。

**修改位置**：`processMessage()` 函数中，删除以下代码块：
```go
// 已删除：消息级别的重复检查
if isRunning, err := c.isMessageAlreadyRunning(groupID, messageID, traceID); err != nil {
    return fmt.Errorf("failed to check running status: %w", err)
} else if isRunning {
    logger.WarnM(consumerModule, traceID, "message already being processed by another node, skipping duplicate")
    return nil
}
```

#### 3b. 新增 `isAgentAlreadyRunning` 函数

```go
// isAgentAlreadyRunning checks if the specified agent is already processing the given message.
// 关键：以 agent_id 为粒度，不同 agent 可以同时处理同一条消息
func (c *Consumer) isAgentAlreadyRunning(groupID, messageID, agentID, traceID string) (bool, error) {
    var existing models.AgentMessageProcessing
    err := c.db.Where("group_id = ? AND message_id = ? AND agent_id = ? AND status = ?",
        groupID, messageID, agentID, models.ProcessingStatusRunning).
        First(&existing).Error
    if err != nil {
        if err == gorm.ErrRecordNotFound {
            return false, nil
        }
        return false, err
    }
    return true, nil
}
```

**关键区别**：WHERE 条件包含 `agent_id`，实现 agent 级别去重。

#### 3c. 在 `processAgentTarget` 中添加 agent 级别重复检查

在 `processAgentTarget` 函数中，**`createRunningRecord` 调用之前**添加：

```go
// Check if this agent is already processing this message (agent-level deduplication)
if isRunning, err := c.isAgentAlreadyRunning(group.GroupID, pendingMsg.MessageID, agentMember.MemberID, traceID); err != nil {
    return fmt.Errorf("failed to check agent running status: %w", err)
} else if isRunning {
    logger.WarnM(consumerModule, traceID, "agent already processing this message, skipping duplicate",
        "agent_id", agentMember.MemberID,
        "message_id", pendingMsg.MessageID,
    )
    return nil
}
```

**关键约束**：去重以 **agent_id（member_id）** 为粒度，不同的 agents 可以同时去触发处理同一条消息。

### 4. 创建 running 记录并更新状态

**文件**: `internal/nats/consumer.go` - `processAgentTarget()`

在获取信号量成功后、实际调用 agent chat 前，创建 `AgentMessageProcessing` 的 `running` 状态记录。

新增方法 `createRunningRecord()`:
```go
func (c *Consumer) createRunningRecord(groupID, messageID, agentID, traceID string) error {
    record := &models.AgentMessageProcessing{
        GroupID:   groupID,
        MessageID: messageID,
        AgentID:   agentID,
        Status:    models.ProcessingStatusRunning,
    }
    if err := c.db.Create(record).Error; err != nil {
        return fmt.Errorf("failed to create running record: %w", err)
    }
    return nil
}
```

修改 `recordProcessingStatus()` 方法，优先尝试更新已有的 `running` 记录为最终状态（completed/failed），而不是总是创建新记录。

## 新增单元测试

**文件**: `internal/nats/consumer_duplicate_test.go`

新增以下测试用例：

### `isAgentAlreadyRunning` 测试
- `TestIsAgentAlreadyRunning_NoRecord` - 无记录时返回 false
- `TestIsAgentAlreadyRunning_SameAgentRunning` - 同一 agent 有 running 记录时返回 true
- `TestIsAgentAlreadyRunning_DifferentAgentRunning` - 不同 agent 有 running 记录时返回 false（关键测试）
- `TestIsAgentAlreadyRunning_CompletedRecord` - 已完成记录返回 false
- `TestIsAgentAlreadyRunning_FailedRecord` - 失败记录返回 false

### `createRunningRecord` 测试
- `TestCreateRunningRecord` - 创建 running 记录

### `recordProcessingStatus` 测试
- `TestRecordProcessingStatus_UpdateRunningRecord` - 更新 running 到 completed
- `TestRecordProcessingStatus_UpdateRunningRecordToFailed` - 更新 running 到 failed
- `TestRecordProcessingStatus_NoRunningRecord_CreatesNew` - 无 running 时创建新记录
- `TestRecordProcessingStatus_UpdatesTimestamp` - 验证时间戳更新

### Agent 级别去重集成测试
- `TestAgentLevelDeduplication_SameAgentSameMessage` - 同一 agent 同一消息应去重
- `TestAgentLevelDeduplication_DifferentAgentsSameMessage` - 不同 agent 同一消息应允许并发
- `TestAgentLevelDeduplication_MultipleAgentsCanRun` - 多个不同 agent 可同时处理同一条消息

## 验证结果

- `go build ./...` 编译通过
- `go test ./...` 全部测试通过

## 修复日期

2026-06-16

## 修正记录

### 2026-06-16 第一次修正：粒度错误

**问题**：初始修复错误地实现了**消息级别**的去重。

**具体错误**：
- 在 `processMessage()` 中调用了 `isMessageAlreadyRunning(groupID, messageID)`，该函数只检查 `(group_id, message_id, status=running)`
- 当消息 M1 触发 agents A1 和 A2 时：
  1. A1 开始处理，创建 running 记录 `(M1, A1, running)`
  2. 当处理 A2 时（同一 processMessage 内，或 NATS 重发后），`isMessageAlreadyRunning("g1", "M1")` 查到 `(M1, A1, running)`
  3. **错误地认为 M1 已在处理，跳过 A2**
  4. **不同 agent 无法同时处理同一条消息！**

**根因分析**：
- `isMessageAlreadyRunning` 的 WHERE 条件缺少 `agent_id`
- `isMessageAlreadyRunning` 的调用位置在 `processMessage` 中，此时还没有解析出 targets，根本不知道要处理哪些 agents
- 测试用例 `TestIsMessageAlreadyRunning_DifferentAgent` 断言了错误的行为（同一 message 不同 agent 应返回 running）

**修正为 agent 级别去重**：
- **删除** `processMessage()` 中的消息级别 `isMessageAlreadyRunning` 检查
- **新增** `isAgentAlreadyRunning(groupID, messageID, agentID)` 函数，WHERE 条件包含 `agent_id`
- 在 `processAgentTarget()` 中、**`createRunningRecord` 调用之前**添加 agent 级别检查
- **重写测试文件**，核心测试 `TestIsAgentAlreadyRunning_DifferentAgentRunning` 验证：a1 running 时，检查 a2 → 返回 `false`

**agent 级别去重的正确行为**：

| 场景 | 消息级别去重（Bug） | agent 级别去重（正确） |
|------|-------------------|---------------------|
| M1 触发 A1、A2 | A1 运行时，A2 被错误跳过 | A1、A2 **同时执行** |
| NATS 重发 M1（A1 仍在运行） | 整条消息被跳过 | 只有 **A1 被跳过**，A2 正常处理 |
| 同一 agent 被重复触发 | 不受影响 | **被阻止** |

**关键设计原则**：
> 去重粒度 = **agent 级别**，即 `(group_id, message_id, agent_id)` 的组合唯一性。
> 不同 agent 对同一条消息的并发处理是**合法且必须支持**的。
> 只有 NATS 重发导致的**同一 agent 对同一条消息的重复执行**才需要被阻止。


### 5. InProgress() 心跳机制实现

**文件**: `internal/nats/consumer.go` - `Handler()`

在 `Handler()` 方法中，启动 goroutine 定期调用 `msg.InProgress()`，重置 NATS 的 AckWait 计时器。处理完成后通过 `close(stopInProgress)` 停止心跳。

```go
func (c *Consumer) Handler() nats.MsgHandler {
    return func(msg *nats.Msg) {
        traceID := msg.Header.Get("X-Trace-ID")
        if traceID == "" {
            traceID = uuid.New().String()
        }

        // Extract message_id for logging
        var payload PendingMessagePayload
        messageID := "unknown"
        if err := json.Unmarshal(msg.Data, &payload); err == nil && payload.MessageID != "" {
            messageID = payload.MessageID
        }

        // Start InProgress heartbeat goroutine
        // This prevents NATS from redelivering the message during long-running agent execution
        stopInProgress := make(chan struct{})
        go func() {
            ticker := time.NewTicker(20 * time.Second)
            defer ticker.Stop()
            for {
                select {
                case <-ticker.C:
                    if err := msg.InProgress(); err != nil {
                        logger.WarnM(consumerModule, traceID, "failed to send InProgress",
                            "error", err,
                            "message_id", messageID,
                        )
                    }
                case <-stopInProgress:
                    return
                }
            }
        }()

        if err := c.processMessage(msg, traceID); err != nil {
            logger.ErrorM(consumerModule, traceID, "failed to process pending message", "error", err)
            close(stopInProgress)
            msg.Nak()
            return
        }
        close(stopInProgress)
        msg.Ack()
    }
}
```

**关键设计点**：
- **心跳间隔**: 20 秒（固定值，远小于 AckWait=15 分钟）
- **InProgress 发送失败**: 只记录 warn 日志，**绝对不中断**主流程或导致消息 Nak
- **goroutine 泄漏防护**: `stopInProgress` channel 通过 `defer` 确保一定被 close，即使 `processMessage` panic
- **消息 ID 提取**: 从 payload 中提取 message_id，用于日志追踪

**新增单元测试**: `internal/nats/consumer_inprogress_test.go`

新增以下测试用例：

- `TestHandler_InProgressHeartbeat_Success` - 成功流程：心跳启动、processMessage 成功、心跳停止、msg.Ack()
- `TestHandler_InProgressHeartbeat_Failure` - 失败流程：心跳启动、processMessage 失败、心跳停止、msg.Nak()
- `TestHandler_InProgressError_DoesNotAffectMainFlow` - InProgress 发送失败不影响主流程
- `TestHandler_NoGoroutineLeak` - 确保没有 goroutine 泄漏
- `TestHandler_PanicRecovery` - panic 恢复时心跳 goroutine 仍被正确停止
- `TestHandler_MessageIDExtraction` - 消息 ID 提取测试
- `TestHandler_LongRunningProcessing` - 长时间运行过程中 InProgress 持续被调用
- `TestHandler_StopInProgressCalledExactlyOnce` - stopInProgress 只被关闭一次
- `TestHandler_InProgressStopsAfterClose` - 关闭 channel 后心跳立即停止
- `TestHandler_PanicWithHeartbeat` - 完整 panic 恢复场景包括心跳清理

**验证结果**：
- `go build ./...` 编译通过
- `go test ./internal/nats/ -v` 全部测试通过（含原有测试和新增测试）

## 最终修复总结

| 修复项 | 文件 | 状态 |
|--------|------|------|
| 延长 AckWait 到 15 分钟 | `internal/nats/client.go` | ✅ 已完成 |
| InProgress() 心跳机制 | `internal/nats/consumer.go` | ✅ 已完成 |
| Agent 级别去重 | `internal/nats/consumer.go` | ✅ 已完成 |
| 创建 running 记录 | `internal/nats/consumer.go` | ✅ 已完成 |
| 更新处理状态 | `internal/nats/consumer.go` | ✅ 已完成 |
| 单元测试 | `consumer_duplicate_test.go`, `consumer_inprogress_test.go` | ✅ 已完成 |

**修复日期**: 2026-06-16

## Section 6: No-Ack Mode (Fire-and-Forget) Implementation

**Date**: 2026-06-16
**Status**: ✅ Implemented

### Problem
User requested a switch to control whether pending messages require acknowledgment from consumers. In some scenarios, users want fire-and-forget message delivery without waiting for consumer confirmation.

### Solution
Added `ACS_NATS_PENDING_MESSAGE_NO_ACK` environment variable to enable/disable no-ack mode.

### Changes

#### 1. `internal/nats/client.go`
- Read `ACS_NATS_PENDING_MESSAGE_NO_ACK` from environment
- When `NoAck=true`: use `nats.AckNone()` instead of `nats.ManualAck()`
- When `NoAck=false`: use `nats.ManualAck()` + configurable `AckWait`

#### 2. `internal/nats/consumer.go`
- Added `noAck` field to `Consumer` struct
- Handler logic branches based on `noAck` flag:
  - `noAck=true`: no heartbeat, no Ack/Nak, direct processing with error logging only
  - `noAck=false`: existing ManualAck + InProgress heartbeat logic

#### 3. `internal/config/config.go`
- Added `PendingMessageNoAck` (bool) and `AckWaitSeconds` (int) to `NATSConfig`

#### 4. `docs/Environment_Variables.md`
- Documented `ACS_NATS_PENDING_MESSAGE_NO_ACK`
- Documented `ACS_NATS_ACK_WAIT_SECONDS`

#### 5. `internal/nats/consumer_noack_test.go`
- 22 unit tests covering no-ack mode, ack mode, configuration, edge cases

### Behavior Comparison

| Aspect | No-Ack Mode (NoAck=true) | Ack Mode (NoAck=false) |
|--------|-------------------------|----------------------|
| Ack/Nak | Not called | Called after processing |
| InProgress heartbeat | Not started | Started every 20s |
| Message guarantee | At-most-once | At-least-once |
| Use case | High throughput, tolerate loss | Reliability required |

### Warning
**No-Ack mode may cause message loss** if consumer crashes during processing. Only enable when message loss is acceptable.

### Test Results
```bash
$ go test ./internal/nats/ -v
PASS
ok  github.com/topsailai/agent-community/internal/nats  1.340s
```
All 22 tests passed.
