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
