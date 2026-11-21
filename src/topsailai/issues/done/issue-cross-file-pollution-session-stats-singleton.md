---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: done
---

# Cross-file pollution: a real `AgentChat.run` leaves the stats singleton alive

## Symptom

Running `pytest tests/unit/workspace` in one process failed 18 tests, while every
affected file passed when run alone:

- `test_session_stats_service.py` -> 17 failures
- `test_session_stats_integration.py` -> 1 failure

All of them raised the same error from the constructor:

```
RuntimeError: stats writer already owned by this process
  workspace/session_stats_service.py:176
```

## Evidence

- Each file alone: `test_session_stats_service.py` 64 passed,
  `test_session_stats_integration.py` 17 passed.
- The three files together (service + integration + input_tool): 142 passed, so the
  polluter is not among them.
- Directory bisection over `tests/unit/workspace`: only `plugin_instruction`
  reproduced it (17 failed / 167 passed).
- File bisection inside `plugin_instruction`: only `test_hosting.py`
  (17 failed / 76 passed).
- Test bisection inside `test_hosting.py`: only
  `test_session_exit_does_not_close_instruction` (1 failed / 3 passed).
- Probe: after that test, `session_stats_service._service` and `_owner_ref` both
  still pointed at a live `StatsService`; a following direct construction raised
  the same `RuntimeError`.

## Root cause

`test_session_exit_does_not_close_instruction` builds a fake chat object and calls
the **real** `AgentChat.run`. That method calls `process_service(...)` at its start
(`workspace/agent/agent_shell_base.py:344`), which creates a process-wide
`StatsService` singleton stored in the module globals `_service` and `_owner_ref`.

`AgentChat.run`'s `finally` block closes only `self._stats_binding`; it never
retires the process service, because in production the service is meant to live for
the whole process. `StatsService.__new__` therefore keeps rejecting every later
direct construction in the same process.

This is correct production behavior. The defect is that a unit test drives a
process-lifetime singleton and no test-level isolation restores it.

## Impact

- Any single-process pytest invocation that runs `test_hosting.py` before the stats
  tests reports 18 false failures.
- `tests/run_tests.py` (one process per file) hides the problem, so CI stayed green.

## Fix

Added an autouse fixture `reset_session_stats_singleton` in `tests/unit/conftest.py`.
After each test it stops the live service (best effort), clears `_service` and
`_owner_ref`, and rebuilds `_owner_pid`, `_bootstrap_lock` and `_owner_lock` for the
current process. Production code is unchanged, so the one-writer guard keeps its
full strength.

## Verification

| Check | Result |
|---|---|
| `pytest tests/unit/workspace` before fix | 18 failed / 922 passed |
| `pytest tests/unit/workspace` after fix | 940 passed |
| `pytest tests/unit/workspace tests/unit/test_topsailai_utils_input_tool.py` | 1001 passed |
| Full `pytest tests/unit` after fix | 14269 passed, 1 skipped, 0 failed |
| Probe: real `AgentChat.run` then direct `StatsService()` | passes after reset, raised before |

## Regression scope

- Test-only change; no production module was modified.
- The reset runs after every unit test, so it also protects future tests that drive
  `AgentChat.run` for unrelated reasons.
- `tests/run_tests.py` behavior is unchanged because each file already gets its own
  process.
