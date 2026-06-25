---
status: fixed
severity: medium
component: trigger
---

# NO_TRIGGER_CASES sliding window does not exclude deleted messages

## Summary
`NO_TRIGGER_CASES` rule #3 in `ORIGIN.md` and `docs/API.md` states that a message should not trigger agents if, within the 10 messages before and 10 messages after it **excluding deleted messages**, there is a sliding window of more than 10 consecutive messages whose sender type ends with `-agent`.

The implementation in `internal/trigger/evaluator.go` (`isLoopMessage`) did not exclude deleted messages when building the 20-message sliding window. This has been fixed.

## Fix
- `internal/trigger/evaluator.go`: `isLoopMessage` now filters out messages where `is_deleted = true` or `delete_at_ms > 0` before locating the target message and before building the 10-before/10-after window. The consecutive-agent check runs only over this filtered window.
- `internal/api/handlers/message.go`: `evaluateAndTrigger` now also adds `AND is_deleted = ?` to the database query as an optimization, while keeping the authoritative filter inside `isLoopMessage`.
- `internal/trigger/evaluator_test.go`: Added three new unit tests:
  - `TestEvaluate_SlidingWindowExcludesDeletedAgentMessages`
  - `TestEvaluate_SlidingWindowExcludesDeletedNonAgentMessages`
  - `TestEvaluate_TargetMessageDeleted`

## Verification
- `go test ./internal/trigger/... -count=1` passes.
- `go test ./internal/... -count=1` passes with no regressions.

## References
- `ORIGIN.md` "How to trigger agent" > NO_TRIGGER_CASES
- `docs/API.md` "Agent Triggering" > NO_TRIGGER_CASES
- `internal/trigger/evaluator.go`
- `internal/api/handlers/message.go`
- `internal/trigger/evaluator_test.go`
