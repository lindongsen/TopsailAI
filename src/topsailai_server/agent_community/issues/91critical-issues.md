# Critical Issues & Key Design Decisions

> **Feature ID**: 91
> **Category**: Critical Issues / Key Design Safeguards
> **Last Updated**: 2026-06-16

---

## Overview

This document records critical issues and their corresponding key design decisions in the AI-Agent Community Server (ACS). Each issue is documented as an independent top-level section to facilitate future expansion.

When a new critical issue is identified, append a new `## Issue N: Title` section at the end of this document, following the same structure as existing issues.

---

## Issue 1: Agent-Level Deduplication for Long-Running Agent Execution

> **Corresponding Issue**: [issues/issue-agent-duplicate-execution-on-long-running.md](../issues/issue-agent-duplicate-execution-on-long-running.md)

### 1.1 Problem Background

In ACS, a single `pending_message` may trigger one or more agents to process it. Due to the following factors, there is a risk of duplicate agent execution:

- NATS JetStream Consumer `AckWait` defaults to only 30 seconds, but agent execution may take up to 600 seconds
- `msg.Ack()` is only sent after agent execution completes
- There is no in-progress status protection mechanism

When agent execution exceeds the `AckWait` threshold, NATS considers the message processing failed and redelivers it, causing the same agent to be executed again for the same message.

### 1.2 Core Design Decision: Agent-Level Deduplication

#### 1.2.1 Why Must It Be Agent-Level?

**Key Constraint**: A single `pending_message` can trigger **multiple different agents**.

Typical scenario:
- User sends a message: `@agent-A1 @agent-A2 please help analyze this problem`
- This message needs to trigger both A1 and A2 simultaneously
- A1 and A2 should **execute concurrently** without interfering with each other

If **message-level** deduplication is implemented (using `group_id + message_id` as the granularity):
- When A1 starts processing, a running record is created
- The system detects "this message is already being processed" and skips A2
- **Result**: A2 is incorrectly blocked, and legitimate concurrent processing is interrupted

#### 1.2.2 Definition of Agent-Level Deduplication

> **Deduplication Granularity = Agent-Level**
>
> Use the combination of `(group_id, message_id, agent_id)` as the unique key for deduplication.

**Meaning**:
- ✅ **Different agents** can **concurrently** process the **same message**
- ❌ **Duplicate execution** of the **same agent** on the **same message** must be blocked

#### 1.2.3 Scenario Comparison

| Scenario | Message-Level Deduplication (Incorrect) | Agent-Level Deduplication (Correct) |
|----------|----------------------------------------|-------------------------------------|
| M1 triggers A1, A2 | A2 incorrectly skipped while A1 is running | A1, A2 **execute concurrently** ✅ |
| NATS redelivers M1 (A1 still running) | Entire message skipped (A2 also affected) | Only **A1 is skipped**, A2 processes normally ✅ |
| NATS redelivers M1 (A1 already completed) | Entire message skipped | A1 may execute again (requires additional mechanisms) |
| Different messages trigger same agent | Not affected | Not affected |

### 1.3 Technical Implementation

#### 1.3.1 Database Table: `AgentMessageProcessing`

```go
type AgentMessageProcessing struct {
    GroupID   string // gorm:"index:idx_amp_group_msg"
    MessageID string // gorm:"index:idx_amp_group_msg"
    AgentID   string // Key field! Supports agent-level distinction
    Status    string // pending / running / completed / failed
    // ...
}
```

**Key Point**: The presence of the `AgentID` field makes the data model naturally support agent-level distinction.

#### 1.3.2 Core Function: `isAgentAlreadyRunning`

**File**: `internal/nats/consumer.go`

```go
// isAgentAlreadyRunning checks if the specified agent is already processing the given message.
// Key: Uses agent_id as the granularity; different agents can process the same message concurrently.
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

**Key Difference**: The WHERE clause includes `agent_id`, achieving agent-level deduplication.

#### 1.3.3 Check Location: `processAgentTarget`

**File**: `internal/nats/consumer.go`

Add the check **before** the `createRunningRecord` call in the `processAgentTarget` function:

```go
// Check if this agent is already processing this message (agent-level deduplication)
if isRunning, err := c.isAgentAlreadyRunning(
    group.GroupID, pendingMsg.MessageID, agentMember.MemberID, traceID,
); err != nil {
    return fmt.Errorf("failed to check agent running status: %w", err)
} else if isRunning {
    logger.WarnM(consumerModule, traceID,
        "agent already processing this message, skipping duplicate",
        "agent_id", agentMember.MemberID,
        "message_id", pendingMsg.MessageID,
    )
    return nil
}
```

**Why in `processAgentTarget` instead of `processMessage`**:
- In `processMessage`, the targets have not yet been parsed, so we don't know which agents to process
- In `processAgentTarget`, the specific `agentMember` is already determined, allowing precise checking of whether that agent is already processing

#### 1.3.4 Removed Incorrect Implementation

**Message-level deduplication (deleted)**:
```go
// Deleted: message-level duplicate check
// if isRunning, err := c.isMessageAlreadyRunning(groupID, messageID, traceID); ...
```

`isMessageAlreadyRunning` only checked `(group_id, message_id, status=running)`, missing `agent_id`, which caused different agents to be incorrectly skipped.

### 1.4 Supporting Mechanisms

#### 1.4.1 NATS AckWait Extension

**File**: `internal/nats/client.go`

```go
nats.AckWait(60*time.Minute),  // Greater than the default agent timeout of 600 seconds
```

#### 1.4.2 InProgress() Heartbeat

**File**: `internal/nats/consumer.go`

When processing a message, start a goroutine that calls `msg.InProgress()` every 20 seconds to reset NATS's AckWait timer:

```go
stopInProgress := make(chan struct{})
go func() {
    ticker := time.NewTicker(20 * time.Second)
    defer ticker.Stop()
    for {
        select {
        case <-ticker.C:
            msg.InProgress()
        case <-stopInProgress:
            return
        }
    }
}()
// ... processMessage ...
close(stopInProgress)
```

#### 1.4.3 Running Record Management

- **Creation**: In `processAgentTarget`, after acquiring the semaphore, check before `createRunningRecord`; create the running record only after confirming no duplicate
- **Update**: After agent execution completes, `recordProcessingStatus` updates the running record to completed/failed
- **Cleanup**: Completed/failed records are retained for auditing and deduplication purposes

### 1.5 Test Coverage

**File**: `internal/nats/consumer_duplicate_test.go`

#### Core Tests

| Test Name | Validation Content |
|-----------|-------------------|
| `TestIsAgentAlreadyRunning_DifferentAgentRunning` | **Key test**: When a1 is running, check a2 → returns `false` (allows concurrency) |
| `TestAgentLevelDeduplication_DifferentAgentsSameMessage` | Different agents on the same message should be allowed to process concurrently |
| `TestAgentLevelDeduplication_MultipleAgentsCanRun` | Multiple different agents can process the same message simultaneously |
| `TestAgentLevelDeduplication_SameAgentSameMessage` | Same agent on the same message should be deduplicated |

### 1.6 Design Principles Summary

> **Agent-level deduplication is one of the core constraints of ACS message processing.**
>
> 1. **Concurrency is the norm**: Multiple agents processing the same message simultaneously is a normal business scenario
> 2. **Deduplication must be precise**: Only block duplicate execution of the same agent on the same message
> 3. **Check at the right time**: Perform the check after the specific agent is determined but before creating the running record
> 4. **Granularity must be correct**: Database queries must include the `agent_id` condition

### 1.7 Related Files

- `internal/nats/consumer.go` - Core implementation
- `internal/nats/client.go` - NATS Consumer configuration
- `internal/nats/consumer_duplicate_test.go` - Unit tests
- `internal/models/agent_message_processing.go` - Data model
- [issues/issue-agent-duplicate-execution-on-long-running.md](../issues/issue-agent-duplicate-execution-on-long-running.md) - Detailed issue record

---

## Issue 2: [Reserved for Future Critical Issues]

> This section is reserved for documenting future critical issues and their design decisions.
>
> When adding a new issue, follow this template:
> ```markdown
> ## Issue N: [Issue Title]
>
> > **Corresponding Issue**: [link to issue file]
>
> ### N.1 Problem Background
> ...
>
> ### N.2 Core Design Decision
> ...
>
> ### N.3 Technical Implementation
> ...
>
> ### N.4 Supporting Mechanisms
> ...
>
> ### N.5 Test Coverage
> ...
>
> ### N.6 Design Principles Summary
> ...
>
> ### N.7 Related Files
> ...
> ```
