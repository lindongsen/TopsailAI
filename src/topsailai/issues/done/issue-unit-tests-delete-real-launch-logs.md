---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Issue: unit tests delete real launch logs through the startup cleanup

## Symptom

A pytest run at 2026-11-16 14:27:20 executed the newly wired
`cleanup_expired_launch_logs()` against the real home and removed 225
diagnostic launch logs (372,283,985 B) from
`/root/.topsailai/workspace/task`. The log records

```
Removed 225 expired launch log(s) from /root/.topsailai/workspace/task
        (launch_log_retention.py:193) (unit-test:)
```

preceded by 225 `DELETED:` lines naming real paths. Real-home launch log
records dropped from 263 to 39, and expired records from 227 to 2.

## Root cause

Folder constants are computed at import time in
`workspace/folder_constants.py` from `TOPSAILAI_HOME`.
`tests/unit/conftest.py` did not isolate `TOPSAILAI_HOME` and did not patch
those constants, so any test that reached
`agent_shell._get_agent_chat_impl` ran the startup cleanup against the real
home. Clearing the environment variable in `clean_env` cannot undo an
already-frozen constant, and 13 production modules hold their own frozen
alias.

## Why the deletion logic was still correct

225 of 227 expired records were removed and exactly the 2 leased records
survived, matching the pre-run prediction byte for byte. The defect is test
isolation, not deletion authority.

## Blast radius

Eight test files construct a chat. Three of them mocked none of the startup
cleanups: `test_topsailai_workspace_agent_shell.py`,
`plugin_instruction/test_hosting.py`, `test_hooks_application_entries.py`.
A sentinel launch log survived `test_hosting.py` alone, so the exact trigger
was never identified; the isolation fixture makes identification unnecessary.

## Impact

235 of 251 launch logs had no `session.stdout` sibling, so for those
sessions the console record of that run is permanently lost. Conversation
content in the database is unaffected.

## Resolution

The defect was architectural, not a missing fixture. The launch log is a CLI
artifact: the detached supervisor creates it and relays the launcher console
stream into it. Its lifecycle therefore belongs to the CLI process that owns it,
not to the agent core that merely runs inside the launcher.

The core wiring was reverted in full, and the sweep now runs in `_supervise`'s
`finally` block in `cli/cli_topsailai/agent_launch_background.py`. Because the
sweep only executes in the supervisor process, it can never run inside a test
process, so this class of incident is removed structurally instead of being
guarded by a fixture.

An isolation fixture was prototyped while the core wiring existed. It was
discarded together with the wiring, because it is no longer needed for this
feature. Three constraints were learned from that prototype and remain relevant
to any future fixture that redirects the agent home:

- The temporary home must be short. Session channel endpoints are AF_UNIX
  sockets and the kernel rejects a path longer than 108 bytes, so a home
  created under the pytest basetemp makes socket tests fail with
  `AF_UNIX path too long`.
- The whole redirected directory family must be created, not only
  `workspace/task`, because lock, memory, skill and log folders are redirected
  too and a caller writing a lock file fails when its parent is absent.
- Cleanup must be session-scoped. A function-scoped finalizer runs before
  `monkeypatch` undoes the test's own doubles, so a test that patches `open` or
  `scandir` sees its double invoked during teardown and fails with an assertion
  meant for the test body.

Acceptance for the resolution: the agent core contains no reference to any CLI
module, and the reclaim sweep is reachable only from the supervisor exit path.

## Prevention

A cleanup must live in the layer that owns the artifact it deletes. The launch
log is created by the CLI supervisor, so the CLI reclaims it; the agent core
must never reach into the CLI to delete files it did not create. This keeps the
dependency direction one-way and keeps the sweep out of every test process.

Verify confinement with the log tag, not with a sentinel: this home is shared
with live agents and a sibling container, so a backdated sentinel is
legitimately deleted by production and its disappearance proves nothing.

## Verification

The resolution was verified by the layering invariant rather than by a
sentinel. A text search for `cli_topsailai` and `topsailai.cli` across every
production directory outside `cli/` returns no import, and a runtime check that
imports the core entry modules finds no CLI module in `sys.modules`. The
reclaim sweep is reachable only from `_supervise`'s `finally` block, which a
test process never executes.

The new test file `cli/tests/unit/topsailai/test_launch_log_reclaim.py` failed
12 of 13 cases in an isolated worktree at pristine HEAD and passes all 13 after
the change, so the tests observe the new behaviour rather than passing
trivially.
