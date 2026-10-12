---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
---

# Issue: Hooks Test Runner Parallel Resource and Deadline Contention

## Symptom

The mandatory parallel regression command reports concurrent-only Hooks failures:

```text
PYTHONDONTWRITEBYTECODE=1 python tests/run_tests.py --workers 20 --timeout 120 --retries 0
```

The run reports 10 failed files and 1 timeout, although the affected files pass in fresh single-file sequential execution.

## Evidence

The 20-worker run produced 325 files total: 314 passed, 10 failed, and 1 timeout. The following 11 files all passed in fresh, colorless, single-file sequential isolation, for an aggregate of 432 passed tests:

- `test_captured_module_worker.py`
- `test_hook_point_plan_capture.py`
- `test_module_stop_wiring.py`
- `test_module_worker_transport.py`
- `test_process_backend.py`
- `test_process_cleanup.py`
- `test_runtime_dispatch.py`
- `test_runtime_reload_settings_red.py`
- `test_script_runner_process.py`
- `test_simplified_configured_runtime.py`
- `test_summary_prepared_registration.py`

Under the parallel runner, expected results such as `success`, `invalid_output`, or `worker_lost` are replaced by deadline-related `timeout` outcomes. The symptoms disappear in fresh isolation, so they are not U8 behavior defects.

## Impact

The 20-worker full-regression signal is unreliable for the affected Hooks/process tests. Concurrent-only failures can obscure real regressions and delay acceptance despite passing isolated behavior.

## Recommended Follow-up

Authorize a dedicated test-runner reliability investigation covering shared process and scheduler capacity, deadline budgeting under parallel load, and test-runner isolation. The investigation must not weaken or alter U8 close-epoch or canonical candidate-plan provenance behavior merely to make concurrent runs pass.
