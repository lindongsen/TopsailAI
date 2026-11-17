---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
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

## Resolution (2026-11-17)

All three blind spots are fixed in the two test files. The fourth suggestion
(`filterwarnings`) is deliberately deferred; see below.

### What the status channel actually is

The issue proposed asserting `status: denied` in the denial message. Measurement
showed that is **not sufficient**: under `policy: deny` a policy timeout also
resolves to `STATUS_DENIED`, so both a human refusal and silence produce the
identical text `Tool '...' was not approved (status: denied).`

```
human deny  : status='denied' decision_by='user'    message=... (status: denied).
silence     : status='denied' decision_by='policy'  message=... (status: denied).
```

The channel that separates them is `instance.decision_by`: `"user"` for a human
answer, `"policy"` for a timeout resolution. The fix asserts `decision_by` and
keeps the message assertion as a secondary check.

### Blind spot 1: deny tests can now tell a refusal from silence

`tests/unit/test_topsailai_ai_base_tool_approval_decorator.py::test_ask_denied_raises`
and `tests/unit/test_topsailai_ai_base_tool_approval_integration.py::test_require_and_deny`:

- `time.sleep(0.05)` replaced with `transport.request_ready.wait(timeout=1)`, the
  pattern already used by `test_ask_denied_message_contains_rule_name`.
- Added `assert transport.instances[0].decision_by == "user"` and
  `assert "status: denied" in str(caught.value)`.

### Blind spot 2: the registry assertion runs on the main thread

`test_instance_registered_while_pending` now records the observation in the
worker (`observed.append(...)`) and asserts `observed == [1]` on the main thread
after `worker.join(timeout=1)`, plus `assert not worker.is_alive()` so a worker
that never ran cannot pass silently.

### Blind spot 3: the ask_again retry cycle is driven, not raced

`test_ask_again_then_approved` no longer sleeps 0.08s against a 0.05s timeout.
The transport's `wait_response` is wrapped to count waits and approve during the
second cycle, then asserts `len(waits) == 2` and `decision_by == "user"`. This
also proves the retry cycle actually happened, which the sleep version could not.

### Verification

| Check | Result |
|---|---|
| decorator + integration + matcher | 124 passed (1.24s) |
| all ten approval test files | 239 passed (7.69s) |
| `tests/run_tests.py` on both changed files | PASS, 24 cases, 0 failures |
| `-W error::pytest.PytestUnhandledThreadExceptionWarning` on both files | 24 passed |

Negative controls, each applied alone to a copy of the fixed file:

| Mutation | Result |
|---|---|
| deny resolver never answers | `test_ask_denied_raises` FAILED: `assert 'policy' == 'user'` |
| deny resolver never answers (integration) | `test_require_and_deny` FAILED: `assert 'policy' == 'user'` |
| registry observation `+ 999` | `test_instance_registered_while_pending` FAILED: `assert [1000] == [1]` |
| retry cycle never approves | `test_ask_again_then_approved` FAILED: `assert 'policy' == 'user'` |

Before the fix, the same two mutations left the tests **passing** (measured:
`2 passed, 17 deselected, 1 warning`). The tests now observe the behaviour they
claim to verify.

### Deferred: `filterwarnings`

The project has no pytest configuration file at all (no `pyproject.toml`,
`pytest.ini`, `setup.cfg`, or `tox.ini`), and no `filterwarnings` setting
anywhere. Promoting `PytestUnhandledThreadExceptionWarning` to an error is a
project-wide policy change that would affect every test file, so it is left as a
separate decision. The two files changed here already pass under that filter, so
enabling it later will not be blocked by them.

### Correction to the issue's file paths

The issue cited `tests/integration/.../test_tool_approval_integration.py:137` and
`tests/unit/.../test_tool_approval_decorator.py:224`. The real paths are
`tests/unit/test_topsailai_ai_base_tool_approval_integration.py` (the sleep was at
line 137) and `tests/unit/test_topsailai_ai_base_tool_approval_decorator.py` (the
sleep was at line 224). No `tests/integration/` copy of either file exists.
