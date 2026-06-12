---
maintainer: AI
programming_language: go
---

# Issue: Sliding Window Test Passes for Wrong Reason

## Description

The `TestEvaluateSlidingWindow` test in `internal/trigger/evaluator_test.go` passes, but not because the sliding window anti-trigger logic actually blocks a trigger. It passes because there is no manager-agent in the test setup, so auto-trigger cannot fire.

## Affected Code

File: `internal/trigger/evaluator_test.go`
Test: `TestEvaluateSlidingWindow`

```go
func TestEvaluateSlidingWindow(t *testing.T) {
    // ... creates 15 agent messages + 1 user message
    // The user message breaks the consecutive agent chain
    // Max consecutive agents in window = 10, which does NOT exceed threshold (>10)
    // But even if it did, there's no manager-agent for auto-trigger to fire
}
```

## Problem

1. The test does not include a manager-agent, so `evaluateAutoTrigger()` will always return `ShouldTrigger: false` regardless of sliding window.
2. The target message (user message) is inserted at position 15, breaking the consecutive chain. The max consecutive agents in the window is 10, which does NOT exceed the >10 threshold.
3. There is no test that verifies the sliding window ACTUALLY blocks a trigger that would otherwise fire.

## Suggested Fix

Create a new test case that:
1. Includes a manager-agent in the group members
2. Creates a scenario where >10 consecutive agent messages exist in the 20-message window
3. Has a valid trigger condition (e.g., a mention of the manager-agent)
4. Verifies that `ShouldTrigger` is `false` specifically because of the sliding window rule

Example setup:
- 12 consecutive agent messages
- 1 user message with @manager-agent mention (the target)
- 7 more agent messages
- The window around the target should contain >10 consecutive agents, blocking the trigger
