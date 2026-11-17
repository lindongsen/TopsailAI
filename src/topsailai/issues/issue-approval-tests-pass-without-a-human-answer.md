---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: open
---

# Approval tests pass even when no human ever answers

## Symptom

Four approval tests cannot distinguish the behaviour they claim to verify from
the behaviour they are meant to exclude. Two of them pass when the approval
transport never resolves at all, one asserts inside a worker thread where the
failure is discarded, and one has a 0.02s timing margin.

The reported flakiness in `issue-approval-integration-approve-race` was already
fixed by `1d52a985` (8/8 runs passed). These are the sibling defects that the
same fix did not reach.

## Root cause

### Blind spot 1: deny tests cannot tell a refusal from silence

`ai_base/tool_approval/decorator.py:170` raises the same
`ToolApprovalDeniedError` for `STATUS_DENIED` and `STATUS_TIMEOUT`. Both
`test_require_and_deny` (`tests/integration/.../test_tool_approval_integration.py:137`)
and `test_ask_denied_raises` (`tests/unit/.../test_tool_approval_decorator.py:224`)
assert only `pytest.raises(ToolApprovalDeniedError)` plus `len(calls) == 0`, so a
timeout satisfies them identically.

Measured: replacing the real `deny_later` with a transport that never resolves
left `test_require_and_deny` **passing**.

### Blind spot 2: an assertion inside a thread never fails the test

`test_instance_registered_while_pending` (`test_tool_approval_decorator.py:335`)
runs `assert len(registry.list_pending_approvals()) >= 1` in a child thread.
pytest 8.4.2 converts that into `PytestUnhandledThreadExceptionWarning`, and no
pytest configuration promotes it to an error.

Measured: changing the assertion to `>= 999` still produced
`1 passed, 1 warning`.

### Blind spot 3: a 0.02s window

`test_ask_again_then_approved` (`test_tool_approval_decorator.py:306`) uses
`timeout: 0.05` with policy `ask_again`, so `wait_for_decision()` waits 0.05s,
times out, then waits again. The approval arrives after `sleep(0.08)`, which must
land inside 0.05–0.10s. Twenty consecutive runs passed, but the margin is 0.02s.

## Impact

The deny path is the security-relevant branch: it decides whether a tool call is
blocked. A regression that turned a real refusal into a silent timeout, or that
stopped registering pending approvals, would not be caught by these tests.

## Suggested fix

1. Assert the status channel instead of only the exception type. The denial
   message already carries it: `_build_denial_message()` emits `status: denied`
   or `status: timeout`, and `test_ask_denied_message_contains_rule_name` already
   asserts `"status: denied" in message`. Reuse that channel in both deny tests.
2. Move the registry assertion back to the main thread, or collect the thread
   result and assert after `join()`.
3. Drive `test_ask_again_then_approved` with `request_ready` like
   `test_require_and_approve`, or widen the rule timeout so the margin is not
   0.02s.
4. Consider enabling
   `filterwarnings = error::pytest.PytestUnhandledThreadExceptionWarning` so a
   dead thread assertion cannot return silently.

## Discovered while

Reviewing `issue-approval-integration-approve-race` on 2026-11-17. That issue's
own symptom was already fixed and it was archived to `done/`; these findings are
the residual scope it did not cover.
