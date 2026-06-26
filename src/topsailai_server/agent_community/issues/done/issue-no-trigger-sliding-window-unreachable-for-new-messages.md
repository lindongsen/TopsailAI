---
status: open
severity: medium
component: trigger
---

# NO_TRIGGER sliding-window rule is unreachable for new messages

## Summary
The `NO_TRIGGER_CASES` sliding-window rule ("more than 10 consecutive agent messages in a 20-message window") is documented in `docs/API.md`, `README.md`, and `ORIGIN.md` as a guard that prevents automatic agent triggers when a conversation has a long run of agent messages. During manual testing of Plan 03 Test Case 3.8, the rule never fired for a new user message even when more than 10 agent responses were produced in the recent history.

## Root cause
`internal/trigger/evaluator.go` builds the inspected window as:

```go
for i := start; i <= end; i++ {
    if i != targetIdx {
        window = append(window, filtered[i])
    }
}
```

The target message is excluded from the window. For a **newly created message**, the target is always the latest message in the group, so the "after" portion of the window is empty. The window therefore contains only the 10 messages immediately before the target. Because the target itself is excluded, a run of agent messages can never span across it, and the maximum possible consecutive-agent count in the window is **10**. The condition `maxConsecutive > 10` can never be satisfied for a new message.

The existing unit tests (`TestEvaluateSlidingWindow`, `TestEvaluate_SlidingWindowBoundary11`) pass only because they construct artificial `contextMessages` where the target is in the **middle** of the slice and agent messages exist on both sides. This scenario cannot be produced through normal API usage.

## Expected behavior
A new user message sent after a run of more than 10 agent responses should be suppressed by the sliding-window rule. For example:

1. Group contains a worker-agent.
2. Produce 11 consecutive agent messages (e.g. by mentioning 11 agents or by repeatedly triggering).
3. Send a new user message mentioning an agent.
4. The new message should **not** trigger an agent automatically.

## Actual behavior
The new user message always triggers the agent because the sliding-window condition can never be met for a message at the end of the stream.

## Reproduction steps
1. Start ACS with manager-agent auto-join enabled (`ACS_GROUP_MANAGER_AGENT_CMD_CHAT=mock_agent_cmd_chat.sh`).
2. Create a group with User A and User B (to avoid single-user auto-trigger).
3. Add a worker-agent with a passing health check (`cmd_check_health: mock_agent_cmd_check_health_noop.sh`).
4. Send 12 user messages and manually trigger each one with `agent_id=worker-agent`, producing 12 agent responses.
5. Send a new user message mentioning `@worker-agent`.
6. Observe that an additional agent response is created, proving the rule did not suppress the trigger.

## Impact
- The documented anti-loop protection is effectively dead for the most common trigger path (new user messages with mentions).
- Long agent-driven conversations can continue to cascade agent triggers indefinitely in edge cases.

## Suggested fix
Include the target message in the inspected window (or check the last 20 messages overall). With the target included, a run of 11 agent messages immediately before a user target would be counted as a run of 11 and correctly suppress the trigger. The target being a user message would simply terminate the run without reducing the count of the preceding run.

## Verification needed
- Unit test: 11 consecutive agent messages before a user target suppresses trigger.
- Unit test: exactly 10 consecutive agent messages before a user target still allows trigger.
- Manual test: reproduce the scenario above and confirm suppression.

## References
- `docs/API.md` — Agent Triggering > NO_TRIGGER_CASES
- `README.md` — Agent Trigger Mechanism > NO_TRIGGER Cases
- `ORIGIN.md` — How to trigger agent > NO_TRIGGER_CASES
- `internal/trigger/evaluator.go` (`isLoopMessage`)
- `internal/trigger/evaluator_test.go`
