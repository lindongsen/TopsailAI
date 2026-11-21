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

# A sleep counter patched on the global `time` module measures every thread

## Symptom

`tests/unit/test_topsailai_utils_input_tool.py::TestInputFromPipe::test_writer_closed_without_data_does_not_busy_wait`
failed only in the full `tests/unit` run:

```
AssertionError: closed writer was polled 25 times
assert 25 == 0
```

The same test passed three consecutive isolated runs and passed when its own file
ran alone (61 passed).

## Evidence

- Isolated runs: 3/3 passed.
- Whole file: 61 passed.
- Full `tests/unit`: failed with a varying count (25 in the observed run).
- `grep -n "time\.sleep" utils/input_tool.py` returns nothing, so the function under
  test never calls `time.sleep` at all.
- `topsailai.utils.input_tool.time is time` -> `True`: the module attribute is the
  global `time` module, not a private alias.
- Probe with no background threads: `CALLS: []`.
- Probe with one leaked background sleeper thread: `CALL COUNT: 5`,
  `THREADS: ['leftover-sleeper']`.

## Root cause

The test patches `input_tool.time.sleep`, which is the process-wide `time.sleep`.
Every thread in the process is therefore intercepted, including background workers
left running by earlier tests in the same process. The counter measured foreign
threads, not the loop under test.

The assertion is correct in intent — a closed FIFO writer must return instead of
polling — but the measurement instrument was process-wide while the claim was
thread-local.

## Impact

- The test becomes a load-dependent coin flip: it passes whenever no other thread
  happens to sleep during the read.
- The failure looks like a product regression in `input_from_pipe`, which sends a
  future investigator into correct code.

## Fix

Count only calls made by the thread executing the test:

```python
test_thread = threading.current_thread()

def counting_sleep(seconds):
    if threading.current_thread() is test_thread:
        sleep_calls["count"] += 1
    real_sleep(seconds)
```

The docstring now states why the thread filter is required, so a future edit cannot
silently remove it.

## Verification

| Check | Result |
|---|---|
| Isolated run, 3 times | 3 passed |
| Whole file | 61 passed |
| Negative control: leaked background sleeper, fixed assertion | `COUNT: 0`, passed |
| Negative control: same probe before the fix | `CALL COUNT: 5` |
| Full `pytest tests/unit` | 14269 passed, 1 skipped, 0 failed |

## Regression scope

- Test-only change; `utils/input_tool.py` is untouched.
- The assertion still fails if the loop genuinely starts sleeping, because a real
  regression would sleep on the test thread.
- Other tests patching `time.sleep` through a module attribute have the same
  process-wide reach; they are safe only because they assert on a mock's call count
  rather than on a global side effect.
