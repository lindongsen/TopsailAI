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

Resolved by commit `87791479` ("fix: keep session artifacts and survive database io
failures"). The planned change in this issue was **not** implemented as written, because
it placed the decision in the wrong layer and would have converted a hard exit into an
uncaught traceback rather than a return to the prompt.

What was implemented instead:

- The process is never terminated on a database I/O failure. The exit path was removed
  from the write-failure handler entirely.
- Writes are classified. A committed write (a conversation record) reports the failure to
  its caller, which abandons the turn, keeps the answer that was already produced, and
  continues the session. A non-committed write (token counters, session metrics, access
  metadata, session renames) is logged and skipped.
- The recovery decision lives in the agent loop, which already resolves interactivity
  once per run, and is additionally guarded so a worker thread never waits for input.
  A non-interactive run or a worker thread ends with an explicit failure answer instead
  of an uncaught error.
- Session metadata, standard output and event records are retained on every exit path,
  including an abnormal one, and are reclaimed only together with the metadata that
  authorizes their removal.

Corrections to this issue's original text:

- The end-of-turn prompt is at `workspace/agent/agent_shell_base.py:782-784`, not at
  `:495` and `:497-499`. Line 495 is the loop header and 497-499 is the hard-interrupt
  branch.
- The crash table conflated session identifiers with process identifiers. The 05:52:48
  crash belonged to process `3552162`, not `1030280`.
- All three crashes originated from a token-counter write, not from a conversation
  message write. Treating every write as equally fatal is what made a lost counter kill
  a usable session.
- The stdout-retention claim could not be verified for the recorded incident, because
  that session directory contained no stdout file.

## Verification

Completed:

- An interactive session survives an injected database I/O failure and returns to the
  input prompt, with the already-produced answer printed.
- A non-interactive run and a worker thread end with an explicit failure answer instead
  of an uncaught exception.
- A failure while persisting the answer keeps the answer and continues the session.
- A last-resort net converts any remaining database I/O failure into a logged
  termination instead of a traceback.
- Session metadata, stdout and event records are retained on normal exit, on SIGTERM,
  and on a failed write.
- The full unit suite was compared against pristine `HEAD` in an isolated worktree: the
  41 failing files are identical in both trees, so this change introduces no regression.

Not verified:

- The stdout-retention check for the original incident cannot be reproduced, because
  that session produced no stdout file.
