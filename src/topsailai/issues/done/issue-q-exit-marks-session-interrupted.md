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

# Issue: Typing `q` to exit leaves the session meta as `interrupted`

## Symptom

A user ends an interactive agent session by typing `q`. The session metadata file
records `status: interrupted` instead of `status: completed`, even though the user
ended the session deliberately and the process exited with code `0`.

Observed on host `topsail` on 2026-11-14:

| Session meta | Status | start_ts | end_ts |
|---|---|---|---|
| `wa-c2a6583cd3e3.122064.session.meta` | `interrupted` | 2026-11-14T08:26:43 | 2026-11-14T23:04:05 |
| `wa-8200a8632652.3904023.session.meta` | `interrupted` | 2026-11-14T17:45:19 | 2026-11-14T22:56:52 |
| `topsailai.1590161.session.meta` | `completed` | 2026-11-14T23:03:53 | 2026-11-14T23:03:53 |

The long interactive sessions are `interrupted`; the short one-shot runs are
`completed`. The difference is the exit path, not the duration.

## Root cause

`q` is an exit command, and the exit command raises `SystemExit`, which is a
`BaseException` and therefore bypasses the `except Exception` handler that owns the
normal completion write.

1. `utils/instruction_tool.py:30` declares
   `DESCRIPTION_EXIT_SET = ["exit", "quit", "/exit", "/quit", "q"]`.
2. `utils/instruction_tool.py:606-607` calls `sys.exit(0)` for any message in that
   set, raising `SystemExit`.
3. `workspace/input_tool.py:93` forwards the call unchanged, so `SystemExit`
   propagates out of `input_message()` and out of `AgentChat._run()`.
4. `workspace/agent/agent_shell_base.py:306` sets `completed = False`.
   `completed = True` is only reached at line 323, after `self._run(...)` returns.
   The handler at line 325 is `except Exception`, which does not catch
   `SystemExit`, so line 323 is never executed.
5. The `finally` block at line 350 guards the status write with `if completed:`
   (line 351). Because `completed` is still `False`, `update_session_meta_status`
   is never called and the metadata keeps `status: running`.
6. `workspace/session_meta.py:267` registered `_finalize_on_exit` through
   `atexit`. That handler (lines 273-288) rewrites any metadata still in
   `STATUS_RUNNING` to `STATUS_INTERRUPTED` and stamps `end_ts`.

So the `interrupted` value is produced by the `atexit` fallback, not by the agent
loop. The fallback is behaving exactly as designed; the defect is that a normal
user exit never reaches the completion write, so the fallback cannot tell a
deliberate exit from a crash.

## Evidence

Probe 1 — the exit command raises `SystemExit`:

```
PROBE: SystemExit propagated, code = 0
```

`input_message()` was called with `_input` stubbed to return `"q"`.

Probe 2 — `AgentChat.run()` leaves the metadata untouched:

```
PROBE SystemExit propagated, code = 0
PROBE status inside process after run(): running
```

`AgentChat._run` was patched to raise `SystemExit(0)`.

Probe 3 — `atexit` converts the leftover `running` into `interrupted`:

```
FINAL status = interrupted
FINAL end_ts = 2026-11-14T23:16:41.390554
```

The same probe sequence without the `SystemExit` leaves `completed`, which
confirms the exit path is the only difference.

## Impact

- `interrupted` is documented as the abnormal-termination state, so a deliberate
  exit is recorded as if the process had crashed.
- `cli/cli_topsailai/formatting.py:204` and `cli/cli_topsailai/log_files.py:477`
  treat only `status == "completed"` as completion evidence. A session ended with
  `q` therefore never gets the DONE marker and is not filtered by
  `include_completed`, so it keeps appearing as an unfinished row.
- `context/session_activity.py:43` accepts `interrupted` as cleanable, so cleanup
  still works; the damage is to reporting and to the meaning of the field.

## Proposed fix

Catch `SystemExit` in `AgentChat.run()` so the completion write happens before the
exit propagates. The minimal shape is to treat a `SystemExit` raised by `_run` as a
normal end of the session: set `completed = True` and re-raise so the process still
exits with the requested code. `error` and `interrupted` must keep their current
meaning for genuine failures.

A regression test must assert that a `SystemExit` raised inside `_run` leaves the
metadata as `completed`, with a negative control proving the unpatched code yields
`interrupted`.

## Open question

Whether a user-initiated exit deserves its own status value instead of reusing
`completed`. `update_session_meta_status` currently documents only `completed`,
`error`, and `interrupted`, and the CLI completion filters key on `completed`, so
reusing `completed` is the smallest change that restores correct reporting.

## Resolution

Status: RESOLVED on 2026-11-14.

Decision: reuse `completed` for a deliberate exit command. The Human approved this
option, so `error` and `interrupted` keep their existing meaning for genuine failures
and the CLI completion filters need no change.

Implementation: `workspace/agent/agent_shell_base.py::AgentChat.run()` gained one
`except SystemExit:` branch immediately before the existing `except Exception` handler.
It sets `completed = True` and re-raises, so the completion write in `finally` runs and
the requested exit code still propagates. `KeyboardInterrupt` is deliberately not
handled there, because an interrupted run must keep reporting `interrupted`.

Verification evidence:

- New regression file `tests/unit/test_topsailai_workspace_agent_agent_shell_base_exit_command.py`
  with six tests: exit code 0 and 3 both record `completed` and propagate the code, no
  `error` or `interrupted` status is written, `KeyboardInterrupt` still skips the
  completion write, an ordinary exception still records `error`, and teardown still runs.
- Fixed tree: 6 passed.
- Negative control at pristine `HEAD` `25af311a` in an isolated worktree with explicit
  `PYTHONPATH` and a verified imported-module path: the two exit-code tests failed, the
  four behaviour-preservation tests passed. This proves the tests observe the defect.
- Sibling regression: 141 tests across the eight related files passed.
- Real-file end-to-end probe with the real metadata writer and the real `atexit`
  fallback: status was `running` before the run, `completed` inside the process after
  `SystemExit` propagated with code 0, and still `completed` with an `end_ts` after the
  process exited. The fallback no longer rewrites the status.

Temporary resources were removed and the deletions were logged: the owned worktree, the
probe home directory, and the task-scoped temporary directory.
