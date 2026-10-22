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

# Session metadata BDD naming worker does not exit

## Symptom

`tests/bdd/test_session_meta_name.py` failed during child cleanup with an assertion that a naming worker did not exit within the 10-second join.

## Reproduction

Run `pytest -q --color=no --tb=line --disable-warnings tests/bdd/test_session_meta_name.py` from the workspace.

## Evidence

The root cause is confirmed in the BDD harness, not production code. The child patched the shared `threading` module through `ctx_manager.threading.Thread = <TrackedThread>`. This also captured the resident `session-stats` service thread created at `workspace/session_stats_service.py:207-208`. That thread exits only after `stop()` at `workspace/session_stats_service.py:291-296`; otherwise it continues its `idle.wait(0.01)` loop at `workspace/session_stats_service.py:277-281`. Cleanup joined every captured thread with `join(10)`, so it waited on a non-naming thread and could report a naming-worker cleanup failure, potentially twice. The actual `_async_update_session_name` worker exited normally.

Classification: BDD harness defect; no production defect was found.

## Impact

This blocked BDD acceptance for the hostname metadata change because the naming and startup-context assertions could not reliably complete.

## Resolution

Both affected child harnesses now use a consumer-local threading proxy, capture only the exact `_async_update_session_name` target before thread start, join only naming workers with the existing 10-second timeout, and preserve exception-safe cleanup.

- Commit `dcb98a144da674dd9b05517494461aa69b9dd056` fixed `tests/bdd/session_meta_name_child.py`.
- Commit `bcb00a2119c4cb23741c1350c5bac5237001a103` fixed `tests/bdd/session_name_startup_context_harness.py`, including its embedded child script.

No production code was changed.

## Verification

- `tests/bdd/test_session_meta_name.py`: 1 passed.
- `tests/bdd/test_session_name_startup_context.py`: 4 passed on each of two independent reruns; the prior result was 2 failed, 2 passed.
- Hostname unit tests: 23 passed and 18 passed, 41 passed total.
- `git diff --check`: passed.

## Status

Done. The confirmed BDD harness defect was fixed in both child implementations and verified without changing production behavior.
