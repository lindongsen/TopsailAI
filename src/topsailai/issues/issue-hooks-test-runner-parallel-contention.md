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

## Reproduced again on 2026-11-17

The contention is still live at HEAD `5da6bb49f651a501b041486590a0c87e5acd85c6`. Same eleven files, same runner, two modes:

| Mode | Result |
|---|---|
| `--workers 20` | **9 failed, 2 passed**, 30 failed cases out of 432 records |
| `--sequential` | **9 passed, 0 failed**, 308 cases |

The nine files that fail concurrently all pass sequentially, which reproduces the reported
symptom exactly and confirms it is scheduler/deadline contention rather than a Hooks behavior
defect. `test_summary_prepared_registration.py` and `test_hook_point_plan_capture.py` passed in
both modes this time, so the affected set is not fixed.

This issue remains open because the recommended follow-up is a dedicated test-runner reliability
investigation, which has not been authorized.

## Investigation on 2026-11-18: one file fixed, systemic contention confirmed and still open

A single-file root cause was proven and fixed; the broader contention was reproduced and
measured, and it is **not** resolved by that fix. This issue therefore stays open.

### Fixed: `test_script_runner_process.py` deadline could not absorb process startup

`test_exited_leader_with_descendant_only_result_writer_retains_debt` used `timeout=0.1`.
The execution deadline is absolute and is computed **before** the child is spawned, so
interpreter startup is charged against the budget. Measured child startup is 26.2–28.3 ms
idle (10 runs, median 26.6 ms), but 38 ms under parallel load, leaving only ~62 ms for the
leader to exit.

Transport evidence from the same test, same code, differing only in machine load:

| Condition | `transport_enter_remaining_ms` | `exit_code` | Result |
|---|---|---|---|
| Idle | 98.47 of 100 | `0` | pass |
| 24-process CPU load | 61.84 of 100 | `null` | fail |

`hooks/process_transport.py::_stop_before_settlement()` polls `process.poll()` and then
`_observe_stop_facts()` returns True once `time.monotonic() >= deadline`, so an expired
deadline wins over an already-reaped leader.

Fix: `timeout=0.1` → `timeout=0.2`, which stays above startup (26–38 ms) and below the
descendant's 0.3 s sleep, so every existing assertion still holds. Verified under load
(`transport_enter_remaining_ms` 156.0 of 200, `exit_code: 0`, pass) and idle (pass).
Negative control: reverting to 0.1 under the same load reproduced the original failure
(61.2 ms remaining, `exit_code: null`). Committed as `5ab1e6c3`.

### Still open: nine files fail under load with the same signature

The eleven files were re-run at `--workers 20 --timeout 120 --retries 0` under a
24-process CPU load:

| Condition | Result |
|---|---|
| Idle | Total=11, Passed=11, Failed=0, 432/432 cases |
| 24-process CPU load | **Total=11, Passed=2, Failed=9**, 394/432 cases, 38 failures |

All 38 failures carry the same signature, `assert 'timeout' == 'success'` (or
`'timeout' == 'error'`, `'timeout' == 'invalid_output'`), which matches the symptom
described above. The failing files are `test_captured_module_worker.py`,
`test_module_stop_wiring.py`, `test_module_worker_transport.py`, `test_process_backend.py`,
`test_process_cleanup.py`, `test_runtime_dispatch.py`, `test_runtime_reload_settings_red.py`,
`test_script_runner_process.py`, and `test_simplified_configured_runtime.py`.
`test_hook_point_plan_capture.py` and `test_summary_prepared_registration.py` passed.

This reproduces the 2026-11-17 report (9 failed, 2 passed) exactly, and it shows the
affected set is load-dependent rather than fixed.

### Why the remaining work needs authorization

The failing tests assert completion inside tight millisecond budgets — observed values
include `timeout_ms=2`, `timeout_ms=3`, `timeout=150`, `timeout_ms=900`, and
`budget_ms=2250`. Under parallel load, process spawn alone can exceed several of these.

Two different repairs are possible and they are not equivalent:

1. **Test-side**: widen each tight budget so it absorbs spawn overhead, as done for the one
   file above. This is mechanical but touches many files and weakens the timing precision
   each test was written to assert.
2. **Production-side**: treat the tight deadlines as a real design limit that cannot survive
   a loaded host, and change the deadline policy itself. This alters runtime behavior and
   must not weaken U8 close-epoch or canonical candidate-plan provenance behavior.

Choosing between them, and deciding how much timing precision each test may give up, is the
dedicated test-runner reliability investigation this issue already says has not been
authorized. No production code was changed in this phase.

### Environment note

This host has 8 CPUs. `--workers 20` exceeds the core count, so the runner itself
oversubscribes the machine before any test-level load is added. The runner's
`DEFAULT_WORKERS` is 4 (set by `f996e78c`), and `--workers 20` appears only in issue and
`.task/` documents, not in `test.md` or any project configuration file.

## Investigation on 2026-11-18: external CPU load, not runner parallelism, is the cause

The earlier sections attribute the failures to runner parallelism and scheduler contention.
A controlled experiment shows that attribution is wrong: **sequential execution under the same
external load fails the same way**. Every number below came from a command executed in this
workspace.

### Method

Eleven affected files, selected by their `tests/unit`-relative paths, run through
`tests/run_tests.py` in four conditions. External load was 24 CPU-burning processes on an
8-CPU host, kept alive for 900 s so it outlasted each run; liveness was re-checked after the
run finished.

### Results

| Condition | Files passed | Cases | Failures |
|---|---|---|---|
| Idle, `--workers 20` | 11 / 11 | 432 / 432 | 0 |
| 24-process load, `--workers 20` | 0 / 11 | 255 / 337 | 82 |
| 24-process load, `--workers 4` | 1 / 11 | 265 / 337 | 72 |
| 24-process load, `--sequential` | 1 / 11 | 275 / 337 | 62 |

Reducing workers from 20 to 4 changed failures from 82 to 72, and removing parallelism
entirely changed them to 62. Parallelism therefore contributes only a small part of the
effect; the dominant factor is the external load itself.

### Per-file slowdown

| File | Idle | Load | Ratio |
|---|---|---|---|
| `test_module_stop_wiring.py` | 5.1 s | 26.9 s | 5.3x |
| `test_process_cleanup.py` | 6.8 s | 29.5 s | 4.4x |
| `test_script_runner_process.py` | 7.1 s | 32.7 s | 4.6x |
| `test_runtime_reload_settings_red.py` | 7.2 s | 39.5 s | 5.5x |
| `test_runtime_dispatch.py` | 12.8 s | 60.4 s | 4.7x |
| `test_captured_module_worker.py` | 14.0 s | 62.1 s | 4.4x |
| `test_summary_prepared_registration.py` | 14.2 s | 78.2 s | 5.5x |
| `test_simplified_configured_runtime.py` | 14.9 s | 75.0 s | 5.0x |
| `test_process_backend.py` | 18.4 s | 71.5 s | 3.9x |
| `test_module_worker_transport.py` | 22.9 s | 117.5 s | 5.1x |
| `test_hook_point_plan_capture.py` | 44.7 s | 120.1 s | 2.7x |
| **Total** | **168.1 s** | **713.5 s** | **4.2x** |

A uniform 4–5x wall-clock inflation is the signature of CPU starvation, not of a scheduling
bug in the runner. The tests assert completion inside millisecond budgets, so a 4x slowdown
converts expected outcomes into `timeout`.

### Failure signatures

From the JUnit evidence of the loaded run:

```
30  assert 'timeout' == 'success'
 2  assert 'timeout' == 'invalid_output'
 2  assert 'timeout' == 'error'
 2  assert 'success' == 'timeout'
```

The last class is the reverse direction: `test_concurrent_protocol_selection` asserts
`old.status == new.status == 'success'` and observed one side as `timeout`, so the two
concurrent protocol selections disagreed. That is a genuine timing-sensitivity in the test,
not merely a budget that is too small.

A second, distinct failure appeared in the same file:
`test_post_validation_deadline` raised
`FileNotFoundError: .../basetemp/test_post_validation_deadline0/import.pid`, meaning the
worker never wrote its import marker before the deadline expired. This is the same root cause
observed from the other side.

### Correction to the earlier attribution

The 2026-11-17 section concluded that the failures are "scheduler/deadline contention rather
than a Hooks behavior defect". The first half is right and the second half is right, but the
implied cause is wrong: the contention is **host CPU starvation**, which the runner neither
creates nor can avoid. `--workers 20` on an 8-CPU host does oversubscribe, but the experiment
shows that even one worker at a time fails when 24 external processes compete for the same
cores.

### Consequence for the two proposed repairs

The earlier section offered a test-side repair (widen budgets) and a production-side repair
(change the deadline policy). The measurement adds a third, cheaper option that neither
requires weakening assertions nor changing runtime behavior:

1. **Runner-side**: cap effective workers at the available CPU count, so the runner cannot
   oversubscribe the host on its own. This addresses only the runner's own contribution,
   which the experiment shows is the smaller part.
2. **Test-side**: widen the tight budgets by the measured 4–5x factor. This is mechanical and
   preserves every assertion's meaning, but it weakens the timing precision each test was
   written to assert.
3. **Production-side**: treat the tight deadlines as a design limit that cannot survive a
   loaded host. This changes runtime behavior and must not weaken U8 close-epoch or canonical
   candidate-plan provenance behavior.

None of these is authorized, and the choice between them is still the dedicated test-runner
reliability investigation this issue says has not been authorized. What the measurement does
establish is that the failures are **environmental**, so a green run on an idle host and a red
run on a loaded host describe the same code.

### Environment note

This host has 8 CPUs. The runner's `DEFAULT_WORKERS` is 4 and it has no CPU-count cap, so
`--workers 20` oversubscribes by 2.5x before any test-level load is added.
