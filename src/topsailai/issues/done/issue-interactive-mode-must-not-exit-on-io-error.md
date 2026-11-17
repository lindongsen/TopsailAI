---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: resolved
---

# Issue: Interactive mode must not exit on IO or database errors

## Symptom

Interactive agent sessions die outright on an IO or database error instead of
returning control to the user. On 2026-11-14 three sessions were killed by
`sqlite3.OperationalError: database or disk is full`:

| Session | Time | Host |
|---|---|---|
| `wa-a1ad42ea0a3f` | 05:52:48 | ai-dev |
| `wa-ecd67a6e691e` | 06:14:35 | topsail |
| `wa-a79cafc1f220` | 06:14:48 | topsail |

Each crash left a meta file stuck at `status: running` with `end_ts: null`,
because the process was terminated without running its finalizer.

## Evidence

- `utils/db_io_tool.py:229 handle_write_failure` classifies the failure, logs at
  `critical`, then calls `_exit_process(1)` at line 248 unconditionally.
- `utils/db_io_tool.py:219 _exit_process` calls `os._exit(code)` at line 226.
- `workspace/session_meta.py:261` registers `atexit.register(_finalize_on_exit, path)`.
  `os._exit` bypasses `atexit` entirely, so `_finalize_on_exit` never runs and the
  meta file keeps `STATUS_RUNNING` (`workspace/session_meta.py:31`).
- The interactive-mode predicate already exists at
  `utils/env_tool.py:138 is_interactive_mode()` and defaults to `True`
  (`TOPSAILAI_INTERACTIVE_MODE` unset or not `"0"`), but `handle_write_failure`
  never consults it.
- The end-of-turn wait position is `workspace/input_tool.py:39 INPUT_TIPS`
  (`>>> Your Turn: (pid=...)`), reached from the agent loop at
  `workspace/agent/agent_shell_base.py:495` and the prompt call at `:497-499`.
- The resulting ghost cannot be reaped: `context/session_activity.py:42`
  `_CLEANABLE_OWNER_STATUSES` contains only `completed`, `error`, `interrupted`,
  and `:268` therefore refuses to clean a `running` owner.

## Required Behavior

In interactive mode, any IO error or database error MUST NOT terminate the
process. It MUST return to the end-of-turn position that waits for user input,
that is the `>>> Your Turn` prompt at the end of one completed agent loop
iteration. The user keeps the session and can decide what to do next.

`os._exit` remains the last-resort fallback, and only for the non-interactive
path where no user is present to recover the turn.

Preserving the meta file on the abnormal path is expected, correct, and
important. The meta file MUST be retained, not deleted, so the abnormal exit
stays observable. The stdout file MUST also be retained, so the turn history
survives the fault and the user can inspect what happened.

## Impact

An interactive session is killed instead of handing control back. The user loses
the turn boundary and must resume manually. Every crash also leaves an
unreapable `running` ghost, so the session inventory accumulates entries that no
cleanup path is authorized to remove.

## Resolution

Resolved. The interactive contract and the non-interactive fallback are both
implemented, and the fallback is now restored after an earlier revision removed
it entirely.

The earlier revision removed the exit path from the write-failure handler and
never terminated the process. That satisfied the interactive requirement but
broke the non-interactive one: a run whose committed write failed printed a
failure answer and returned normally, so the entry point exited with code `0`
and a lost write looked like success to a script, a CI job or the launcher. The
fallback is required precisely because a non-interactive caller has no human to
recover the turn.

Implemented behavior:

- `utils/db_io_tool.py` never terminates the process. `handle_write_failure`
  logs at `critical` and re-raises, so the decision belongs to the caller.
- `workspace/agent/agent_shell_base.py` resolves the database I/O failure from
  the exception chain and branches on interactivity and thread ownership.
- `DB_IO_FALLBACK_EXIT_CODE = 1` and `_exit_after_db_io_failure` provide the
  last-resort exit for the non-interactive main-thread path.

Behavior matrix:

| Caller | Behavior |
|---|---|
| Interactive, main thread | Warn, print the already-produced answer, return to the input prompt, restore the turn budget |
| Non-interactive, main thread | Print an explicit failure answer, flush both streams, `os._exit(1)` |
| Worker thread, any mode | Abandon only this turn, never finalize the metadata, never terminate the process |

Why the fallback must NOT rewrite the metadata: `os._exit` is an abnormal
termination, so the on-disk scene is the evidence. The metadata keeps the state
the failure left it in, which is `running` with `end_ts: null`. That state is
exactly what proves the process died without finalizing, and it is what makes
the abnormal exit observable afterwards. Rewriting it to `error` would fabricate
a finalized record after the fact and erase the only trace that the exit was
abnormal. The fallback therefore only flushes `sys.stdout` and `sys.stderr`, so
the `TeeOutput` artifact keeps the bytes already produced up to the exit
instant. Flushing delivers buffered bytes; it never invents state. Neither
artifact is ever removed, and the flush is wrapped so a flush failure cannot
block the non-zero exit.

An earlier revision of this fix wrote `error` metadata inside the fallback. That
was wrong for the reason above and has been reverted: the fallback now takes no
session identity at all, so it cannot touch the metadata even by accident.

Corrections to this issue's original text:

- The end-of-turn prompt is at `workspace/agent/agent_shell_base.py:782-784`, not
  at `:495` and `:497-499`. Line 495 is the loop header and 497-499 is the
  hard-interrupt branch.
- The crash table conflated session identifiers with process identifiers. The
  05:52:48 crash belonged to process `3552162`, not `1030280`.
- All three crashes originated from a token-counter write, not from a
  conversation message write. Treating every write as equally fatal is what made
  a lost counter kill a usable session.
- The stdout-retention claim could not be verified for the recorded incident,
  because that session directory contained no stdout file.

## Verification

Completed:

- An interactive session survives an injected database I/O failure and returns to the
  input prompt, with the already-produced answer printed.
- A non-interactive run exits with code `1` after flushing both streams, so a lost write
  never looks like success.
- A worker thread abandons only its own turn, never finalizes the metadata of the live
  session, and never terminates the process.
- A failure while persisting the answer keeps the answer and continues the session.
- The fallback never reads or writes the metadata, so an unavailable metadata store
  cannot block the non-zero exit.
- Session metadata, stdout and event records are retained on normal exit, on SIGTERM,
  and on a failed write.
- `tests/unit/test_topsailai_workspace_agent_agent_shell_base_db_io.py` and
  `tests/unit/test_db_write_io_policy.py` pass, 66 tests, including assertions on the
  exit code, the metadata being left untouched, and the flush order.
- BDD coverage exists in `tests/bdd/features/db_io_failure_interactive_survival.feature`
  with four scenarios, all passing.
- Mutation check, interactive guard removed: both interactive scenarios fail, proving the
  scenarios reach the guarded branch.
- Mutation check, fallback exit removed: the non-interactive scenario fails on the exit
  code, proving the fallback is genuinely asserted.
- Mutation check, metadata write re-added inside the fallback: the non-interactive BDD
  scenario and the non-interactive unit test both fail on
  `Expected 'update_session_meta_status' to not have been called`, proving the
  scene-preservation contract is genuinely asserted.
- `make core-bdd-test` reports 42 failed and 746 passed against a pre-change baseline of
  44 failed and 737 passed, so this change introduces no regression.

Not verified:

- The stdout-retention check for the original incident cannot be reproduced, because
  that session produced no stdout file.
- The stdout-retention assertion in the BDD scenario observes the flush call rather than
  a real session stdout file, because the scenario runs in-process.
