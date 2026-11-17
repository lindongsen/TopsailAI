---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Issue: Tool Approval Integration Test `test_require_and_approve` Is Timing-Flaky

## Symptom

`tests/unit/test_topsailai_ai_base_tool_approval_integration.py::test_require_and_approve`
intermittently fails. The test expects the tool call to be approved, but the approval
gate sometimes resolves as `timeout` (denied by policy) instead.

Failure rate observed: roughly 1 run in 3 to 1 run in 8.

## Root Cause

`tests/unit/conftest.py` contains an autouse fixture (`fast_tool_approval_timeout`) that
sets `TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT=0.05` so the suite never blocks on a real
human prompt. The test itself spawns a thread that does `time.sleep(0.05)` and then calls
`instance.approve()`.

The wait budget (50 ms) and the approval delay (50 ms) are exactly equal, so the outcome
is decided purely by thread scheduling. Measured pre-wait latency in the waiting thread
was only 0.38–0.98 ms, leaving effectively zero margin.

## Evidence That This Is Pre-Existing, Not a Regression

Verified in an isolated `git worktree` checked out at pristine `HEAD` (no changes from the
approval-display task present, `PYTHONPATH` pointed at that worktree):

| Context | Runs | Result |
|---------|------|--------|
| Pristine `HEAD` worktree, single test | 8 | 3 failed / 5 passed |
| Working tree with approval-display changes, single test | 5 | 1 failed / 4 passed |

The same failure reproduces without any of the approval-display changes, so the display
work did not introduce it.

## Impact

- Non-deterministic unit-suite results; a green/red signal cannot be trusted for this file.
- Masks genuine regressions in the approval wait path and produces false alarms.

## Suggested Fix (requires human decision — not applied)

Any of the following, in order of preference:

1. Remove the fixed sleep from the test: have the approving thread wait on an
   `threading.Event` (or approve immediately after the request is observed) so the
   approval timing is decoupled from the wait budget.
2. Give the test an explicit, generous timeout via the rule/instance parameter instead of
   inheriting the autouse fixture default.
3. Lower the autouse fixture default further is **not** acceptable — it increases flakiness.

Option 1 is preferred because it removes the timing dependency entirely rather than
rebalancing two arbitrary constants.

## Scope Note

Deliberately left unfixed during the approval-display task: the fix touches a shared
autouse fixture or the test's concurrency design, which is outside that task's single
logical change.

## Analysis (2026-11-17)

### The reported symptom is already fixed

The preferred Option 1 repair was applied in commit `1d52a985 feat: add configured hook framework readiness` (2026-10-10). That commit added `MockTransport.request_ready` (set inside `send_request`) and replaced the approving thread's `time.sleep(0.05)` with `transport.request_ready.wait(timeout=1)`, so approval is now driven by the observed request instead of a fixed delay.

Executed evidence: `tests/unit/test_topsailai_ai_base_tool_approval_integration.py` ran 8 consecutive times, 5 passed each time, zero failures. The file completes in 0.22-0.49s.

### The same defect class survives in three sibling tests

The issue was scoped to `test_require_and_approve`, but the identical pattern remains elsewhere. Two of them are worse than flaky: they cannot fail at all.

| Test | File | Pattern | Real risk |
|---|---|---|---|
| `test_require_and_deny` | integration, line 137 | `time.sleep(0.05)` then resolve deny | Blind spot: passes on timeout too |
| `test_ask_denied_raises` | decorator, line 224 | `time.sleep(0.05)` then resolve deny | Blind spot: passes on timeout too |
| `test_ask_again_then_approved` | decorator, line 306 | `time.sleep(0.08)` vs timeout 0.05 | 0.02s margin on the late side |
| `test_instance_registered_while_pending` | decorator, line 335 | `time.sleep(0.02)` then assert in thread | Blind spot: in-thread assert cannot fail |

### Blind spot 1: a deny test cannot distinguish deny from timeout

`decorator.py:170` raises the same `ToolApprovalDeniedError` for both `STATUS_DENIED` and `STATUS_TIMEOUT`. A test whose rule policy is `deny` therefore passes whether the human denied the request or never answered at all.

Probe: a transport that mirrors `MockTransport` but never resolves the request, with `TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT=0.05` and policy `deny`, still raises `ToolApprovalDeniedError`. Patching the real `test_require_and_deny` so `deny_later` returns immediately also passes. The test asserts only `pytest.raises(ToolApprovalDeniedError)` and `len(calls) == 0`, never the status.

The status is available: `_build_denial_message()` emits `status: denied` versus `status: timeout`, and `test_ask_denied_message_contains_rule_name` already asserts `"status: denied" in message`. The two blind-spot tests simply do not use that channel.

### Blind spot 2: an assertion inside a thread cannot fail the test

`test_instance_registered_while_pending` performs `assert len(registry.list_pending_approvals()) >= 1` inside `check_registry`, which runs on a `threading.Thread`. pytest 8.4.2 converts an unhandled thread exception into `PytestUnhandledThreadExceptionWarning`, and this project has no `filterwarnings = error` configuration in any pytest config file, so the test still reports passed.

Probe: patching that assertion to `>= 999` (impossible) still yields `1 passed, 1 warning`. The registry assertion is dead code.

### Blind spot 3: the ask_again margin

`test_ask_again_then_approved` uses `timeout: 0.05` with policy `ask_again`. `wait_for_decision()` waits 0.05s, applies `ask_again` (returns `STATUS_PENDING`), then waits one more 0.05s cycle. Approval at 0.08s must therefore land inside the second window (0.05-0.10s). Arriving earlier is harmless because the first window also approves; arriving after 0.10s fails. The usable margin is 0.02s. Measured 20/20 passes, so it is currently stable but structurally fragile.

### Recommended repair, not applied

1. For the two deny tests, assert the status channel: capture the message and require `"status: denied" in message`, so a timeout can no longer masquerade as a denial. Alternatively drive resolution from `request_ready` as `test_require_and_approve` already does.
2. For `test_instance_registered_while_pending`, move the registry assertion onto the main thread. The main thread already observes the pending instance indirectly; assert `registry.get_pending_approval(...)` before the wait, or collect the thread's result into a list and assert after `join()`.
3. For `test_ask_again_then_approved`, resolve from `request_ready` and let the second wait cycle be the only timing dependency, or raise the rule timeout so the margin is not 0.02s.
4. Consider enabling `filterwarnings = error::pytest.PytestUnhandledThreadExceptionWarning` so this class of dead assertion cannot silently return.

No source or test code was changed in this analysis.
