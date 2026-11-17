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

# Issue: Session-meta socket test fails under the runner because the AF_UNIX path exceeds the kernel limit

## Symptom

`tests/unit/test_topsailai_workspace_session_meta.py::test_orphan_cleanup_retains_socket_endpoint`
fails on every run of the mandatory per-file runner, and also on a pristine checkout:

```text
tests/unit/test_topsailai_workspace_session_meta.py:725: OSError: AF_UNIX path too long
```

The same file passes when pytest is invoked directly with a short `--basetemp`:

```text
60 passed in 2.51s
```

## Root cause

The test binds a real Unix domain socket inside pytest's `tmp_path`:

```python
sock_path = os.path.join(
    session_meta.FOLDER_WORKSPACE_TASK, "orphan-socket.4246.session.sock"
)
endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
endpoint.bind(sock_path)
```

`FOLDER_WORKSPACE_TASK` is monkeypatched to `tmp_path` by `_isolate_meta_files`, so the
socket path is `tmp_path + "/orphan-socket.4246.session.sock"` (31 characters of filename).

`sun_path` in `sockaddr_un` is 108 bytes including the terminating NUL, so the usable path
length is 107 bytes. Measured on this host, the relationship is exactly linear:

```text
sock_path_len = basetemp_len + 44
```

| basetemp length | socket path length | bind result |
|---|---|---|
| 62 | 106 | ok |
| 63 | 107 | ok |
| 64 | 108 | `OSError: AF_UNIX path too long` |

The runner builds its basetemp as
`{RUN_TEMP_ROOT}/file-XXXXXXXX/attempt-0/basetemp`, where
`RUN_TEMP_ROOT = {PROJECT_ROOT}/.tmp/unit-runner`:

```text
/TopsailAI/src/topsailai/.tmp/unit-runner/file-k2dmpfai/attempt-0/basetemp
```

That is 74 characters, so the socket path is 118 bytes and the bind always fails. In the
pristine worktree the basetemp is 82 characters, giving 126 bytes, which also fails.

The test is therefore correct in intent and correct in isolation; it is incompatible with
any basetemp longer than 63 characters. The runner's own evidence layout is what pushes it
over the limit.

## Impact

One test file cannot pass through the mandated runner, so the full-suite result always
contains this failure. Because it is deterministic, it is easy to mistake for a regression
introduced by an unrelated change, and it masks whether the socket-retention behavior
itself still works.

The behavior under test is not broken: the test passes whenever the path is short enough,
which proves `cleanup_orphan_session_files` does retain a socket endpoint.

## Reproduction

Through the runner, three consecutive runs, all failing:

```text
PYTHONDONTWRITEBYTECODE=1 python tests/run_tests.py --workers 1 --timeout 120 --retries 0 \
  test_topsailai_workspace_session_meta.py
```

```text
[1/1] test_topsailai_workspace_session_meta.py: FAIL (4.541s)
[1/1] test_topsailai_workspace_session_meta.py: FAIL (5.070s)
[1/1] test_topsailai_workspace_session_meta.py: FAIL (6.202s)
```

Directly with a long basetemp, isolating the cause:

```text
python -m pytest tests/unit/test_topsailai_workspace_session_meta.py -q \
  --basetemp=/tmp/<60 chars>/<40 chars>
```

```text
1 failed, 59 passed
tests/unit/test_topsailai_workspace_session_meta.py:725: OSError: AF_UNIX path too long
```

Pristine worktree at `e0db1376`, with `PYTHONPATH` forced to its own roots and the imported
module verified to resolve inside that tree:

```text
topsailai     -> /tmp/pristine-arch/src/topsailai/__init__.py
session_meta  -> /tmp/pristine-arch/src/topsailai/workspace/session_meta.py
isolated = True
```

Result: `Total=1, Passed=0, Failed=1`, basetemp 82 characters, socket path 126 bytes.
The failure is pre-existing and not caused by any current change.

## Suggested fix

Make the socket path independent of the basetemp length. Options, in order of preference:

1. Bind the socket in a short dedicated directory instead of `tmp_path`, for example a
   `tempfile.mkdtemp(prefix="sock-", dir="/tmp")` that the test removes in `finally`, and
   monkeypatch `FOLDER_WORKSPACE_TASK` to that directory for this test only. This keeps the
   assertion on the real cleanup path while removing the path-length coupling.
2. Skip the test when the computed socket path exceeds 107 bytes, reporting the measured
   length. This preserves coverage on short-path hosts but silently drops it on long-path
   hosts, so it is a weaker option.
3. Shorten the runner's basetemp layout. This fixes only this runner and leaves the test
   fragile for any other long-path invocation, so it should not be the only change.

Whichever option is chosen, the test should assert the measured path length so a future
layout change produces a clear message instead of a kernel-level `OSError`.

## Resolution (2026-11-17)

Option 1 was implemented in two steps.

`7b573e70` (2026-11-17 14:37, "test: bind orphan socket endpoint in a short
directory") moved the bind out of `tmp_path` into a dedicated
`tempfile.mkdtemp(prefix="sm-")` directory and redirected
`FOLDER_WORKSPACE_TASK` to it, so the real inventory scan and the real socket
stay inside the assertion boundary. That commit made the runner pass.

Two gaps remained and are closed here:

1. `tempfile.mkdtemp` honours `TMPDIR`, so the fix replaced a basetemp coupling
   with a `TMPDIR` coupling. Measured with an inherited 84-character `TMPDIR`,
   the old form produced a 129-byte socket path and still failed with
   `OSError: AF_UNIX path too long`, while the same code with `dir="/tmp"`
   produced 48 bytes and bound successfully. The directory is now created with
   an explicit `dir=_SHORT_TEMP_ROOT` (`/tmp`), which is what this issue's
   option 1 actually specified.
2. The `finally` block called `os.unlink(sock_path)` unconditionally, so a failed
   bind was reported as `FileNotFoundError` from the cleanup instead of the real
   `OSError`. The unlink is now guarded by a `bound` flag, so the original
   failure survives.

The path-length assertion this issue asked for is now present. The test computes
`len(sock_path.encode("utf-8"))` and asserts it against `_MAX_SUN_PATH_BYTES`
(107), reporting the measured length and the path in the message. A simulated
future layout change produced:

```text
AssertionError: socket path is 134 bytes, over the AF_UNIX limit of 107: /tmp/sm-.../orphan-socket....session.sock
```

The limit is expressed in bytes rather than characters because a multi-byte
character consumes more than one byte of `sun_path`. This follows the existing
convention in `cli/cli_topsailai/agent_launch_attempt.py`, which already guards
its control socket with a byte-length check and a clear error message.

Verification:

- `python -m pytest tests/unit/test_topsailai_workspace_session_meta.py` ->
  60 passed.
- The same file with `TMPDIR` set to an 84-character path -> 60 passed. Before
  this change the same invocation failed with `OSError: AF_UNIX path too long`.
- The mandated runner,
  `python tests/run_tests.py --workers 1 --timeout 120 --retries 0
  test_topsailai_workspace_session_meta.py` -> `PASS (1.972s)`, 60 passed,
  0 failed.

The behaviour under test was never broken, as this issue already noted; only the
test's environment coupling was.
