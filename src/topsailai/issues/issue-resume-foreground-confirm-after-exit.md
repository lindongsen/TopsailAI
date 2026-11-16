---
maintainer: AI
author: DawsonLin
---
# Foreground resume reports a false failure after a successful session

A foreground `workspace resume` (default mode `dtach`) prints
`[ERROR] Session '<id>' did not answer on its control channel; the resumed agent is not running.`
and exits `4` after the resumed session has already run normally and been exited by the operator.

## Reproduction

1. `topsailai workspace resume -s <session_id>` in the foreground (no `-b`), default `dtach` mode.
2. Interact with the agent for any length of time.
3. Exit the agent normally (`CTRL D` / `EOF`).
4. The CLI prints the control-channel error and returns `4`.

Observed on session `wa-470fab9b316a`: resumed at `2026-11-16T08:39:35`, exited at
`2026-11-16T12:02:12` with `status: completed`, and the CLI then reported the error.

## Root cause

`resume_session_result()` calls `_confirm_resumed_startup()` **after**
`launch_agent_driver()` returns. In foreground `dtach` mode `launch_agent_driver()`
blocks in `child.wait()` until the wrapped child exits, so the confirmation always
runs post-mortem:

- `dtach -A` in the foreground blocks until the child exits (measured: `sleep 3` took
  `3.02s`), and returns `0` regardless of the child status (measured: child `exit 7`
  produced dtach status `0`).
- On normal exit the agent's `ControlServer.stop()` runs through `atexit` and calls
  `remove_socket_file()`, so no socket survives the run.
- `socket_heartbeat_alive()` returns `None` for an absent socket, so
  `_confirm_resumed_startup()` returns `heartbeat_unreachable`.
- Because the launcher status is `0`, the `code != 0` branch is skipped and the
  message is printed with exit code `4`.

The `foreground_raw_exited` exemption already encodes the correct reasoning — the
agent is the child, so its exit is the completed run and no channel survives it — but
it was applied only to `raw`. Foreground `dtach` has the same property on the normal
exit path, so the exemption is missing for the default foreground mode.

## Detection failure

`cli/tests/unit/topsailai/test_resume_startup_confirm.py` calls
`_confirm_resumed_startup()` directly with a live socket, and
`test_project_scope.py` patches `_confirm_resumed_startup()` out entirely. No test
exercises the real foreground path where the blocking wait precedes the confirmation,
so the ordering defect was invisible to the suite.

## Fix (implemented)

The confirmation now runs **concurrently with** the foreground wait instead of after
it. `launch_agent_driver()` gained an `on_spawned` callback that fires immediately
after the child is created and before `child.wait()`, and `resume_session_result()`
uses it to start a daemon probe thread. The probe still uses the heartbeat as the
authority, so a driver that dies before publishing a channel is never trusted.

`_confirm_resumed_startup()` now accepts `code=None`, meaning the launcher status is
not known yet because the probe runs while the launch is still in progress. An unknown
status is not a failure, so the launch-failure short circuit is skipped.

When the child is never created (a spawn failure, or a caller that patches the launch
boundary), the probe never starts and the confirmation runs after the launch exactly
as before, which keeps a spawn failure and a foreground `raw` run on their original
paths.

## Verification (executed)

- `cli/tests/unit/topsailai/test_resume_foreground_confirm.py` (new, 4 tests): a run
  that publishes then removes its socket is confirmed; a channel that survives the
  wait is confirmed; a run that never publishes a channel is refused with `4`; the
  probe thread is already alive while the blocking wait is in progress.
- Negative control in an isolated worktree at pristine `HEAD` (`579691e2`), with
  `PYTHONPATH` forced to that tree and the imported module path verified: the two
  ordering tests fail there (`4 != 0`, probe not running) while the two safety tests
  pass on both trees, so the new tests observe the ordering rather than the API.
- Full CLI unit suite: `4340 passed`.
- Resume BDD scenarios: `5 passed`.
- Manual: `cli/tests/manual/verify_resume_foreground_confirm.py` driven through tmux
  against a real unix socket that answers the real control protocol; the resume
  returns `0` with `startup_reason: heartbeat_answered` after the agent removed its
  socket and exited.
